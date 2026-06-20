"""Goal-state verifier for env-01-file-server.

Deterministic + self-contained: it inspects the live environment after the harness has launched the
nodes. The goal state is "the client transported the server's exact bytes" — so we compare the
server's source file to what the client actually wrote.
"""


def verify(env):
    expected = env.node("server").read_file("data.txt").get("content")
    got = env.node("client").read_file("result.txt").get("content")
    ok = expected is not None and got == expected
    detail = (f"expected {len(expected or '')} bytes; client wrote {len(got or '')}"
              + ("" if ok else " — mismatch"))
    return {"passed": ok, "checks": [
        {"name": "client received the exact server bytes", "ok": ok, "detail": detail},
    ]}
