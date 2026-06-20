"""EnvironmentProvider abstraction — provision N isolated, no-internet nodes for agentic,
multi-machine challenges (PLAN.md §9 P3).

A goal-state-env challenge ships a topology (env.toml → EnvSpec) and a deterministic verifier. A
provider materializes the topology into live Nodes (write_file / run / read_logs + peer discovery),
the harness launches each node's program and runs the verifier, then the environment is torn down.
The same interface backs a cheap local-process provider (tests/CI) and a docker-compose provider
(real isolation, images pinned by digest). Firecracker microVM + ssh-to-hosts are future impls.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field


@dataclass
class NodeSpec:
    name: str
    start: str | None = None          # command that launches this node's program
    background: bool = False           # long-running (a server) vs one-shot (a client)
    ports: list[int] = field(default_factory=list)   # ports the node's program listens on
    needs: list[str] = field(default_factory=list)   # peers it connects to (→ PEER_* env vars)
    image: str | None = None           # container image (docker provider; ignored by local)


@dataclass
class EnvSpec:
    id: str
    nodes: list[NodeSpec]
    timeout: int = 20                  # per foreground-node run

    @property
    def node_map(self) -> dict[str, NodeSpec]:
        return {n.name: n for n in self.nodes}


@dataclass
class RunResult:
    rc: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.rc == 0 and not self.timed_out


class Node(abc.ABC):
    """A provisioned node: an isolated workspace + the ability to run its program and talk to peers.
    `run` automatically injects PORT (the node's first port) and PEER_<NAME>_HOST/PORT for each peer
    in `needs`, so the agent's code discovers the topology without hardcoding addresses."""
    name: str

    @abc.abstractmethod
    def write_file(self, path: str, content: str) -> dict: ...

    @abc.abstractmethod
    def read_file(self, path: str) -> dict: ...        # {"content": ...} or {"error": ...}

    @abc.abstractmethod
    def run(self, cmd: str, *, background: bool = False, timeout: int = 30) -> RunResult: ...

    @abc.abstractmethod
    def read_logs(self) -> str: ...                    # combined output of background processes

    @property
    @abc.abstractmethod
    def host(self) -> str: ...                         # address peers use to reach this node


class Environment(abc.ABC):
    spec: EnvSpec
    nodes: dict[str, Node]

    def node(self, name: str) -> Node:
        if name not in self.nodes:
            raise KeyError(f"no node {name!r} (have {sorted(self.nodes)})")
        return self.nodes[name]

    @abc.abstractmethod
    def wait_ready(self, name: str, port: int, timeout: float = 10.0) -> bool:
        """Block until `name`'s `port` accepts connections (server readiness)."""

    @abc.abstractmethod
    def reset(self) -> None:
        """Kill background processes so the next launch starts clean (used across agent retries)."""

    @abc.abstractmethod
    def teardown(self) -> None: ...

    def provenance(self) -> dict:
        """Reproducibility metadata for the bundle (provider, image digests, ...)."""
        return {"provider": getattr(self, "provider_name", "unknown")}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.teardown()
        return False


class EnvironmentProvider(abc.ABC):
    name: str

    @abc.abstractmethod
    def available(self) -> bool:
        """Whether this provider can run here (e.g. docker daemon reachable)."""

    @abc.abstractmethod
    def provision(self, spec: EnvSpec) -> Environment: ...
