"""docker-compose EnvironmentProvider — real isolation + a no-internet private network, images
pinnable by digest. Same interface as the local provider, so an EnvSpec runs unchanged on either.

Each node is a long-lived container (`sleep infinity`) we exec into; nodes reach peers by service
name on an `internal: true` network (no outbound internet). The harness writes files, launches the
node programs, and the verifier reads goal-state — all via `docker compose exec`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .base import Environment, EnvironmentProvider, EnvSpec, Node, NodeSpec, RunResult
from .capabilities import PROVIDER_CAPS, Capabilities

WORK = "/work"


def _compose(project: str, cwd: Path, *args: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", "-p", project, *args],
                          cwd=cwd, capture_output=True, text=True, **kw)


class DockerNode(Node):
    def __init__(self, env: "DockerEnvironment", spec: NodeSpec):
        self.name = spec.name
        self._env = env

    @property
    def host(self) -> str:
        return self.name  # service name is resolvable on the internal network

    def _exec(self, sh: str, *, detach: bool = False, timeout: int = 60, stdin: str | None = None):
        flags = ["-d"] if detach else ["-T"]
        return _compose(self._env.project, self._env.dir, "exec", *flags, self.name,
                        "sh", "-c", sh, input=stdin, timeout=timeout)

    def write_file(self, path: str, content: str) -> dict:
        path = path.lstrip("/")
        r = self._exec(f"mkdir -p {WORK}/$(dirname '{path}') 2>/dev/null; cat > {WORK}/{path}",
                       stdin=content if content is not None else "")
        return {"ok": True, "path": path} if r.returncode == 0 else {"error": r.stderr[-500:]}

    def read_file(self, path: str) -> dict:
        path = path.lstrip("/")
        r = self._exec(f"cat {WORK}/{path}")
        return {"content": r.stdout} if r.returncode == 0 else {"error": f"no such file: {path}"}

    def run(self, cmd: str, *, background: bool = False, timeout: int = 30) -> RunResult:
        if background:
            r = self._exec(f"cd {WORK} && exec {cmd} > {WORK}/.bglog 2>&1", detach=True, timeout=timeout)
            return RunResult(r.returncode, stdout="[started]", stderr=r.stderr)
        try:
            r = self._exec(f"cd {WORK} && {cmd}", timeout=timeout)
            return RunResult(r.returncode, r.stdout[-20000:], r.stderr[-20000:])
        except subprocess.TimeoutExpired:
            return RunResult(124, "", "[TIMEOUT]", timed_out=True)

    def read_logs(self) -> str:
        r = self._exec(f"cat {WORK}/.bglog 2>/dev/null")
        return f"--- {self.name} ---\n{r.stdout[-8000:]}" if r.stdout else ""


class DockerEnvironment(Environment):
    provider_name = "docker"

    def __init__(self, spec: EnvSpec):
        self.spec = spec
        self.dir = Path(tempfile.mkdtemp(prefix=f"psenv-dc-{spec.id}-"))
        self.project = f"psenv{abs(hash(str(self.dir))) % 10**8}"
        self._digests: dict[str, str] = {}
        (self.dir / "docker-compose.yml").write_text(self._compose_yaml(spec))
        up = _compose(self.project, self.dir, "up", "-d", "--remove-orphans", timeout=300)
        if up.returncode != 0:
            self.teardown()
            raise RuntimeError(f"docker compose up failed: {up.stderr[-1000:]}")
        self.nodes: dict[str, Node] = {n.name: DockerNode(self, n) for n in spec.nodes}
        for n in spec.nodes:                # ensure the work dir exists in each container
            self.nodes[n.name].run("true")  # noop exec; mkdir handled lazily by write_file
        self._record_digests(spec)

    def _peer_env(self, n: NodeSpec) -> dict[str, str]:
        env = {}
        if n.ports:
            env["PORT"] = str(n.ports[0])
            env["PORTS"] = ",".join(map(str, n.ports))
        for peer in n.needs:
            pspec = self.spec.node_map.get(peer)
            env[f"PEER_{peer.upper()}_HOST"] = peer
            if pspec and pspec.ports:
                env[f"PEER_{peer.upper()}_PORT"] = str(pspec.ports[0])
        return env

    def _compose_yaml(self, spec: EnvSpec) -> str:
        services = {}
        for n in spec.nodes:
            services[n.name] = {
                "image": n.image or "python:3.12-slim",
                "command": ["sh", "-c", f"mkdir -p {WORK}; exec sleep infinity"],
                "working_dir": WORK,
                "init": True,
                "networks": ["internal"],
                "environment": self._peer_env(n),
            }
        doc = {"name": self.project, "services": services,
               "networks": {"internal": {"internal": True}}}
        return json.dumps(doc)  # compose accepts JSON (a YAML superset)

    def _record_digests(self, spec: EnvSpec):
        for image in {n.image or "python:3.12-slim" for n in spec.nodes}:
            r = subprocess.run(["docker", "image", "inspect", image, "-f", "{{index .RepoDigests 0}}"],
                               capture_output=True, text=True)
            if r.returncode == 0 and r.stdout.strip():
                self._digests[image] = r.stdout.strip()

    def wait_ready(self, name: str, port: int, timeout: float = 10.0) -> bool:
        # connect succeeds → exit 0; refused → the exception makes python exit non-zero
        probe = f"python -c \"import socket; socket.create_connection(('127.0.0.1',{port}),1)\""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            r = self.nodes[name].run(probe, timeout=5)  # type: ignore[attr-defined]
            if r.rc == 0:
                return True
            time.sleep(0.3)
        return False

    def reset(self) -> None:
        # kill node programs from a previous attempt, but NOT the container's keep-alive (sleep)
        for n in self.spec.nodes:
            self.nodes[n.name].run("pkill -9 -f python 2>/dev/null; true")

    def teardown(self) -> None:
        _compose(self.project, self.dir, "down", "-v", "--remove-orphans", timeout=120)
        shutil.rmtree(self.dir, ignore_errors=True)

    def provenance(self) -> dict:
        return {"provider": "docker", "image_digests": self._digests}


class DockerComposeProvider(EnvironmentProvider):
    name = "docker"

    def available(self) -> bool:
        if not shutil.which("docker"):
            return False
        r = subprocess.run(["docker", "compose", "version"], capture_output=True)
        return r.returncode == 0

    def capabilities(self) -> Capabilities:
        return PROVIDER_CAPS["docker"]

    def provision(self, spec: EnvSpec) -> DockerEnvironment:
        return DockerEnvironment(spec)
