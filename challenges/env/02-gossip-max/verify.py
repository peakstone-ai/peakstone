"""Goal-state verifier for env-02-gossip-max: every peer converged on the global maximum.

Deterministic: reads each peer's seed (value.txt) to compute the expected max, then polls each
peer's result.txt until they all agree (or times out). Gossip is asynchronous, so the verifier
waits for convergence rather than checking once.
"""
import time

PEERS = ["peer0", "peer1", "peer2"]


def verify(env):
    seeds = {n: int((env.node(n).read_file("value.txt").get("content") or "0").strip()) for n in PEERS}
    want = str(max(seeds.values()))
    deadline = time.time() + 25
    got = {}
    while time.time() < deadline:
        got = {n: (env.node(n).read_file("result.txt").get("content") or "").strip() for n in PEERS}
        if all(got[n] == want for n in PEERS):
            return {"passed": True, "checks": [
                {"name": f"{n} converged to {want}", "ok": True, "detail": f"seed {seeds[n]}"}
                for n in PEERS]}
        time.sleep(0.5)
    return {"passed": False, "checks": [
        {"name": f"{n} converged", "ok": got.get(n) == want, "detail": f"{n}={got.get(n)!r} want {want}"}
        for n in PEERS]}
