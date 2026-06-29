"""Produce a signed, schema-valid Peakstone result bundle from a run.

A bundle is the reproducibility contract (see schema/result-bundle.schema.json): it embeds the exact
model identity (repo + file SHA-256 + quant + engine + sampling + serve flags), the environment,
content-hashed challenges, transcripts, and scores — content-addressed and ed25519-signed so a
deterministic result is independently re-runnable.

This layer is auth-agnostic: it signs with the local key (engine/keys.py) and embeds pubkey +
signature; binding a pubkey to an account is a server-side concern.

TODO (tracked in PLAN.md): hf_revision pinning, params_total/active, sampling seed (deterministic
runs), full (untruncated) transcripts, robust split-GGUF + multi-engine identity.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import jsonschema

from . import keys, paths

SCHEMA_PATH = paths.schema_path()
BUNDLE_VERSION = "1.0"
SAFETY_SCORINGS = {"injection", "refusal", "hallucination", "secure-code", "adherence"}


# --------------------------------------------------------------------------- #
# hashing
# --------------------------------------------------------------------------- #
def canonical_bytes(obj) -> bytes:
    """Deterministic JSON encoding for content-addressing (sorted keys, compact)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha256_file_cached(path: Path) -> str:
    """SHA-256 of a (possibly huge) file, cached by (path, size, mtime-ns) under PEAKSTONE_HOME."""
    st = path.stat()
    cache_file = keys.KEY_DIR / "filehash-cache.json"
    cache = {}
    if cache_file.exists():
        try:
            cache = json.loads(cache_file.read_text())
        except Exception:  # noqa: BLE001
            cache = {}
    # nanosecond mtime: a same-second rebuild at the same size must not return a stale hash
    key = f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}"
    if key in cache:
        return cache[key]
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 << 20), b""):
            h.update(chunk)
    digest = h.hexdigest()
    cache[key] = digest
    keys.KEY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = cache_file.with_suffix(".json.tmp")     # atomic write — concurrent runs can't corrupt it
    tmp.write_text(json.dumps(cache))
    tmp.replace(cache_file)
    return digest


def _model_file_hash(file_path: Path) -> tuple[str, bool]:
    """Hash a model file → (digest, verified). For a split GGUF (NNNNN-of-NNNNN) hash all parts.
    `verified` is False for any sentinel (skipped/missing/incomplete) so the bundle never passes off
    a placeholder as a real reproducibility anchor."""
    if os.environ.get("PEAKSTONE_SKIP_FILE_HASH"):
        return "(skipped)", False
    if not file_path.exists():
        return "(missing)", False
    m = re.search(r"-(\d{5})-of-(\d{5})\.gguf$", file_path.name)
    if not m:
        return _sha256_file_cached(file_path), True
    total = int(m.group(2))
    parts = sorted(file_path.parent.glob(re.sub(r"-\d{5}-of-\d{5}\.gguf$", "-*-of-*.gguf", file_path.name)))
    if len(parts) != total:
        return "(incomplete-split)", False     # don't silently hash only part 1
    return _sha256_bytes("".join(_sha256_file_cached(p) for p in parts).encode()), True


def _hash_challenge_dir(d: Path) -> str:
    """Content hash of a challenge: meta.toml + spec.md + every file under tests/ (sorted)."""
    h = hashlib.sha256()
    files = [d / "meta.toml", d / "spec.md"]
    files += sorted((d / "tests").rglob("*")) if (d / "tests").is_dir() else []
    for f in files:
        if f.is_file():
            h.update(f.relative_to(d).as_posix().encode())
            h.update(b"\0")
            h.update(f.read_bytes())
    return h.hexdigest()


def challenge_hashes(challenges_dir: Path) -> dict[str, str]:
    """Map challenge id -> content hash, by reading every meta.toml in the corpus."""
    out: dict[str, str] = {}
    for meta in challenges_dir.rglob("meta.toml"):
        d = meta.parent
        if any(p[:1] in ("_", ".") for p in d.relative_to(challenges_dir).parts):
            continue
        try:
            cid = tomllib.loads(meta.read_text())["id"]
        except Exception:  # noqa: BLE001
            continue
        out[cid] = _hash_challenge_dir(d)
    return out


def challenge_publication(challenges_dir: Path) -> dict[str, dict]:
    """Map challenge id -> {published_at, source} from meta.toml. The publish date is the
    challenge side of the contamination check (compared against model.release_date). Local
    estimate; the platform overrides with its unforgeable first-seen timestamp per hash."""
    out: dict[str, dict] = {}
    for meta in challenges_dir.rglob("meta.toml"):
        d = meta.parent
        if any(p[:1] in ("_", ".") for p in d.relative_to(challenges_dir).parts):
            continue
        try:
            m = tomllib.loads(meta.read_text())
        except Exception:  # noqa: BLE001
            continue
        if m.get("published_at"):
            out[m["id"]] = {"published_at": str(m["published_at"]),
                            "source": m.get("published_at_source", "author")}
    return out


# --------------------------------------------------------------------------- #
# environment + model identity
# --------------------------------------------------------------------------- #
def _nominal_ram_gib(total_bytes: int) -> int:
    """Nominal installed RAM in GiB. MemTotal is reported in binary units and always a bit below the
    installed size (firmware reserves a few hundred MB), so round the usable GiB UP to the next even
    number — a 64 GiB machine reads 64, not the misleading 67 a decimal (/1e9) divide produces."""
    import math
    return math.ceil(total_bytes / 2**30 / 2) * 2


def capture_env(gpu_meta: dict | None, mem_used: dict | None = None) -> dict:
    env: dict = {}
    gpu_meta = gpu_meta or {}
    env["gpu"] = gpu_meta.get("name", "unknown")
    if gpu_meta.get("driver_version"):
        env["driver"] = gpu_meta["driver_version"]
    # CPU model name (prettier than platform.processor() on Linux/macOS)
    cpu = platform.processor() or "unknown"
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                 capture_output=True, text=True, timeout=5)
            cpu = out.stdout.strip() or cpu
        else:
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
    except Exception:  # noqa: BLE001
        pass
    env["cpu"] = cpu
    try:
        env["ram_gb"] = _nominal_ram_gib(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except Exception:  # noqa: BLE001
        pass
    # total GPU memory — the "fits in <=X GB VRAM" leaderboard facet keys on this. On Apple Silicon
    # memory is unified, so the GPU's budget is the machine's total RAM (== ram_gb above).
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
            env["vram_gb"] = round(int(out.stdout.strip()) / 1024**3, 1)
        else:
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=10)
            env["vram_gb"] = round(int(out.stdout.split("\n")[0]) / 1024, 1)
    except Exception:  # noqa: BLE001
        pass
    # measured footprint of the loaded model: VRAM in use + host RAM (RSS). The leaderboard shows these
    # as "VRAM/RAM used" so a model too big for VRAM (spilled to RAM) reads sensibly. Totals above stay
    # for the "fits ≤X GB VRAM" facet.
    mem_used = mem_used or {}
    if mem_used.get("vram_mib") is not None:
        env["vram_used_gb"] = round(mem_used["vram_mib"] / 1024, 1)
    if mem_used.get("ram_mib") is not None:
        env["ram_used_gb"] = round(mem_used["ram_mib"] / 1024, 1)
    env["os"] = platform.platform()
    return env


def _engine_info() -> dict:
    """Best-effort llama.cpp version (the only served engine today)."""
    binary = (os.environ.get("LLAMA_SERVER") or shutil.which("llama-server")
              or str(Path.home() / "llama.cpp" / "build" / "bin" / "llama-server"))
    info = {"name": "llama.cpp", "version": "unknown"}
    if shutil.which(binary) or Path(binary).exists():
        try:
            out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10)
            # llama.cpp prints e.g. "version: 1 (ef8268f)" — keep the whole string (the commit
            # hash is the reproducible part; the leading number is just a local build counter).
            m = re.search(r"version:\s*(.+)", (out.stderr or "") + (out.stdout or ""))
            if m:
                info["version"] = m.group(1).strip()
        except Exception:  # noqa: BLE001
            pass
    return info


def _quant_from_filename(name: str) -> str:
    # separator before the quant token is "-" for most repos but "." for some unsloth files
    # (e.g. Phi-4-mini-instruct.Q8_0.gguf, ...BF16.gguf).
    m = re.search(r"[-.]((?:UD-)?(?:IQ|Q|TQ|BF|F)\w*?)(?:-\d{5}-of-\d{5})?\.gguf$", name)
    return m.group(1) if m else "unknown"


def reasoning_mode(serve_flags, reasoning_token_values) -> str | None:
    """The reasoning RUN CONDITION, auto-derived (no submitter declaration). A chain-of-thought model
    run with thinking on vs off is two distinct runs — faceted, never collapsed — like a quant.
      'on'   — the model actually emitted chain-of-thought (reasoning_tokens > 0) — EVIDENCE wins,
               even if a budget flag tried to disable it (some models think anyway)
      'off'  — reasoning explicitly disabled (--reasoning-budget 0) and none was produced
      None   — not a reasoning model / not applicable (neither signal present).
    Evidence is checked first so a runtime override (PEAKSTONE_REASONING_BUDGET, reflected in
    serve_flags below) and the model's real behaviour can't disagree with the label."""
    if any((rt or 0) > 0 for rt in reasoning_token_values):
        return "on"
    if serve_flags and "--reasoning-budget 0" in serve_flags:
        return "off"
    return None


def _effective_flags(flags: str) -> str:
    """Serve flags as ACTUALLY served — applies the PEAKSTONE_REASONING_BUDGET override (mirrors
    serve.sh) so a runtime thinking on/off choice is faithfully recorded in the bundle, not just the
    model's configured flags."""
    rb = os.environ.get("PEAKSTONE_REASONING_BUDGET")
    if rb not in (None, ""):
        flags = re.sub(r"--reasoning-budget\s+\S+", "", flags).strip()
        flags = (flags + f" --reasoning-budget {rb}").strip()
    return flags


def _sampling(flags: str, run_cfg: dict) -> dict:
    """Effective sampling: temperature from config [run] (the bench overrides it on the request);
    top_p/top_k/repeat_penalty from the served model flags (the request does not override those)."""
    s: dict = {"temperature": run_cfg.get("temperature", 0.2)}
    for flag, key in [("--top-p", "top_p"), ("--top-k", "top_k"), ("--repeat-penalty", "repeat_penalty")]:
        m = re.search(re.escape(flag) + r"\s+([0-9.]+)", flags)
        if m:
            s[key] = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
    if run_cfg.get("max_tokens"):
        s["max_tokens"] = run_cfg["max_tokens"]
    # NOTE: no seed captured yet -> temperature>0 runs are not bit-reproducible (PLAN.md TODO).
    return s


def _ctx_override(default):
    """The served context length: PEAKSTONE_CTX (chosen at run time) overrides the configured ctx."""
    ov = os.environ.get("PEAKSTONE_CTX")
    if ov:
        try:
            return int(ov)
        except ValueError:
            pass
    return default


def model_identity(model_name: str, run_cfg: dict) -> dict:
    """Assemble the model block from serve/models.toml + file hash + engine version (best-effort)."""
    try:
        reg = tomllib.loads(paths.models_toml().read_text())
    except Exception:  # noqa: BLE001
        reg = {}
    cfg = reg.get(model_name)
    if not cfg:  # reference run or model not in the local registry
        return {
            "family": model_name, "artifact": "(unregistered)", "hf_repo": "(local/unknown)",
            "file_sha256": "(none)", "file_sha256_verified": False,
            "engine": {"name": "unknown", "version": "unknown"},
            "sampling": _sampling("", run_cfg),
        }
    file = cfg.get("file", "")
    sha, verified = _model_file_hash(paths.repo_root() / file) if file else ("(none)", False)
    model = {
        # `family` groups quant variants for comparison; declare a shared family in models.toml to
        # compare e.g. UD-Q4_K_XL vs UD-Q6_K of the same model. Defaults to the registry name.
        "family": cfg.get("family") or model_name,
        "artifact": _quant_from_filename(file),
        "hf_repo": cfg.get("repo", "(unknown)"),
        "file_sha256": sha,
        "file_sha256_verified": verified,
        "context": _ctx_override(cfg.get("ctx")),

        "serve_flags": _effective_flags(cfg.get("flags", "")),
        "engine": _engine_info(),
        "sampling": _sampling(_effective_flags(cfg.get("flags", "")), run_cfg),
    }
    # Contamination boundary. release_date is the conservative, unforgeable cutoff (the official
    # held-out metric keys off it); training_cutoff is the optional, self-reported tighter bound.
    # Both come from serve/models.toml when known — omitted (not guessed) otherwise.
    if cfg.get("release_date"):
        model["release_date"] = str(cfg["release_date"])
    if cfg.get("training_cutoff"):
        model["training_cutoff"] = str(cfg["training_cutoff"])
    return model


# --------------------------------------------------------------------------- #
# result mapping + assembly
# --------------------------------------------------------------------------- #
def _verification(row: dict) -> str:
    if row.get("verification"):                  # explicit (e.g. goal-state-env from the env harness)
        return row["verification"]
    if row.get("scoring") == "judge" or (row.get("judge_detail", {}) or {}).get("scores"):
        return "llm-judge"
    return "deterministic-tests"


def _token_metrics(row: dict, served_ctx: int | None) -> dict:
    """Context-efficiency metrics for a result, derived from measured token usage. Only emitted when
    generation was actually measured (completion_tokens > 0) — a 0/None placeholder means "unmeasured",
    not "free", and would poison the ascending efficiency aggregates. ctx_limited flags a result whose
    prompt+generation hit the served window (its tokens are censored and its score depressed by
    truncation, not capability — excluded from honest efficiency aggregates downstream)."""
    ct = row.get("completion_tokens")
    if not isinstance(ct, int) or ct <= 0:
        return {}
    pt = row.get("prompt_tokens") if isinstance(row.get("prompt_tokens"), int) else 0
    m = {"gen_tokens": ct, "prompt_tokens": pt, "tokens_to_solve": pt + ct}
    rt = row.get("reasoning_tokens")
    if isinstance(rt, int):                       # only when the server reported it (else unknown)
        m["reasoning_tokens"] = rt
    if isinstance(served_ctx, int) and served_ctx > 0:
        m["ctx_limited"] = 1 if (pt + ct) >= 0.95 * served_ctx else 0
    return m


def _result(row: dict, chash: dict, judge_model: str | None, cpub: dict | None = None,
            served_ctx: int | None = None) -> dict:
    score: dict = {"final": round(float(row.get("final_score", 0.0)), 4)}
    if row.get("total"):
        score["passed"] = row.get("passed", 0)
        score["total"] = row["total"]
    r: dict = {
        "challenge_id": row["challenge"],
        "challenge_hash": chash.get(row["challenge"], "(unknown)"),
        "verification": _verification(row),
        "score": score,
    }
    pub = (cpub or {}).get(row["challenge"])
    if pub:
        r["published_at"] = pub["published_at"]
        r["published_at_source"] = pub.get("source", "author")
    if row.get("type") or row.get("category"):
        r["category"] = row.get("type") or row.get("category")
    if isinstance(row.get("difficulty"), int) and 1 <= row["difficulty"] <= 5:
        r["difficulty"] = row["difficulty"]
    for k in ("attempts", "passed_on_attempt", "tok_per_s", "latency_s"):
        if row.get(k) is not None:
            r[k] = row[k]
    nums = {}
    if isinstance(row.get("metrics"), dict):
        nums = {k: v for k, v in row["metrics"].items() if isinstance(v, (int, float))}
    nums.update(_token_metrics(row, served_ctx))   # context-efficiency axes (gen/prompt/total tokens)
    if nums:
        r["metrics"] = nums
    if isinstance(row.get("env"), dict) and row["env"]:
        r["env"] = row["env"]   # goal-state-env provenance: provider, image digests, checks, turns
    if row.get("mode") == "planner":
        r["mode"] = "planner"
        r["coder_model"] = row.get("coder_model")
    tr: dict = {}
    if row.get("planner_response"):
        tr["plan"] = row["planner_response"]
    if row.get("response"):
        tr["raw_output"] = row["response"]
    if row.get("stdout"):
        tr["stdout"] = row["stdout"]
    if row.get("stderr"):
        tr["stderr"] = row["stderr"]
    if row.get("error"):
        tr["error"] = row["error"]          # e.g. "repetition-loop" — a distinct failure type
    if tr:
        r["transcript"] = tr
    jd = row.get("judge_detail") or {}
    if jd.get("scores"):
        r["judge"] = {"model": judge_model or "unknown", "scores": jd["scores"]}
    return r


def produce_bundle(meta: dict, results: list[dict], *, harness_version: str = "0.1.0",
                   sign: bool = True) -> dict:
    """Assemble a schema-valid, content-addressed, (optionally) signed result bundle."""
    run_cfg = {}
    try:
        run_cfg = tomllib.loads(paths.config_path().read_text()).get("run", {})
    except Exception:  # noqa: BLE001
        pass

    model_name = (meta.get("planner_model") or (meta.get("models") or ["unknown"])[0])
    chash = challenge_hashes(paths.challenges_dir())
    cpub = challenge_publication(paths.challenges_dir())
    model = model_identity(model_name, run_cfg)
    model["reasoning"] = reasoning_mode(model.get("serve_flags"),
                                        (r.get("reasoning_tokens") for r in results))
    served_ctx = model.get("context")              # the window each result is judged for ctx-truncation against

    bundle_results = [_result(r, chash, meta.get("judge"), cpub, served_ctx) for r in results]
    # hash the sorted list as canonical JSON (self-delimiting) — bare concatenation is ambiguous
    # (["ab","c"] and ["a","bc"] would collide) for a value that pins the exact challenge set.
    suite_hash = _sha256_bytes(canonical_bytes(sorted(r["challenge_hash"] for r in bundle_results)))

    bundle: dict = {
        "bundle_version": BUNDLE_VERSION,
        "submitted_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "harness": {"name": "peakstone-engine", "version": harness_version},
        "model": model,
        "environment": capture_env(meta.get("gpu"), meta.get("mem_used")),
        "suite": {"id": meta.get("suite_id", "adhoc"),
                  "version": meta.get("suite_version", meta.get("timestamp", "unversioned")),
                  "content_hash": suite_hash},
        "results": bundle_results,
    }
    if meta.get("coder_model"):
        bundle["harness"]["coder_model"] = meta["coder_model"]
    # Negative data: a non-viable run (model looped out of every category it tried, passing nothing) is
    # recorded as a verdict so the leaderboard can show which (quant, ctx, reasoning) configs aren't
    # worth testing. `abandoned_categories` is carried even on otherwise-viable runs for transparency.
    if meta.get("run_status"):
        bundle["run_status"] = meta["run_status"]
    if meta.get("run_verdict"):
        bundle["run_verdict"] = meta["run_verdict"]
    if meta.get("abandoned_categories"):
        bundle["abandoned_categories"] = list(meta["abandoned_categories"])

    # content-address + sign
    if sign:
        priv, pub = keys.load_or_create_keypair()
        sign_inplace(bundle, priv, pub)
    else:
        bundle["bundle_hash"] = _sha256_bytes(canonical_bytes(_without_sig(bundle)))

    _validate(bundle)
    return bundle


def sign_inplace(bundle: dict, priv, pub: str) -> dict:
    """Set submitter.pubkey, content-address (only `signature` excluded → the hash BINDS the pubkey),
    then sign. The canonical way to (re)sign a bundle; reuse it so the pubkey can't be swapped after
    signing to re-attribute someone else's run."""
    bundle["submitter"] = {"pubkey": pub}
    bundle["bundle_hash"] = _sha256_bytes(canonical_bytes(_without_sig(bundle)))
    bundle["submitter"]["signature"] = keys.sign(priv, bundle["bundle_hash"].encode())
    return bundle


def _without_sig(bundle: dict) -> dict:
    """The hashed view: drop `bundle_hash` and only `submitter.signature` — submitter.pubkey/handle
    stay in, so they're bound by the content-address."""
    b = {k: v for k, v in bundle.items() if k != "bundle_hash"}
    if isinstance(b.get("submitter"), dict):
        b["submitter"] = {k: v for k, v in b["submitter"].items() if k != "signature"}
    return b


def _validate(bundle: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text())
    jsonschema.validate(bundle, schema)


def write_bundle(bundle: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False))
    return path
