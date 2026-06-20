"""Run a goal-state-env challenge: seed → launch → verify → (teardown).

The scoring run is deterministic and identical for the reference driver and the agent loop:
materialize the node solution files, start background nodes (servers) and wait for readiness, run
foreground nodes (clients) once, then run the challenge's verifier against the live environment.
"""
from __future__ import annotations

from .base import Environment, EnvSpec


def _normalize(vr) -> dict:
    if not isinstance(vr, dict):
        return {"passed": False, "checks": [{"name": "verifier", "ok": False,
                                             "detail": "verify() did not return a dict"}]}
    checks = vr.get("checks") or []
    passed = bool(vr.get("passed"))
    return {"passed": passed, "checks": checks}


def run_once(env: Environment, spec: EnvSpec, node_files: dict[str, dict[str, str]],
             verify_fn, *, fixtures: dict[str, dict[str, str]] | None = None) -> dict:
    """Seed + launch the current solution, then verify. Resets the env first so retries are clean."""
    env.reset()
    fixtures = fixtures or {}

    # 1) seed read-only fixtures, then the solution files, onto each node
    for ns in spec.nodes:
        node = env.node(ns.name)
        for path, content in fixtures.get(ns.name, {}).items():
            node.write_file(path, content)
        for path, content in node_files.get(ns.name, {}).items():
            node.write_file(path, content)

    launch_errors: list[str] = []
    # 2) background nodes (servers) first, wait until their ports accept connections
    for ns in spec.nodes:
        if ns.start and ns.background:
            env.node(ns.name).run(ns.start, background=True)
            for port in ns.ports:
                if not env.wait_ready(ns.name, port, timeout=10):
                    launch_errors.append(f"{ns.name}:{port} never became ready")

    # 3) foreground nodes (clients) once
    runs: dict[str, dict] = {}
    for ns in spec.nodes:
        if ns.start and not ns.background:
            r = env.node(ns.name).run(ns.start, timeout=spec.timeout)
            runs[ns.name] = {"rc": r.rc, "ok": r.ok, "timed_out": r.timed_out,
                             "output": ((r.stdout or "") + (r.stderr or ""))[-2000:]}

    # 4) goal-state verification
    try:
        vr = _normalize(verify_fn(env))
    except Exception as e:  # noqa: BLE001
        vr = {"passed": False, "checks": [{"name": "verifier crashed", "ok": False,
                                          "detail": f"{type(e).__name__}: {e}"}]}

    logs = {ns.name: env.node(ns.name).read_logs() for ns in spec.nodes if ns.background}
    return {"passed": vr["passed"], "checks": vr["checks"], "runs": runs,
            "launch_errors": launch_errors, "logs": logs}


def env_result_row(challenge, result: dict, *, model: str, turns_to_green=None,
                   turns_used=None, transcript: str = "") -> dict:
    """Shape an env run into a result row for engine.bundle.produce_bundle (verification=goal-state-env)."""
    checks = result.get("checks") or []
    n_pass = sum(1 for c in checks if c.get("ok"))
    total = len(checks) or 1
    prov = result.get("provenance") or {}
    return {
        "model": model, "challenge": challenge.id, "language": "multi",
        "type": "goal-state-env", "category": challenge.category, "difficulty": challenge.difficulty,
        "scoring": "goal-state", "verification": "goal-state-env",
        "final_score": 1.0 if result.get("passed") else round(n_pass / total, 4),
        "passed": n_pass, "total": total, "response": transcript, "stdout": "",
        "env": {"provider": prov.get("provider"), "image_digests": prov.get("image_digests", {}),
                "checks": checks, "turns_to_green": turns_to_green, "turns_used": turns_used},
    }


def run_reference(challenge, provider) -> dict:
    """Validate a challenge by running its reference solution to goal-state (no LLM)."""
    with provider.provision(challenge.env) as env:
        result = run_once(env, challenge.env, challenge.reference_files(),
                          challenge.load_verifier(), fixtures=challenge.fixtures())
        result["provenance"] = env.provenance()
        return result
