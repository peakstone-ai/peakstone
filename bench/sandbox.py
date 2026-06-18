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


_REPO = Path(__file__).resolve().parent.parent


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

    @property
    def pass_rate(self) -> float:
        return (self.passed / self.total) if self.total else 0.0


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _node_env(node_bin: str | None) -> dict:
    env = dict(os.environ)
    if node_bin:
        nb = os.path.expanduser(node_bin)
        env["PATH"] = nb + os.pathsep + env.get("PATH", "")
        # make globally-installed packages (tsx, typescript) resolvable
        gmods = os.path.join(os.path.dirname(nb), "lib", "node_modules")
        if os.path.isdir(gmods):
            env["NODE_PATH"] = gmods + os.pathsep + env.get("NODE_PATH", "")
    return env


def _run(cmd: list[str], cwd: Path, timeout: int, env: dict) -> tuple[int, str, str, float, bool]:
    import time
    t0 = time.time()
    timed_out = False
    try:
        p = subprocess.run(
            cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout
        )
        rc, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        rc, out, err, timed_out = 124, (e.stdout or ""), (e.stderr or "") + "\n[TIMEOUT]", True
        if isinstance(out, bytes):
            out = out.decode(errors="replace")
        if isinstance(err, bytes):
            err = err.decode(errors="replace")
    except FileNotFoundError as e:
        rc, out, err = 127, "", f"command not found: {e}"
    # Keep enough output that per-test pass/fail counts stay accurate: a large suite's
    # `go test -json` / TAP stream can exceed a few KB, and truncating the HEAD would drop
    # early test events and undercount passes. (Stored stdout is re-truncated to ~4KB at the
    # row level, so this larger cap only protects counting, not result.json size.)
    return rc, out[-200_000:], err[-200_000:], round(time.time() - t0, 2), timed_out


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
    nm = os.path.expanduser(cfg.get("js_node_modules") or str(_REPO / "bench" / "jsenv" / "node_modules"))
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
def _run_python(workdir, ch, files, timeout, cfg):
    _write_solution(workdir, files)
    _place_tests(workdir, ch.dir, at_root=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(workdir) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    rc, out, err, dur, _ = _run(
        ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-header"],
        workdir, timeout, env,
    )
    text = out + "\n" + err
    passed = int(_search(r"(\d+) passed", text, 0))
    failed = int(_search(r"(\d+) failed", text, 0)) + int(_search(r"(\d+) error", text, 0))
    total = passed + failed or (0 if rc == 5 else 1)  # rc 5 = no tests collected
    return RunResult(rc == 0 and passed > 0, passed, total, rc, dur, out, err)


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
        # node_modules (bench/jsenv), so default type resolution finds them — no typeRoots.
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

    rc, out, err, dur, _ = _run(cmd, workdir, timeout, env)
    text = out + "\n" + err
    passed = int(_search(r"#\s*pass\s+(\d+)", text, 0))
    failed = int(_search(r"#\s*fail\s+(\d+)", text, 0))
    total = passed + failed or 1
    r = RunResult(rc == 0 and passed > 0, passed, total, rc, dur, out, err)
    r.extra = extra
    return r


def _run_go(workdir, ch, files, timeout, cfg):
    _write_solution(workdir, files)
    _place_tests(workdir, ch.dir, at_root=True)
    if not (workdir / "go.mod").exists():
        (workdir / "go.mod").write_text("module challenge\n\ngo 1.21\n")
    env = dict(os.environ)
    cache = workdir / ".gocache"
    env.update(GOCACHE=str(cache), GOPATH=str(workdir / ".gopath"),
               GOFLAGS="-count=1", GOPROXY="off", GO111MODULE="on")
    rc, out, err, dur, _ = _run(["go", "test", "-json", "./..."], workdir, timeout, env)
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
    return RunResult(rc == 0 and passed > 0, passed, total, rc, dur, out, err)


def _run_rust(workdir, ch, files, timeout, cfg):
    _write_solution(workdir, files)           # solution_file should be src/lib.rs
    _place_tests(workdir, ch.dir, at_root=False)
    (workdir / "Cargo.toml").write_text(
        '[package]\nname = "challenge"\nversion = "0.1.0"\nedition = "2021"\n\n'
        '[lib]\npath = "src/lib.rs"\n'
    )
    env = dict(os.environ)
    env.update(CARGO_HOME=str(workdir / ".cargo"), CARGO_NET_OFFLINE="true")
    # cargo links test binaries via a C compiler; point it at the conda gcc if no `cc`.
    if not shutil.which("cc"):
        linker = shutil.which("x86_64-conda-linux-gnu-gcc") or shutil.which("gcc")
        if linker:
            env["CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER"] = linker
            env["CC"] = linker
    rc, out, err, dur, _ = _run(["cargo", "test", "--offline", "-q"], workdir, timeout, env)
    text = out + "\n" + err
    passed = failed = 0
    for m in re.finditer(r"test result:\s*\w+\.\s*(\d+) passed;\s*(\d+) failed", text):
        passed += int(m.group(1))
        failed += int(m.group(2))
    total = passed + failed or 1
    return RunResult(rc == 0 and passed > 0, passed, total, rc, dur, out, err)


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
            return runner(workdir, challenge, files, challenge.timeout, cfg)
        except Exception as e:  # noqa: BLE001
            return RunResult(False, 0, 1, 1, 0.0, "", f"runner crash: {type(e).__name__}: {e}")
