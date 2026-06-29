"""Goal-state verifier for env-06-load-balancer.

The client runs to completion (9 sequential requests) before verification, so the goal state is
static: every request returned `ok`, all 9 reached a backend, and the round-robin router spread them
exactly evenly (3 per backend). No polling needed.
"""

BACKENDS = ["backend0", "backend1", "backend2"]
N = 9


def _count(env, name):
    c = (env.node(name).read_file("count.txt").get("content") or "").strip()
    return int(c) if c.isdigit() else 0


def verify(env):
    counts = {b: _count(env, b) for b in BACKENDS}
    total = sum(counts.values())
    result = env.node("client").read_file("result.txt").get("content") or ""
    lines = [ln for ln in result.splitlines() if ln != ""]

    all_ok = len(lines) == N and all(ln == "ok" for ln in lines)
    reached = total == N
    balanced = all(counts[b] == N // len(BACKENDS) for b in BACKENDS)

    return {"passed": all_ok and reached and balanced, "checks": [
        {"name": "client received 9 successful responses", "ok": all_ok,
         "detail": f"{len(lines)} lines; bodies={lines}"},
        {"name": "all 9 requests reached a backend", "ok": reached, "detail": f"total handled={total}"},
        {"name": "requests evenly balanced (3 per backend)", "ok": balanced, "detail": str(counts)},
    ]}
