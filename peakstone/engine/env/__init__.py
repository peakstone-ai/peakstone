"""Multi-machine / agentic environment harness (PLAN.md §9 P3)."""
from .base import Environment, EnvironmentProvider, EnvSpec, Node, NodeSpec, RunResult
from .capabilities import (Capabilities, MatchResult, Requirements, match, required_caps,
                           select_provider, PROVIDER_CAPS)
from .harness import (UnsatisfiableEnv, check_preconditions, env_result_row, run_once, run_reference)
from .local import LocalProvider
from .spec import EnvChallenge, load_env_challenge, load_env_challenges

__all__ = [
    "Environment", "EnvironmentProvider", "EnvSpec", "Node", "NodeSpec", "RunResult",
    "LocalProvider", "EnvChallenge", "load_env_challenge", "load_env_challenges",
    "run_once", "run_reference", "env_result_row", "check_preconditions", "UnsatisfiableEnv",
    "Capabilities", "MatchResult", "Requirements", "match", "required_caps", "select_provider",
    "PROVIDER_CAPS",
]


def get_provider(name: str = "local"):
    """Resolve a provider by name. docker imported lazily (optional dependency)."""
    if name == "local":
        return LocalProvider()
    if name == "docker":
        from .docker import DockerComposeProvider
        return DockerComposeProvider()
    if name in ("microvm", "firecracker"):
        from .firecracker import FirecrackerProvider
        return FirecrackerProvider()
    raise ValueError(f"unknown environment provider {name!r}")
