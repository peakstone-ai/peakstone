"""Per-language test execution in an isolated temp workdir.

Convention (so challenge authors and the harness agree):
  * Python / JavaScript / TypeScript / Go: the model's solution file and the
    challenge's test files all live at the workdir ROOT (co-located). Tests import
    the solution by its bare name (e.g. `from solution import f`, `import './solution.js'`,
    same Go `package challenge`).
  * Rust: cargo layout — solution at `src/lib.rs`, tests under `tests/` using `challenge::`.

Each run is offline (no network), uses temp caches, and is killed after `timeout` seconds.
Default isolation is plain subprocess; pass sandbox="docker" to wrap in a per-language image.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import metrics as _metrics

_PKG_DIR = Path(__file__).resolve().parent   # the engine package (jsenv/ ships alongside)


def _gnu_time_bin() -> str | None:
    """A `time` binary that supports GNU `-v` (peak-RSS reporting). Linux ships GNU time at
    /usr/bin/time; macOS ships BSD time there, which *rejects* `-v` and aborts the wrapped command
    before it ever runs — so we must not use it. `brew install gnu-time` provides `gtime` (GNU).
    Returns None when no GNU-compatible binary exists, so _run_measured falls back to a plain run
    and simply omits the peak-RSS metric rather than failing every test."""
    for cand in ("/usr/bin/time", "gtime"):
        path = shutil.which(cand)
        if not path:
            continue
        try:
            probe = subprocess.run([path, "-v", "true"], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        if "illegal option" not in (probe.stderr or ""):   # BSD time prints this for -v
            return path
    return None


_TIME_BIN = _gnu_time_bin()


def _net_isolate_prefix() -> list[str]:
    """Argv prefix that runs a command in a fresh network namespace (no external network; loopback
    brought up so 127.0.0.1 tests still work). Enforces the offline test policy: a solution that does
    real I/O — e.g. a BigCodeBench task that wget/HTTP/FTPs past the test's mocks — fails in ~0s
    instead of hanging to the timeout. Empty when unsupported (non-Linux, or user namespaces off)."""
    import sys
    if not shutil.which("unshare"):
        return []
    prefix = ["unshare", "-rn", "--", "sh", "-c", 'ip link set lo up 2>/dev/null; exec "$@"', "_"]
    # Verify the namespace works AND loopback is usable inside it — on a host with userns but no
    # iproute2, `ip link set lo up` silently fails and 127.0.0.1 tests would break, so fall back.
    check = [*prefix, sys.executable, "-c", "import socket; socket.socket().bind(('127.0.0.1', 0))"]
    try:
        if subprocess.run(check, capture_output=True, timeout=10).returncode == 0:
            return prefix
    except (OSError, subprocess.SubprocessError):
        pass
    return []


_NET_ISOLATE = _net_isolate_prefix()

# the isolation mechanism run_tests actually implements. `sandbox="docker"` in config is NOT wired
# into the test runner (only the env providers use real docker), so bundles must record the truth.
SANDBOX_MECHANISM = "subprocess"
_sandbox_warned = False


def effective_sandbox(requested: str | None = None) -> str:
    """The sandbox mechanism that actually ran — never a value the runner only *claims*."""
    global _sandbox_warned
    if requested and requested != SANDBOX_MECHANISM and not _sandbox_warned:
        import sys
        print(f"[sandbox] config requested {requested!r} but only {SANDBOX_MECHANISM!r} is "
              f"implemented; recording the actual mechanism in the bundle", file=sys.stderr)
        _sandbox_warned = True
    return SANDBOX_MECHANISM


@dataclass
class RunResult:
    ok: bool                      # command exited 0 (all tests passed / compiled)
    passed: int
    total: int
    returncode: int
    duration: float
    stdout: str = ""
    stderr: str = ""
    note: str = ""
    extra: dict = field(default_factory=dict)   # e.g. {"typecheck": True}
    metrics: dict = field(default_factory=dict)  # no-LLM efficiency axes (engine/metrics.py)

    @property
    def pass_rate(self) -> float:
        return (self.passed / self.total) if self.total else 0.0


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _node_env(node_bin: str | None) -> dict:
    env = _sanitized_environ()
    if node_bin:
        nb = os.path.expanduser(node_bin)
        env["PATH"] = nb + os.pathsep + env.get("PATH", "")
        # make globally-installed packages (tsx, typescript) resolvable
        gmods = os.path.join(os.path.dirname(nb), "lib", "node_modules")
        if os.path.isdir(gmods):
            env["NODE_PATH"] = gmods + os.pathsep + env.get("NODE_PATH", "")
    return env


# Cap address space per test subprocess so a runaway generated solution (e.g. an unbounded
# allocation or infinite slice growth) fails its OWN test instead of OOM-ing the whole machine.
# A model-written Go solution once made `go test` allocate 44GB and the global OOM-killer took
# down the session. 24 GiB clears the large *virtual* reservations made by WASM/JIT toolchains
# (tsx/esbuild, the Go runtime) while staying well below catastrophe — at 12 GiB the TS runner hit
# "WebAssembly: Cannot allocate Wasm memory". NOTE: RLIMIT_AS limits virtual address space, a blunt
# proxy for physical use; the proper fix (P2 sandbox) is a cgroup memory.max (limits RSS, ignores
# virtual reservations). Override with PEAKSTONE_TEST_MEM_LIMIT_GB.
_MEM_LIMIT_BYTES = int(os.environ.get("PEAKSTONE_TEST_MEM_LIMIT_GB", "24")) * 1024 ** 3


# Largest file a test process may create (a runaway / malicious solution writing an unbounded file
# would otherwise fill the disk). Generous for legit temp output. Override via env.
_FSIZE_LIMIT_BYTES = int(os.environ.get("PEAKSTONE_TEST_FSIZE_LIMIT_GB", "2")) * 1024 ** 3
# Fork-bomb cap. NOTE: RLIMIT_NPROC is per-real-UID (counts ALL the user's processes), so the limit
# is generous; lower it via env on a dedicated runner. Combined with process-group kill on timeout.
_NPROC_LIMIT = int(os.environ.get("PEAKSTONE_TEST_NPROC_LIMIT", "512"))

# Untrusted test code must not inherit harness secrets. Strip anything that looks like a credential
# (HF_TOKEN, *_API_KEY, AWS_SECRET_*, etc.) from the environment handed to the subprocess.
_SECRET_RE = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL", re.I)


def _sanitized_environ() -> dict:
    return {k: v for k, v in os.environ.items() if not _SECRET_RE.search(k)}


def _apply_limits():  # runs in the forked child before exec; inherited by its children
    import resource
    for res, soft_hard in (
        (resource.RLIMIT_AS, (_MEM_LIMIT_BYTES, _MEM_LIMIT_BYTES)),       # address space (memory)
        (resource.RLIMIT_FSIZE, (_FSIZE_LIMIT_BYTES, _FSIZE_LIMIT_BYTES)),  # max file size written
        (resource.RLIMIT_NPROC, (_NPROC_LIMIT, _NPROC_LIMIT)),            # fork-bomb cap
        (resource.RLIMIT_CORE, (0, 0)),                                   # no core dumps
    ):
        try:
            resource.setrlimit(res, soft_hard)
        except (ValueError, OSError):
            pass


def _run(cmd: list[str], cwd: Path, timeout: int, env: dict) -> tuple[int, str, str, float, bool]:
    import signal
    import time
    t0 = time.time()
    timed_out = False
    cmd = [*_NET_ISOLATE, *cmd]   # offline: real network I/O fails fast instead of hanging to timeout
    try:
        # start_new_session puts the child in its own process group so a timeout kills the WHOLE
        # tree (go/cargo/tsx spawn grandchildren that subprocess.run would otherwise orphan).
        p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, preexec_fn=_apply_limits, start_new_session=True)
    except FileNotFoundError as e:
        return 127, "", f"command not found: {e}", round(time.time() - t0, 2), False
    try:
        out, err = p.communicate(timeout=timeout)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        timed_out, rc = True, 124
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except (ProcessLookupError, OSError):
            p.kill()
        try:
            out, err = p.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            out, err = "", ""
        err = (err or "") + "\n[TIMEOUT]"
    # Keep enough output that per-test pass/fail counts stay accurate (a large `go test -json` / TAP
    # stream; stored stdout is re-truncated to ~4KB at the row level).
    return rc, (out or "")[-200_000:], (err or "")[-200_000:], round(time.time() - t0, 2), timed_out


def _run_measured(cmd: list[str], cwd: Path, timeout: int, env: dict):
    """Like _run, but also returns peak RSS (KiB) of the process tree via GNU `/usr/bin/time -v`.
    The report goes to a dot-file so the child's own stdout/stderr (which the runners parse for
    pass/fail) stay clean. Returns (rc, out, err, dur, timed_out, peak_rss_kb|None)."""
    if not _TIME_BIN:
        return (*_run(cmd, cwd, timeout, env), None)
    report = cwd / ".timev"
    rc, out, err, dur, timed_out = _run([_TIME_BIN, "-v", "-o", str(report), *cmd], cwd, timeout, env)
    rss = None
    try:
        if report.exists():
            rss = _metrics.parse_peak_rss_kb(report.read_text())
            report.unlink()
    except OSError:
        pass
    return rc, out, err, dur, timed_out, rss


def _with_rss(r: RunResult, rss_kb: int | None) -> RunResult:
    if rss_kb is not None:
        r.metrics["peak_rss_mb"] = round(rss_kb / 1024, 1)
    return r


def _place_tests(workdir: Path, challenge_dir: Path, at_root: bool) -> None:
    tdir = challenge_dir / "tests"
    if not tdir.is_dir():
        return
    if at_root:
        for f in tdir.rglob("*"):
            if f.is_file():
                dest = workdir / f.relative_to(tdir)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)
    else:
        shutil.copytree(tdir, workdir / "tests")


def _link_node_modules(workdir: Path, cfg: dict) -> str | None:
    """Symlink a shared node_modules into the workdir so ES-module imports of installed
    libraries (lodash, date-fns, zod, ...) resolve (NODE_PATH does not work for ESM)."""
    nm = os.path.expanduser(cfg.get("js_node_modules") or str(_PKG_DIR / "jsenv" / "node_modules"))
    if os.path.isdir(nm):
        link = workdir / "node_modules"
        if not link.exists():
            link.symlink_to(nm)
        return nm
    return None


def _write_solution(workdir: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        dest = workdir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)


# --------------------------------------------------------------------------- #
# per-language runners
# --------------------------------------------------------------------------- #
def _python_for(ch, cfg) -> str:
    """Interpreter that runs this challenge's pytest. Library-heavy suites (e.g.
    BigCodeBench) pin their own versions in a separate env; `[run.envs]` in
    config.toml maps a suite (the directory name under challenges/) to its python.
    Suites with no entry — and stdlib-only ones like HumanEval — use the base
    `python`, preserving prior behaviour."""
    suite = ch.dir.parent.name
    pybin = (cfg.get("envs") or {}).get(suite)
    if pybin:
        pybin = os.path.expanduser(pybin)
        if os.path.exists(pybin):
            return pybin
        import sys
        print(f"[sandbox] [run.envs].{suite} -> {pybin} not found; using base python",
              file=sys.stderr)
    return "python"


def _run_python(workdir, ch, files, timeout, cfg):
    _write_solution(workdir, files)
    _place_tests(workdir, ch.dir, at_root=True)
    env = _sanitized_environ()
    env["PYTHONPATH"] = str(workdir) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pybin = _python_for(ch, cfg)
    if pybin != "python":
        # Suites pinned to their own interpreter also pin their runtime to match how the
        # benchmark was authored (its Docker image runs UTC); this fixes timezone-dependent
        # tasks. Native challenges keep the host's local time.
        env["TZ"] = "UTC"
    rc, out, err, dur, _, rss = _run_measured(
        [pybin, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-header"],
        workdir, timeout, env,
    )
    text = out + "\n" + err
    passed = int(_search(r"(\d+) passed", text, 0))
    failed = int(_search(r"(\d+) failed", text, 0)) + int(_search(r"(\d+) error", text, 0))
    total = passed + failed or (0 if rc == 5 else 1)  # rc 5 = no tests collected
    return _with_rss(RunResult(rc == 0 and passed > 0, passed, total, rc, dur, out, err), rss)


def _run_node(workdir, ch, files, timeout, cfg, ts: bool):
    _write_solution(workdir, files)
    _place_tests(workdir, ch.dir, at_root=True)
    (workdir / "package.json").write_text('{"type":"module","private":true}\n')
    _link_node_modules(workdir, cfg)   # make installed libs importable
    env = _node_env(cfg.get("node_bin"))
    ext = "ts" if ts else "js"
    test_files = sorted(str(p.relative_to(workdir)) for p in workdir.glob(f"*.test.{ext}"))
    if not test_files:
        return RunResult(False, 0, 1, 2, 0.0, "", f"no *.test.{ext} files found")

    extra = {}
    if ts:
        # typecheck gate (recorded, non-fatal to test counting). Point tsc at the global
        # @types/node so node:test / node:assert imports resolve under strict mode.
        # @types/node + @types/lodash + each lib's bundled types all live in the symlinked
        # node_modules (engine/jsenv), so default type resolution finds them — no typeRoots.
        copts = {
            "target": "ES2022", "module": "NodeNext", "moduleResolution": "NodeNext",
            "strict": True, "noEmit": True, "allowImportingTsExtensions": True,
            "skipLibCheck": True, "types": ["node"],
        }
        (workdir / "tsconfig.json").write_text(json.dumps({"compilerOptions": copts}))
        trc, tout, terr, _, _ = _run(["tsc", "--noEmit"], workdir, timeout, env)
        extra["typecheck_ok"] = (trc == 0)
        extra["typecheck_out"] = (tout + terr)[-2000:]
        # tsx CLI registers the TS loader and forwards --test to node's runner
        cmd = ["tsx", "--test", "--test-reporter=tap", *test_files]
    else:
        cmd = ["node", "--test", "--test-reporter=tap", *test_files]

    rc, out, err, dur, _, rss = _run_measured(cmd, workdir, timeout, env)
    text = out + "\n" + err
    passed = int(_search(r"#\s*pass\s+(\d+)", text, 0))
    failed = int(_search(r"#\s*fail\s+(\d+)", text, 0))
    total = passed + failed or 1
    r = RunResult(rc == 0 and passed > 0, passed, total, rc, dur, out, err)
    r.extra = extra
    return _with_rss(r, rss)


def _run_go(workdir, ch, files, timeout, cfg):
    _write_solution(workdir, files)
    _place_tests(workdir, ch.dir, at_root=True)
    if not (workdir / "go.mod").exists():
        (workdir / "go.mod").write_text("module challenge\n\ngo 1.21\n")
    env = _sanitized_environ()
    cache = workdir / ".gocache"
    env.update(GOCACHE=str(cache), GOPATH=str(workdir / ".gopath"),
               GOFLAGS="-count=1", GOPROXY="off", GO111MODULE="on")
    rc, out, err, dur, _, rss = _run_measured(["go", "test", "-json", "./..."], workdir, timeout, env)
    passed = failed = 0
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = ev.get("Test", "")
        if not t or "/" in t:   # count only top-level tests
            continue
        if ev.get("Action") == "pass":
            passed += 1
        elif ev.get("Action") == "fail":
            failed += 1
    total = passed + failed or (1 if rc != 0 else 1)
    return _with_rss(RunResult(rc == 0 and passed > 0, passed, total, rc, dur, out, err), rss)


def _run_rust(workdir, ch, files, timeout, cfg):
    _write_solution(workdir, files)           # solution_file should be src/lib.rs
    _place_tests(workdir, ch.dir, at_root=False)
    (workdir / "Cargo.toml").write_text(
        '[package]\nname = "challenge"\nversion = "0.1.0"\nedition = "2021"\n\n'
        '[lib]\npath = "src/lib.rs"\n'
    )
    env = _sanitized_environ()
    env.update(CARGO_HOME=str(workdir / ".cargo"), CARGO_NET_OFFLINE="true")
    # cargo links test binaries via a C compiler; point it at the conda gcc if no `cc`.
    if not shutil.which("cc"):
        linker = shutil.which("x86_64-conda-linux-gnu-gcc") or shutil.which("gcc")
        if linker:
            env["CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER"] = linker
            env["CC"] = linker
    rc, out, err, dur, _, rss = _run_measured(["cargo", "test", "--offline", "-q"], workdir, timeout, env)
    text = out + "\n" + err
    passed = failed = 0
    for m in re.finditer(r"test result:\s*\w+\.\s*(\d+) passed;\s*(\d+) failed", text):
        passed += int(m.group(1))
        failed += int(m.group(2))
    total = passed + failed or 1
    return _with_rss(RunResult(rc == 0 and passed > 0, passed, total, rc, dur, out, err), rss)


_RUNNERS = {
    "python": _run_python,
    "javascript": lambda *a: _run_node(*a, ts=False),
    "typescript": lambda *a: _run_node(*a, ts=True),
    "go": _run_go,
    "rust": _run_rust,
}


def _search(pat: str, text: str, default):
    m = re.search(pat, text)
    return m.group(1) if m else default


def run_tests(challenge, files: dict[str, str], cfg: dict) -> RunResult:
    """Create a temp workdir, install solution + tests, run the language's test suite."""
    runner = _RUNNERS.get(challenge.language)
    if runner is None:
        return RunResult(False, 0, 1, 2, 0.0, "", f"no runner for {challenge.language}")
    if not files:
        return RunResult(False, 0, 1, 2, 0.0, "", "no code extracted from response")
    with tempfile.TemporaryDirectory(prefix=f"llmlab-{challenge.id}-") as tmp:
        workdir = Path(tmp)
        try:
            result = runner(workdir, challenge, files, challenge.timeout, cfg)
        except Exception as e:  # noqa: BLE001
            return RunResult(False, 0, 1, 1, 0.0, "", f"runner crash: {type(e).__name__}: {e}")
        # efficiency axes: source size (static) + test-suite wall time (peak RSS set by the runner)
        result.metrics.update(_metrics.collect_static(files))
        result.metrics["test_wall_s"] = result.duration
        return result
