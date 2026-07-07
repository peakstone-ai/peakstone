"""Run a goal-state-env challenge: seed → launch → verify → (teardown).

The scoring run is deterministic and identical for the reference driver and the agent loop:
materialize the node solution files, start background nodes (servers) and wait for readiness, run
foreground nodes (clients) once, then run the challenge's verifier against the live environment.
"""
from __future__ import annotations

from .base import Environment, EnvSpec
from .capabilities import Requirements, match


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
    net = prov.get("network") or {}
    return {
        "model": model, "challenge": challenge.id, "language": "multi",
        "type": "goal-state-env", "category": challenge.category, "difficulty": challenge.difficulty,
        "scoring": "goal-state", "verification": "goal-state-env",
        # Goal reached = 1.0; otherwise PARTIAL CREDIT — the fraction of goal checks satisfied.
        # Deliberate (review R20 flagged the doc mismatch, not the behavior): it distinguishes
        # "stood the service up but missed replication" from "did nothing". The BINARY thing is
        # the pass verdict (`passed` = every check green), which run_passed_any/prints key off.
        "final_score": 1.0 if result.get("passed") else round(n_pass / total, 4),
        "passed": n_pass, "total": total, "response": transcript, "stdout": "",
        "env": {"provider": prov.get("provider"), "image_digests": prov.get("image_digests", {}),
                "checks": checks, "turns_to_green": turns_to_green, "turns_used": turns_used,
                # network fidelity (real vs simulated conditions) gates how comparable this result is
                "network_fidelity": net.get("fidelity"), "preconditions": net.get("preconditions", []),
                "requirements": net.get("requirements")},
    }


class UnsatisfiableEnv(RuntimeError):
    """The provider cannot supply the network conditions the challenge requires."""


def check_preconditions(env: Environment, req: Requirements) -> list[dict]:
    """Assert the declared network conditions actually hold, so a challenge can't pass under the
    wrong ones (capabilities as verifiable preconditions). Best-effort + deterministic."""
    checks: list[dict] = []
    if req.egress in ("blocked", "allowed") and env.nodes:
        node = next(iter(env.nodes))
        probe = ("python -c \"import socket; socket.setdefaulttimeout(4); "
                 "socket.create_connection(('1.1.1.1', 53))\"")
        reached = env.node(node).run(probe, timeout=8).rc == 0
        want_blocked = req.egress == "blocked"
        ok = (not reached) if want_blocked else reached
        checks.append({"name": f"egress is {req.egress}", "ok": ok,
                       "detail": f"internet {'reachable' if reached else 'unreachable'} from '{node}'"})
    # a firewall-blocked link must actually drop traffic BOTH ways — a half-open partition is a
    # different, easier problem than the one declared, and recovery challenges are gameable
    # through the leaking direction (review R11). Each direction is probed when its target
    # serves a port.
    for l in req.links:
        if l.firewall == "blocked":
            for src, dst in ((l.src, l.dst), (l.dst, l.src)):
                host, port = env.address_of(dst)
                if port is None:
                    continue
                probe = (f"python -c \"import socket; socket.setdefaulttimeout(4); "
                         f"socket.create_connection(('{host}', {port}))\"")
                reached = env.node(src).run(probe, timeout=8).rc == 0
                checks.append({"name": f"link {src}->{dst} blocked", "ok": not reached,
                               "detail": f"{dst}:{port} {'reachable' if reached else 'unreachable'} from '{src}'"})
    return checks


def _network_provenance(env, spec) -> dict:
    req = spec.requirements
    m = match(req, env_provider_caps(env))
    return {"requirements": req.summary(), "fidelity": m.fidelity,
            "satisfied": m.ok, "unmet": m.unmet, "isolation": getattr(env, "provider_name", "?"),
            "applied": env.provenance().get("applied_network", {}),
            "preconditions": check_preconditions(env, req)}


def env_provider_caps(env):
    from .capabilities import PROVIDER_CAPS
    return PROVIDER_CAPS.get(getattr(env, "provider_name", ""), PROVIDER_CAPS["local"])


def run_reference(challenge, provider, *, strict: bool = True) -> dict:
    """Validate a challenge by running its reference solution to goal-state (no LLM).

    `strict` refuses to run if the provider can't supply the required network conditions — a result
    under the wrong conditions would be meaningless (and silently misleading)."""
    spec = challenge.env
    m = match(spec.requirements, provider.capabilities())
    if strict and not m.ok:
        raise UnsatisfiableEnv(
            f"provider {provider.name!r} cannot satisfy {challenge.id}: missing {m.unmet}")
    with provider.provision(spec) as env:
        result = run_once(env, spec, challenge.reference_files(),
                          challenge.load_verifier(), fixtures=challenge.fixtures())
        result["provenance"] = {**env.provenance(), "network": _network_provenance(env, spec)}
        return result
