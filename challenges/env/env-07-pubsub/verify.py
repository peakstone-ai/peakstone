"""Goal-state verifier for env-07-pubsub.

Subscribers run in the background and mirror their topic continuously, so we poll until each one's
received.txt equals the exact ordered messages for its topic (or a deadline passes). Order matters:
a broker that delivers messages out of order fails.
"""
import time

EXPECTED = {"subscriber_a": ["one", "two", "three"], "subscriber_b": ["red", "green"]}


def _lines(env, name):
    c = env.node(name).read_file("received.txt").get("content") or ""
    return [ln for ln in c.splitlines() if ln != ""]


def verify(env):
    got = {}
    deadline = time.time() + 25
    while time.time() < deadline:
        got = {n: _lines(env, n) for n in EXPECTED}
        if all(got[n] == EXPECTED[n] for n in EXPECTED):
            break
        time.sleep(0.5)

    checks = [{"name": f"{n} received its topic's messages in order",
               "ok": got.get(n) == EXPECTED[n],
               "detail": f"got {got.get(n)} want {EXPECTED[n]}"} for n in EXPECTED]
    return {"passed": all(c["ok"] for c in checks), "checks": checks}
