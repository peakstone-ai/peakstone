"""Goal-state verifier for env-03-elect-collect.

Deterministic: the leader is the peer with the highest priority (read from fixtures); the expected
total is the sum of all peers' values. Polls until the leader reports SUM=<total> and every follower
reports OK (collection is asynchronous, so we wait for convergence).
"""
import time

PEERS = ["peer0", "peer1", "peer2", "peer3"]


def _int(env, node, path):
    return int((env.node(node).read_file(path).get("content") or "0").strip())


def verify(env):
    prio = {n: _int(env, n, "priority.txt") for n in PEERS}
    total = sum(_int(env, n, "value.txt") for n in PEERS)
    leader = max(PEERS, key=lambda n: (prio[n], n))      # highest priority (tie-break by name)
    want_leader = f"SUM={total}"
    deadline = time.time() + 25
    res = {}
    while time.time() < deadline:
        res = {n: (env.node(n).read_file("result.txt").get("content") or "").strip() for n in PEERS}
        leader_ok = res[leader] == want_leader
        follow_ok = all(res[n] == "OK" for n in PEERS if n != leader)
        if leader_ok and follow_ok:
            break
        time.sleep(0.5)
    checks = [{"name": f"leader {leader} totalled all values", "ok": res.get(leader) == want_leader,
               "detail": f"{leader}={res.get(leader)!r} want {want_leader!r}"}]
    checks += [{"name": f"{n} deferred to the leader", "ok": res.get(n) == "OK",
                "detail": f"{n}={res.get(n)!r}"} for n in PEERS if n != leader]
    return {"passed": all(c["ok"] for c in checks), "checks": checks}
