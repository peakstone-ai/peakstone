"""SWE-bench-style repo-patch harness.

Given a SWE-bench instance (repo, base_commit, test_patch, FAIL_TO_PASS, PASS_TO_PASS, ...), run the
repo's own test suite in a Docker sandbox after applying a candidate patch, and check that every
FAIL_TO_PASS test now passes and every PASS_TO_PASS test still passes ("resolved", like SWE-bench).

Candidate patch comes one-shot (oracle): the model is shown the issue + the files the gold patch
touches and asked for a unified diff. The patch step is the single swappable seam — a future agent
loop (browse/edit/run tools, reusing env/agent.py's chat_tools pattern) replaces just that.

Setup modes (from the instance):
  * synthetic  — `fixtures` {path: content} seeded into the container; no clone (tests use no network).
  * prebuilt   — `image` set: the repo is already at /testbed with deps installed (no network).
  * generic    — base python:3.12: git clone <repo>@base_commit + pip install -e . (best-effort; needs egress).
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
import time
import urllib.request

from . import bandwidth, keys

WORK = "/testbed"
GENERIC_IMAGE = "python:3.12"
_IMG_SIZE_CACHE = keys.KEY_DIR / "imagesizes.json"


def image_size(image: str) -> int | None:
    """Compressed download size (bytes) of a Docker image tag via Docker Hub's API. Cached. Used for
    bandwidth-aware estimates (no pull needed) and to record throughput after a real pull."""
    try:
        cache = json.loads(_IMG_SIZE_CACHE.read_text())
    except (OSError, ValueError):
        cache = {}
    if image in cache:
        return cache[image]
    repo, _, tag = image.partition(":")
    ns_name = repo if "/" in repo else f"library/{repo}"
    try:
        with urllib.request.urlopen(  # noqa: S310 (trusted host)
                f"https://hub.docker.com/v2/repositories/{ns_name}/tags/{tag or 'latest'}", timeout=8) as r:
            full = json.load(r).get("full_size")
    except Exception:  # noqa: BLE001
        full = None
    if full:
        cache[image] = int(full)
        _IMG_SIZE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        try:
            _IMG_SIZE_CACHE.write_text(json.dumps(cache))
        except OSError:
            pass
    return int(full) if full else None


def _docker(*args, timeout=120, stdin=None):
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          timeout=timeout, input=stdin)


class RepoSandbox:
    """A single long-lived container; commands via `docker exec`, files via stdin."""

    def __init__(self, image: str, *, network: bool, prune: bool = False):
        self.image = image
        self.prune = prune              # remove the image after teardown (stream one-at-a-time, bounded disk)
        # pull explicitly (when absent) so we can time it and record a bandwidth sample for estimates.
        if _docker("image", "inspect", image, "-f", "{{.Id}}", timeout=30).returncode != 0:
            t0 = time.monotonic()
            if _docker("pull", image, timeout=1800).returncode == 0:
                sz = image_size(image)
                if sz:
                    bandwidth.record(sz, time.monotonic() - t0, "docker")
        net = [] if network else ["--network", "none"]
        r = _docker("run", "-d", "--rm", *net, image, "sleep", "infinity", timeout=900)
        if r.returncode != 0:
            raise RuntimeError(f"docker run {image} failed: {r.stderr[-300:]}")
        self.cid = r.stdout.strip()
        _docker("exec", self.cid, "mkdir", "-p", WORK)   # so `-w WORK` execs are valid from the start

    def exec(self, cmd: str, *, timeout=300, workdir=WORK):
        return _docker("exec", "-w", workdir, self.cid, "bash", "-lc", cmd, timeout=timeout)

    def write(self, path: str, content: str, *, workdir=WORK):
        return _docker("exec", "-i", "-w", workdir, self.cid, "bash", "-lc",
                       f'mkdir -p "$(dirname {shlex.quote(path)})"; cat > {shlex.quote(path)}',
                       stdin=content, timeout=120)

    def read(self, path: str, *, workdir=WORK) -> str | None:
        r = _docker("exec", "-w", workdir, self.cid, "cat", path, timeout=30)
        return r.stdout if r.returncode == 0 else None

    def digest(self) -> str:
        r = _docker("image", "inspect", self.image, "-f", "{{index .RepoDigests 0}}")
        return r.stdout.strip() if (r.returncode == 0 and r.stdout.strip()) else self.image

    def teardown(self):
        _docker("rm", "-f", self.cid, timeout=60)
        if self.prune:
            _docker("rmi", "-f", self.image, timeout=120)   # keep peak disk to ~one image

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.teardown()


# --------------------------------------------------------------------------- #
# parsing helpers (pure)
# --------------------------------------------------------------------------- #
_DIFF_FILE = re.compile(r"^\+\+\+ b/(.+)$", re.M)
_PYTEST_LINE = re.compile(r"^(PASSED|FAILED|ERROR|SKIPPED)\s+(\S+)", re.M)
_FENCE = re.compile(r"```(?:diff|patch)?\s*\n(.*?)```", re.S)


def patched_files(diff: str) -> list[str]:
    """Paths a unified diff modifies (the `+++ b/...` targets)."""
    return [m for m in _DIFF_FILE.findall(diff or "") if m != "/dev/null"]


def parse_pytest(output: str) -> dict[str, str]:
    """{test_node_id: 'passed'|'failed'|'error'|'skipped'} from `pytest -rA` output."""
    out: dict[str, str] = {}
    for status, nid in _PYTEST_LINE.findall(output or ""):
        out[nid] = status.lower()
    return out


def extract_diff(text: str) -> str:
    """Pull a unified diff from a model reply: a ```diff fence if present, else from the first
    `diff --git`/`--- ` marker to the end."""
    if not text:
        return ""
    for block in _FENCE.findall(text):
        if "diff --git" in block or "\n+++ " in block or block.lstrip().startswith(("diff ", "--- ")):
            return block.strip() + "\n"
    for marker in ("diff --git", "\n--- "):
        i = text.find(marker)
        if i != -1:
            return text[i:].strip() + "\n"
    return ""


def resolved(results: dict[str, str], fail_to_pass: list[str], pass_to_pass: list[str]) -> bool:
    """SWE-bench 'resolved': every FAIL_TO_PASS passes AND every PASS_TO_PASS still passes."""
    if not fail_to_pass:
        return False
    return (all(results.get(t) == "passed" for t in fail_to_pass)
            and all(results.get(t) == "passed" for t in pass_to_pass))


# --------------------------------------------------------------------------- #
# setup + run
# --------------------------------------------------------------------------- #
def _setup(sb: RepoSandbox, inst: dict, log: list, mode: str) -> bool:
    """Put the repo at base_commit into /testbed. Returns True on success."""
    if mode == "synthetic":
        for path, content in inst.get("fixtures", {}).items():
            sb.write(path, content)
        for cmd in inst.get("setup_cmds", []):
            sb.exec(cmd)
        return True
    if mode == "prebuilt":                                     # repo already in the image at /testbed
        repo_dir = inst.get("repo_dir", WORK)
        r = sb.exec(f"git -C {repo_dir} checkout -f {shlex.quote(inst['base_commit'])} 2>&1 || true",
                    timeout=120)
        log.append("[prebuilt] " + (r.stdout or "")[-300:])
        return True
    # generic: clone + install (best-effort)
    repo = inst["repo"]
    # /testbed already exists (empty) from sandbox init; clone into it.
    must_pass = [
        f"git clone --quiet https://github.com/{repo}.git {WORK}",
        f"git -C {WORK} checkout -f {shlex.quote(inst['base_commit'])}",
    ]
    # best-effort dependency install: the package + common test-extra conventions + pytest itself.
    # (Generic mode can't know each repo's exact test deps — prebuilt images are the full-coverage path.)
    best_effort = [
        f"cd {WORK} && pip install -q -e . 2>&1 | tail -3 || true",
        f"cd {WORK} && pip install -q -e '.[test]' 2>&1 | tail -2 || true",
        f"cd {WORK} && pip install -q -e '.[tests]' 2>&1 | tail -2 || true",
        f"cd {WORK} && pip install -q -e '.[dev]' 2>&1 | tail -2 || true",
        "pip install -q pytest 2>&1 | tail -2 || true",
        *inst.get("setup_cmds", []),
    ]
    for c in must_pass:
        r = sb.exec(c, timeout=1800, workdir="/")
        log.append(f"$ {c[:80]}\n{(r.stdout or '')[-400:]}{(r.stderr or '')[-400:]}")
        if r.returncode != 0:
            return False                                       # clone/checkout must succeed
    for c in best_effort:
        r = sb.exec(c, timeout=1800)
        log.append(f"$ {c[:80]}\n{(r.stdout or '')[-400:]}{(r.stderr or '')[-400:]}")
    return True


def _apply(sb: RepoSandbox, diff: str, label: str, log: list) -> bool:
    if not diff.strip():
        log.append(f"[{label}] empty patch")
        return False
    sb.write(f"{WORK}/.ps_{label}.diff", diff)
    for cmd in (f"git -C {WORK} apply -v .ps_{label}.diff",
                f"git -C {WORK} apply -v --3way .ps_{label}.diff",
                f"cd {WORK} && patch -p1 < .ps_{label}.diff"):
        r = sb.exec(cmd, timeout=120)
        if r.returncode == 0:
            return True
        log.append(f"[{label}] apply failed: {(r.stderr or r.stdout)[-300:]}")
    return False


def _oracle_patch(sb, inst, client, model, run_cfg, log) -> str:
    """One-shot: show the model the issue + the files the gold patch touches; parse a diff back."""
    files = patched_files(inst.get("patch", ""))
    ctx = []
    for p in files[:8]:
        content = sb.read(f"{WORK}/{p}")
        if content is not None:
            ctx.append(f"### File: {p}\n```\n{content[:8000]}\n```")
    prompt = (inst.get("problem_statement", "") + "\n\n"
              + ("Relevant files:\n\n" + "\n\n".join(ctx) if ctx else "")
              + "\n\nProduce a unified diff (git diff format, paths as a/<file> b/<file>) that "
              "resolves the issue. Output ONLY the diff inside a ```diff code block.")
    res = client.chat(model, [
        {"role": "system", "content": "You are an expert software engineer fixing a bug in a repo."},
        {"role": "user", "content": prompt}],
        temperature=run_cfg.get("temperature", 0.2),
        max_tokens=args_max_tokens(run_cfg), timeout=run_cfg.get("request_timeout", 600))
    if res.error:
        log.append(f"[oracle] model error: {res.error[:200]}")
        return ""
    return extract_diff(res.text or res.reasoning)


def args_max_tokens(run_cfg) -> int:
    return max(run_cfg.get("max_tokens", 6144), 8192)


# --------------------------------------------------------------------------- #
# agent loop (multi-turn tools over the live repo) — replaces the one-shot oracle step
# --------------------------------------------------------------------------- #
AGENT_SYSTEM = (
    "You are an expert software engineer fixing a bug in the Python repository checked out at the "
    "current directory. Workflow: use `grep`/`read_file` to locate the cause, then change the SOURCE "
    "with `edit_file` (a precise find-and-replace — preferred) or `write_file` (only for whole/new "
    "files). Do NOT edit the test suite. Use `run` to inspect or run a quick check. When the fix is "
    "complete, call `done`. Keep edits minimal and targeted.")

AGENT_TOOLS = [
    {"type": "function", "function": {"name": "ls", "description": "List a directory in the repo.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read a file, optionally a line range.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "start": {"type": "integer"}, "end": {"type": "integer"}},
            "required": ["path"]}}},
    {"type": "function", "function": {"name": "grep", "description": "Search the repo (regex); returns file:line matches.",
        "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "edit_file",
        "description": "Replace an exact snippet in a file. `old` must occur verbatim exactly once; "
                       "include enough surrounding context to make it unique. Preferred over write_file.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}},
            "required": ["path", "old", "new"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Overwrite a whole file (or create one). Prefer edit_file for changes.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "run", "description": "Run a shell command in the repo (e.g. to run a test).",
        "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}},
    {"type": "function", "function": {"name": "done", "description": "Signal the fix is complete.",
        "parameters": {"type": "object", "properties": {}}}},
]


def _short(x) -> str:
    s = x if isinstance(x, str) else json.dumps(x)
    return s if len(s) <= 200 else s[:200] + "…"


def _agent_dispatch(sb: RepoSandbox, fn: str, a: dict) -> dict:
    if fn == "ls":
        r = sb.exec(f"ls -la {shlex.quote(a.get('path', '.'))}", timeout=30)
        return {"output": (r.stdout or r.stderr)[:2000]}
    if fn == "read_file":
        content = sb.read(a.get("path", ""))
        if content is None:
            return {"error": f"cannot read {a.get('path')!r}"}
        lines = content.splitlines()
        s, e = a.get("start"), a.get("end")
        if isinstance(s, int) or isinstance(e, int):
            lines = lines[(s or 1) - 1: (e or len(lines))]
        return {"content": "\n".join(lines)[:12000]}
    if fn == "grep":
        r = sb.exec(f"grep -rn -E {shlex.quote(a.get('pattern', ''))} . 2>/dev/null | head -60", timeout=60)
        return {"matches": (r.stdout or "")[:3000] or "(no matches)"}
    if fn == "edit_file":
        path, old, new = a.get("path", ""), a.get("old", ""), a.get("new", "")
        if not old:
            return {"error": "`old` must be the exact non-empty text to replace"}
        content = sb.read(path)
        if content is None:
            return {"error": f"cannot read {path!r}"}
        n = content.count(old)
        if n == 0:
            return {"error": "`old` not found verbatim — read_file and copy the exact text"}
        if n > 1:
            return {"error": f"`old` matches {n} places — add surrounding context to make it unique"}
        wr = sb.write(path, content.replace(old, new, 1))
        return {"ok": wr.returncode == 0, "replaced": 1} if wr.returncode == 0 else {"error": wr.stderr[-300:]}
    if fn == "write_file":
        wr = sb.write(a.get("path", ""), a.get("content", ""))
        return {"ok": wr.returncode == 0} if wr.returncode == 0 else {"error": wr.stderr[-300:]}
    if fn == "run":
        r = sb.exec(a.get("cmd", ""), timeout=180)
        return {"rc": r.returncode, "output": ((r.stdout or "") + (r.stderr or ""))[-2500:]}
    if fn == "done":
        return {"done": True}
    return {"error": f"unknown tool {fn}"}


def _run_agent(sb, inst, client, model, run_cfg, max_turns, log) -> str:
    """Drive the model over the live repo via tools until `done` / no-tool / max_turns. Edits land
    in the working tree; the caller grafts the graded tests on top and scores."""
    msgs = [{"role": "system", "content": AGENT_SYSTEM},
            {"role": "user", "content": (inst.get("problem_statement", "")
             + "\n\nFix the bug in the source, then call done.")}]
    transcript: list[str] = []
    edits = nudges = 0
    turn = 0
    for turn in range(1, max_turns + 1):
        res = client.chat_tools(model, msgs, AGENT_TOOLS,
                                temperature=run_cfg.get("temperature", 0.2),
                                max_tokens=max(run_cfg.get("max_tokens", 4096), 8192),
                                timeout=run_cfg.get("request_timeout", 600))
        if res.get("error"):
            transcript.append(f"[t{turn}] model error: {res['error'][:150]}")
            break
        msg = res["message"]
        tcs = msg.get("tool_calls") or []
        if not tcs:
            # the model replied with prose instead of acting; nudge it back to tools a couple of times
            # (only while it hasn't edited anything) before giving up — don't let chatter end the run.
            if edits == 0 and nudges < 2:
                nudges += 1
                msgs.append(msg)
                msgs.append({"role": "user", "content": "Make the change with edit_file/write_file, "
                             "then call done. Use the tools — don't just describe the fix."})
                transcript.append(f"[t{turn}] no tool call — nudged ({nudges})")
                continue
            transcript.append(f"[t{turn}] no tool call — stop")
            break
        msgs.append(msg)
        stop = False
        for tc in tcs:
            fn = (tc.get("function") or {}).get("name", "")
            raw = (tc.get("function") or {}).get("arguments") or "{}"
            try:
                a = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                a = {}
            out = _agent_dispatch(sb, fn, a)
            if fn in ("edit_file", "write_file") and out.get("ok"):
                edits += 1
            transcript.append(f"[t{turn}] {fn}({_short(a)}) -> {_short(out)}")
            msgs.append({"role": "tool", "tool_call_id": tc.get("id", ""), "name": fn,
                         "content": json.dumps(out)[:3000]})
            if fn == "done":
                stop = True
        if stop:
            break
    log.append(f"agent turns={turn} edits={edits}")
    return f"AGENT TRANSCRIPT (turns={turn}, edits={edits}):\n" + "\n".join(transcript)


def run_repo_patch_task(inst: dict, *, client=None, model="", run_cfg=None, reference=False,
                        agent=False, prebuilt=False, prune=False, max_turns=25, timeout=1800) -> dict:
    """Set up the repo, produce a fix (gold patch if `reference`; an agent loop editing the live repo
    if `agent`; else a one-shot oracle patch), graft the graded test_patch on top, run the target
    tests, and check 'resolved'. Returns a result dict for the runner.

    Environment: `synthetic` (fixtures), `prebuilt` (the instance's per-instance image — full
    fidelity; set `prune` to remove it after, streaming one-at-a-time), or `generic` (clone+install
    in a shared base image — free but best-effort)."""
    run_cfg = run_cfg or {}
    log: list[str] = []
    f2p = list(inst.get("FAIL_TO_PASS") or [])
    p2p = list(inst.get("PASS_TO_PASS") or [])
    if inst.get("fixtures"):
        mode, image, network = "synthetic", GENERIC_IMAGE, True
    elif prebuilt and inst.get("image"):
        mode, image, network = "prebuilt", inst["image"], False
    else:
        mode, image, network = "generic", GENERIC_IMAGE, True
    t0 = time.time()
    try:
        with RepoSandbox(image, network=network, prune=prune) as sb:
            digest = sb.digest()
            if not _setup(sb, inst, log, mode):
                # setup fails before the model acts — an environment problem, never a 0.0 (R10)
                return _fail("repo setup failed", log, image, digest, f2p, t0, unscored=True)

            # Produce the candidate fix (the one swappable step).
            head = ""
            if reference:
                if not _apply(sb, inst.get("patch", ""), "fix", log):
                    return _fail("gold patch did not apply", log, image, digest, f2p, t0)
            elif agent:
                head = _run_agent(sb, inst, client, model, run_cfg, max_turns, log)
                _revert_test_tampering(sb, inst, log)
            else:  # one-shot oracle
                patch = _oracle_patch(sb, inst, client, model, run_cfg, log)
                head = "PATCH:\n" + patch[:2000]
                if not _apply(sb, patch, "fix", log):
                    return _fail("patch did not apply", log, image, digest, f2p, t0, transcript=patch)

            # graft the graded tests on top, then run
            if inst.get("test_patch"):
                _apply(sb, inst["test_patch"], "test", log)
            # Target the test FILES (not every node id): instances with hundreds of PASS_TO_PASS
            # would otherwise blow the command-line length. -rA still prints per-test status, which
            # parse_pytest maps back to the specific f2p/p2p node ids.
            targets = sorted({t.split("::", 1)[0] for t in (f2p + p2p) if "::" in t}) or list(f2p + p2p)
            tgt = " ".join(shlex.quote(t) for t in targets)
            # prebuilt images set up a conda env "testbed" — use its python so the repo's deps resolve.
            py = "python"
            if mode == "prebuilt" and "y" in (sb.exec(
                    "test -x /opt/miniconda3/envs/testbed/bin/python && echo y || true").stdout or ""):
                py = "/opt/miniconda3/envs/testbed/bin/python"
            base = (inst.get("test_cmds") or ["python -m pytest"])[0]
            if base.startswith("pytest"):     # module form so it works without the console script
                base = f"{py} -m {base}"
            elif base.startswith("python "):
                base = py + base[len("python"):]
            cmd = f"{base} -rA -p no:cacheprovider {tgt}" if tgt else f"{base} -rA"
            r = sb.exec(cmd, timeout=timeout)
            results = parse_pytest((r.stdout or "") + "\n" + (r.stderr or ""))
            res_ok = resolved(results, f2p, p2p)
            n_f2p = sum(1 for t in f2p if results.get(t) == "passed")
            log.append(f"$ {cmd[:120]}\n{(r.stdout or '')[-1500:]}\n{(r.stderr or '')[-800:]}")
            # no parseable test results => the suite never ran (collection/dep failure). That is
            # NOT a wrong patch — scoring it 0.0 systematically understates models run without
            # prebuilt images (review R10). `unscored` tells the caller to record a skip, not a row.
            err = None if results else ("no tests ran — generic setup likely missing this repo's test "
                                        "deps; use a prebuilt image (instance `image`)")
            return {
                "resolved": res_ok, "final": 1.0 if res_ok else 0.0, "unscored": not results,
                "passed": n_f2p, "total": len(f2p) or 1, "error": err,
                "transcript": (head + "\n\nLOG:\n" + "\n".join(log))[-8000:],
                "env": {"provider": "docker", "image": image, "image_digest": digest, "setup": mode,
                        "resolved": res_ok, "fail_to_pass_passed": n_f2p, "fail_to_pass_total": len(f2p),
                        "duration_s": round(time.time() - t0, 1)},
            }
    except (subprocess.TimeoutExpired, RuntimeError, OSError) as e:
        return _fail(f"{type(e).__name__}: {e}", log, image, "?", f2p, t0)


# pytest collection/config machinery the agent must not control: editing (or creating) any of
# these can force green without touching a graded test file — skip/xfail via conftest, addopts
# via the .ini/.cfg/.toml files, import-time stubbing via sitecustomize.
_TEST_INFRA = {"conftest.py", "pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml",
               "sitecustomize.py", "usercustomize.py"}


def _revert_test_tampering(sb, inst, log: list) -> None:
    """After the agent loop: revert edits to the graded test files AND any test-infra files, and
    delete infra files the agent CREATED (git checkout can't remove untracked files) — review R9.
    A legitimate fix landing in one of these is essentially unheard of in SWE-bench; when it
    happens the revert under-scores (conservative), never over-scores."""
    for fpath in patched_files(inst.get("test_patch", "")):
        sb.exec(f"git checkout -- {shlex.quote(fpath)} 2>/dev/null || true")
    changed = (sb.exec("git diff --name-only HEAD").stdout or "").splitlines()
    created = (sb.exec("git ls-files --others --exclude-standard").stdout or "").splitlines()
    for f in (x.strip() for x in changed):
        if f and f.rsplit("/", 1)[-1] in _TEST_INFRA:
            log.append(f"reverted test-infra edit: {f}")
            sb.exec(f"git checkout -- {shlex.quote(f)} 2>/dev/null || true")
    for f in (x.strip() for x in created):
        if f and f.rsplit("/", 1)[-1] in _TEST_INFRA:
            log.append(f"removed created test-infra file: {f}")
            sb.exec(f"rm -f {shlex.quote(f)}")


def _fail(msg, log, image, digest, f2p, t0, transcript="", unscored=False) -> dict:
    """A failed task. `unscored=True` marks failures that happened BEFORE the model could act
    (environment problems, not wrong patches) — the caller records a skip instead of a 0.0 row."""
    return {"resolved": False, "final": 0.0, "passed": 0, "total": len(f2p) or 1, "error": msg,
            "unscored": unscored,
            "transcript": (transcript + "\n" + "\n".join(log))[-8000:],
            "env": {"provider": "docker", "image": image, "image_digest": digest,
                    "error": msg, "duration_s": round(time.time() - t0, 1)}}
