"""Local multi-process EnvironmentProvider — each node is an isolated workdir + subprocesses on
localhost, peers reachable via assigned 127.0.0.1 ports. Cheap and dependency-free (tests/CI run
here). It is NOT a security boundary — use the docker provider for untrusted agent code / real
no-internet isolation. The same EnvSpec runs unchanged on both.
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from .base import Environment, EnvironmentProvider, EnvSpec, Node, NodeSpec, RunResult
from .capabilities import PROVIDER_CAPS, Capabilities

_SECRET_RE = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL", re.I)


def _killpg(p: subprocess.Popen) -> None:
    """SIGKILL the whole process group (node programs spawn children)."""
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except (ProcessLookupError, OSError):
        try:
            p.kill()
        except OSError:
            pass


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class LocalNode(Node):
    def __init__(self, name: str, workdir: Path, env_vars: dict[str, str]):
        self.name = name
        self._dir = workdir
        self._env = env_vars
        self._bg: list[tuple[subprocess.Popen, Path]] = []   # (proc, logfile)

    @property
    def host(self) -> str:
        return "127.0.0.1"

    def _safe(self, path: str) -> Path:
        # proper containment: a string-prefix check would let `../node1-evil/x` pass for node `node1`
        root = self._dir.resolve()
        p = (self._dir / path.lstrip("/")).resolve()
        if p != root and root not in p.parents:
            raise ValueError("path escapes node workdir")
        return p

    def write_file(self, path: str, content: str) -> dict:
        try:
            p = self._safe(path)
        except ValueError as e:
            return {"error": str(e)}
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content if content is not None else "")
        return {"ok": True, "path": path, "bytes": len(content or "")}

    def read_file(self, path: str) -> dict:
        try:
            p = self._safe(path)
        except ValueError as e:
            return {"error": str(e)}
        if not p.is_file():
            return {"error": f"no such file: {path}"}
        return {"content": p.read_text()}

    def _proc_env(self) -> dict:
        # strip harness secrets — node programs are untrusted model output
        env = {k: v for k, v in os.environ.items() if not _SECRET_RE.search(k)}
        env.update(self._env)
        env.pop("http_proxy", None)
        env.pop("https_proxy", None)
        return env

    def run(self, cmd: str, *, background: bool = False, timeout: int = 30) -> RunResult:
        if background:
            log = self._dir / f".log-{len(self._bg)}"
            fh = open(log, "wb")
            p = subprocess.Popen(cmd, cwd=self._dir, env=self._proc_env(), shell=True,
                                 stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
            self._bg.append((p, log))
            return RunResult(0, stdout=f"[started pid {p.pid}]")
        p = subprocess.Popen(cmd, cwd=self._dir, env=self._proc_env(), shell=True,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             start_new_session=True)
        try:
            out, err = p.communicate(timeout=timeout)
            return RunResult(p.returncode, (out or "")[-20000:], (err or "")[-20000:])
        except subprocess.TimeoutExpired:
            _killpg(p)
            return RunResult(124, "", "[TIMEOUT]", timed_out=True)

    def read_logs(self) -> str:
        out = []
        for _, log in self._bg:
            if log.is_file():
                out.append(f"--- {self.name} ---\n{log.read_text()[-8000:]}")
        return "\n".join(out)

    def stop_background(self) -> None:
        for p, _ in self._bg:
            if p.poll() is None:
                _killpg(p)   # kill the whole group, not just the shell (it spawns the server)
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
        self._bg.clear()


class LocalEnvironment(Environment):
    provider_name = "local"

    def __init__(self, spec: EnvSpec):
        self.spec = spec
        self._root = Path(tempfile.mkdtemp(prefix=f"psenv-{spec.id}-"))
        self.nodes: dict[str, Node] = {}
        try:
            # assign a free localhost port per declared node-port
            self._ports: dict[tuple[str, int], int] = {}
            for n in spec.nodes:
                for declared in n.ports:
                    self._ports[(n.name, declared)] = _free_port()
            for n in spec.nodes:
                self.nodes[n.name] = LocalNode(n.name, self._root / n.name, self._node_env(n))
        except BaseException:
            self.teardown()   # don't leak the temp dir on partial construction
            raise

    def _first_port(self, name: str) -> int | None:
        spec = self.spec.node_map[name]
        return self._ports.get((name, spec.ports[0])) if spec.ports else None

    def _node_env(self, n: NodeSpec) -> dict[str, str]:
        env: dict[str, str] = {}
        if n.ports:
            env["PORT"] = str(self._ports[(n.name, n.ports[0])])
            env["PORTS"] = ",".join(str(self._ports[(n.name, p)]) for p in n.ports)
        for peer in n.needs:
            pport = self._first_port(peer)
            env[f"PEER_{peer.upper()}_HOST"] = "127.0.0.1"
            if pport is not None:
                env[f"PEER_{peer.upper()}_PORT"] = str(pport)
        return env

    def address_of(self, name: str) -> tuple[str, int | None]:
        return ("127.0.0.1", self._first_port(name))

    def wait_ready(self, name: str, port: int, timeout: float = 10.0) -> bool:
        actual = self._ports.get((name, port))
        if actual is None:
            return False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", actual), timeout=0.5):
                    return True
            except OSError:
                time.sleep(0.1)
        return False

    def reset(self) -> None:
        for node in self.nodes.values():
            node.stop_background()

    def teardown(self) -> None:
        self.reset()
        shutil.rmtree(self._root, ignore_errors=True)


class LocalProvider(EnvironmentProvider):
    name = "local"

    def available(self) -> bool:
        return True

    def capabilities(self) -> Capabilities:
        return PROVIDER_CAPS["local"]

    def provision(self, spec: EnvSpec) -> LocalEnvironment:
        return LocalEnvironment(spec)
