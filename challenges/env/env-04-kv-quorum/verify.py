"""Goal-state verifier for env-04-kv-quorum.

The client wrote k1 via peer0 and k2 via peer1 (each replicated to only ONE other replica, leaving
peer2 without either key), then read both back from peer2. peer2 can only return them via a quorum
read across its peers — a local-only read would miss them. So a correct result proves quorum reads
work. Deterministic: exact expected content.
"""
import time


def verify(env):
    want = "k1=alpha\nk2=beta"
    got = ""
    deadline = time.time() + 15
    while time.time() < deadline:
        got = (env.node("client").read_file("result.txt").get("content") or "").strip()
        if got == want:
            break
        time.sleep(0.5)
    ok = got == want
    return {"passed": ok, "checks": [
        {"name": "quorum read on a non-replica node returned both writes", "ok": ok,
         "detail": f"client wrote {got!r}; want {want!r}"}]}
