"""Measure & resolve model capabilities so levels/relevance pick the right axes automatically.

Capabilities are facts about a model we can TEST, not hand-guesses. Gating caps (`tools`, `agentic`)
decide which axes a model attempts; descriptive caps (`reasoner`, `multimodal`, `long_ctx`) are for
display/filtering. Four sources, in precedence:

    declared (serve/models.toml `capabilities`)  >  probed/observed (local cache)  >  inferred (ctx)

- probe   : `classify()` runs tiny probes and writes definitive caps (incl. negatives) to the cache.
- observe : `observe()` derives POSITIVES from any run's results (or the public leaderboard) — never a
            negative (one non-engagement isn't proof).
- inferred: from the registry context length.

The cache is tri-state (a cap is present only when known true/false); the API supplies observed caps
from public runs (see api/ingest.py) which the CLI can import into the cache.
"""
from __future__ import annotations

import datetime as dt
import json
import tomllib
from pathlib import Path

from . import keys, matheval, paths

CACHE_PATH = keys.KEY_DIR / "capabilities.json"
GATING = ("tools", "agentic")
DESCRIPTIVE = ("reasoner", "multimodal", "long_ctx")
_MIN_CTX_AGENTIC = 16384
_MIN_CTX_LONG = 65536

# a 1x1 PNG — enough to see whether the model accepts/engages image input at all
_TINY_PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4"
             "2mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


# --------------------------------------------------------------------------- #
# cache
# --------------------------------------------------------------------------- #
def load_cache(path: Path | None = None) -> dict:
    p = path or CACHE_PATH
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def update_cache(model: str, caps: dict, source: str, path: Path | None = None) -> None:
    """Merge known caps (cap->bool) into the cache for a model."""
    p = path or CACHE_PATH
    data = load_cache(p)
    entry = data.setdefault(model, {"caps": {}})
    entry["caps"].update({k: bool(v) for k, v in caps.items()})
    entry["source"] = source
    entry["at"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(p)


def _model_cfg(model: str, models_toml: Path | None = None) -> dict:
    try:
        reg = tomllib.loads((models_toml or paths.models_toml()).read_text())
    except (OSError, ValueError):
        reg = {}
    return reg.get(model) or {}


def effective_capabilities(model: str, *, models_toml: Path | None = None,
                           cache_path: Path | None = None) -> set[str]:
    """Resolve a model's gating capabilities: inferred (ctx) -> cache (known true/false) -> declared.

    Honest framing (review R20): the DEFAULTS are optimistic, not measured — `tools` is assumed
    True and `agentic` is assumed True when ctx is unknown, so gating is attempt-by-default and
    only EXCLUDES on evidence (a declared false, a cached probe/observation, or a ctx that's
    provably too small). Measurement refines the picture (observe/classify feed the cache); it
    does not produce the initial one."""
    cfg = _model_cfg(model, models_toml)
    ctx = cfg.get("ctx")
    known: dict[str, bool] = {"tools": True}
    if isinstance(ctx, int):
        known["agentic"] = ctx >= _MIN_CTX_AGENTIC
        if ctx >= _MIN_CTX_LONG:
            known["long_ctx"] = True
    else:
        known["agentic"] = True
    # cache (probed/observed) overrides
    for cap, val in (load_cache(cache_path).get(model, {}).get("caps", {}) or {}).items():
        known[cap] = bool(val)
    # declared wins; the gating caps are fully specified by the list (absent => false)
    decl = cfg.get("capabilities")
    if decl is not None:
        decl = set(decl)
        for g in GATING:
            known[g] = g in decl
        for d in DESCRIPTIVE:
            if d in decl:
                known[d] = True
    return {c for c, v in known.items() if v}


# --------------------------------------------------------------------------- #
# probes (best-effort; each isolated so one failure doesn't sink the rest)
# --------------------------------------------------------------------------- #
_PROBE_TOOL = [{"type": "function", "function": {
    "name": "calc", "description": "Evaluate an arithmetic expression and return the number.",
    "parameters": {"type": "object", "properties": {"expr": {"type": "string"}}, "required": ["expr"]}}}]


def probe_tools(client, model, run_cfg) -> bool:
    """True iff the model emits a well-formed tool call when one is clearly useful."""
    for prompt in ("Compute 23*19 by calling the calc tool, then state the number.",
                   "Use the calc tool to evaluate 100-37, then answer."):
        res = client.chat_tools(model, [{"role": "user", "content": prompt}], _PROBE_TOOL,
                                temperature=0.0, max_tokens=512,
                                timeout=run_cfg.get("request_timeout", 300))
        msg = res.get("message") or {}
        for tc in (msg.get("tool_calls") or []):
            if (tc.get("function") or {}).get("name"):
                return True
    return False


def probe_reasoner(client, model, run_cfg) -> bool:
    """True if the model solves a multi-step problem or emits a real chain-of-thought."""
    res = client.chat(model, [{"role": "user", "content":
        "A tank holds 200 L. It drains at 8 L/min for 7 min, then fills at 5 L/min for 12 min. "
        "How many litres are in it? Put the final answer in \\boxed{}."}],
        temperature=0.0, max_tokens=run_cfg.get("max_tokens", 4096),
        timeout=run_cfg.get("request_timeout", 300))
    if res.error:
        return False
    got = matheval.extract_answer(res.text) or matheval.extract_answer(res.reasoning)
    return matheval.answers_match(got, "204") or len((res.reasoning or "")) > 200


def probe_multimodal(client, model, run_cfg):
    """Stub — multimodal is not probed yet (declare it in models.toml, or it's observed later via a
    vision suite). Returns None = unknown so classify() doesn't record it. (_TINY_PNG kept for the
    eventual image probe.)"""
    return None


def probe_agentic(client, model, run_cfg, *, timeout=600) -> bool | None:
    """True if the model can drive the repo agent loop (edit a synthetic repo via tools). Needs docker;
    returns None when docker is unavailable (leave unknown)."""
    from . import swebench
    import shutil
    import subprocess
    if not shutil.which("docker"):
        return None
    try:
        if subprocess.run(["docker", "info"], capture_output=True, timeout=10).returncode != 0:
            return None
    except (OSError, subprocess.SubprocessError):
        return None
    inst = {
        "instance_id": "cap-probe-add",
        "fixtures": {"mymod.py": "def add(a, b):\n    return a - b\n",
                     "test_mod.py": "from mymod import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"},
        "setup_cmds": ["pip install -q pytest"], "test_patch": "", "test_cmds": ["python -m pytest"],
        "FAIL_TO_PASS": ["test_mod.py::test_add"], "PASS_TO_PASS": [],
    }
    res = swebench.run_repo_patch_task(inst, client=client, model=model, run_cfg=run_cfg,
                                      agent=True, timeout=timeout)
    if res["resolved"]:
        return True
    return "edits=" in res.get("transcript", "") and "edits=0" not in res.get("transcript", "")


def classify(model, client, run_cfg, *, docker=True, cache_path=None) -> dict:
    """Run the probes, write the definitive caps to the cache, return them."""
    caps: dict[str, bool] = {}
    for name, fn in (("tools", probe_tools), ("reasoner", probe_reasoner)):  # multimodal: stub for now
        try:
            caps[name] = bool(fn(client, model, run_cfg))
        except Exception:  # noqa: BLE001
            pass
    if docker:
        try:
            ag = probe_agentic(client, model, run_cfg)
            if ag is not None:
                caps["agentic"] = ag
        except Exception:  # noqa: BLE001
            pass
    if caps.get("agentic"):
        caps["tools"] = True   # agentic implies tool use
    update_cache(model, caps, "probed", cache_path)
    return caps


# --------------------------------------------------------------------------- #
# observe (positives from results — local run rows or, via api/ingest, bundle results)
# --------------------------------------------------------------------------- #
def observe(results, *, score_key="final_score", cat_key="category") -> dict:
    """Positive capabilities evidenced by a set of result rows. Never asserts a negative."""
    caps: dict[str, bool] = {}
    for r in results:
        cat = r.get(cat_key) or r.get("type")
        score = r.get(score_key, 0) or 0
        if (r.get("scoring") == "tool_calls" or cat == "tool-calling") and score > 0:
            caps["tools"] = True
        if r.get("verification") == "goal-state-env" and score > 0:
            caps["agentic"] = True
            caps["tools"] = True
        if cat == "math" and score > 0:
            caps["reasoner"] = True
        if cat == "long-context" and score > 0:   # actually used a long window, not just declared one
            caps["long_ctx"] = True
    return caps
