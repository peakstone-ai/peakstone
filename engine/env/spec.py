"""Load a goal-state-env challenge from disk.

Layout (challenges/env/<slug>/):
  meta.toml        id/title/difficulty/category/max_turns/timeout, type="goal-state-env"
  env.toml         topology: [[nodes]] with name/start/background/ports/needs/image
  spec.md          the task shown to the agent
  verify.py        deterministic goal-state verifier: verify(env) -> {passed, checks}
  fixtures/<node>/ read-only inputs seeded onto a node (e.g. the file a server must serve)
  reference/<node>/ reference solution files per node (for ref-driven validation)
"""
from __future__ import annotations

import importlib.util
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .base import EnvSpec, NodeSpec


@dataclass
class EnvChallenge:
    id: str
    title: str
    difficulty: int
    category: str
    dir: Path
    spec: str
    env: EnvSpec
    max_turns: int = 12
    verify_path: Path = field(default=None)  # type: ignore[assignment]

    def _per_node(self, sub: str) -> dict[str, dict[str, str]]:
        base = self.dir / sub
        out: dict[str, dict[str, str]] = {}
        if not base.is_dir():
            return out
        for node_dir in base.iterdir():
            if node_dir.is_dir():
                files = {str(f.relative_to(node_dir)): f.read_text()
                         for f in node_dir.rglob("*") if f.is_file()}
                if files:
                    out[node_dir.name] = files
        return out

    def fixtures(self) -> dict[str, dict[str, str]]:
        return self._per_node("fixtures")

    def reference_files(self) -> dict[str, dict[str, str]]:
        return self._per_node("reference")

    def load_verifier(self):
        """Import verify.py and return its verify(env) callable."""
        spec = importlib.util.spec_from_file_location(f"verify_{self.id}", self.verify_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if not hasattr(mod, "verify"):
            raise AttributeError(f"{self.verify_path} has no verify(env) function")
        return mod.verify


def load_env_spec(env_toml: Path, challenge_id: str, timeout: int) -> EnvSpec:
    data = tomllib.loads(env_toml.read_text())
    nodes = [NodeSpec(name=n["name"], start=n.get("start"), background=bool(n.get("background", False)),
                      ports=list(n.get("ports", [])), needs=list(n.get("needs", [])),
                      image=n.get("image"))
             for n in data.get("nodes", [])]
    return EnvSpec(id=challenge_id, nodes=nodes, timeout=timeout)


def load_env_challenge(d: Path) -> EnvChallenge:
    m = tomllib.loads((d / "meta.toml").read_text())
    timeout = int(m.get("timeout", 20))
    return EnvChallenge(
        id=m["id"], title=m.get("title", m["id"]), difficulty=int(m.get("difficulty", 3)),
        category=m.get("category", "multi-machine"), dir=d,
        spec=(d / "spec.md").read_text() if (d / "spec.md").exists() else "",
        env=load_env_spec(d / "env.toml", m["id"], timeout),
        max_turns=int(m.get("max_turns", 12)), verify_path=d / "verify.py",
    )


def load_env_challenges(root: Path) -> list[EnvChallenge]:
    out = []
    for meta in sorted(root.rglob("meta.toml")):
        d = meta.parent
        if any(part[:1] in ("_", ".") for part in d.relative_to(root).parts):
            continue
        if (d / "env.toml").exists() and (d / "verify.py").exists():
            out.append(load_env_challenge(d))
    return out
