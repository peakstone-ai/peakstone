"""Goal-state verifier for env-05-partition-heal.

Proves partition RECOVERY: (1) while the declared firewall is up, each side converges only within
itself (peer0 has exactly side-A's elements, not the full set); (2) after we HEAL the network, all
four peers converge on the full union. Needs a provider that can heal at runtime (docker/microvm).
"""
import time

SIDE_A = ["peer0", "peer1"]
SIDE_B = ["peer2", "peer3"]
PEERS = SIDE_A + SIDE_B


def _set(env, n):
    return {x for x in (env.node(n).read_file("result.txt").get("content") or "").split(",") if x}


def verify(env):
    elem = {n: (env.node(n).read_file("element.txt").get("content") or "").strip() for n in PEERS}
    full = set(elem.values())
    a_only = {elem[n] for n in SIDE_A}
    b_only = {elem[n] for n in SIDE_B}

    # 1) wait for each side to converge internally while partitioned (proves the split is real)
    partitioned = False
    a_snap = set()
    deadline = time.time() + 12
    while time.time() < deadline:
        a_snap = _set(env, "peer0")
        if a_snap == a_only and _set(env, "peer2") == b_only:
            partitioned = True
            break
        time.sleep(0.5)

    # 2) heal the network; require global convergence to the full union
    env.heal()
    converged = False
    deadline = time.time() + 30
    while time.time() < deadline:
        if all(_set(env, n) == full for n in PEERS):
            converged = True
            break
        time.sleep(0.5)

    return {"passed": partitioned and converged, "checks": [
        {"name": "sides isolated before heal", "ok": partitioned,
         "detail": f"peer0 during partition={sorted(a_snap)} (want {sorted(a_only)})"},
        {"name": "all peers converged after heal", "ok": converged,
         "detail": f"want {sorted(full)}; "
                   + "; ".join(f"{n}={sorted(_set(env, n))}" for n in PEERS)}]}
