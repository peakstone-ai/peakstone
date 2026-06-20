"""Multi-machine / agentic environment harness (PLAN.md §9 P3)."""
from .base import Environment, EnvironmentProvider, EnvSpec, Node, NodeSpec, RunResult
from .harness import env_result_row, run_once, run_reference
from .local import LocalProvider
from .spec import EnvChallenge, load_env_challenge, load_env_challenges

__all__ = [
    "Environment", "EnvironmentProvider", "EnvSpec", "Node", "NodeSpec", "RunResult",
    "LocalProvider", "EnvChallenge", "load_env_challenge", "load_env_challenges",
    "run_once", "run_reference", "env_result_row",
]


def get_provider(name: str = "local"):
    """Resolve a provider by name. docker imported lazily (optional dependency)."""
    if name == "local":
        return LocalProvider()
    if name == "docker":
        from .docker import DockerComposeProvider
        return DockerComposeProvider()
    raise ValueError(f"unknown environment provider {name!r}")
