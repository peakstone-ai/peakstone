"""Goal-state verifier for env-08-two-phase-commit.

The coordinator runs to completion (both transactions) before verification. We require the recorded
decisions AND atomicity: t1 committed on *every* participant; t2 aborted on *every* participant —
including the two that voted yes on t2, which must still abort because one peer voted no.
"""
import time

PARTICIPANTS = ["participant0", "participant1", "participant2"]
EXPECTED_DECISION = {"t1": "commit", "t2": "abort"}


def _parse(env, node, fname):
    c = env.node(node).read_file(fname).get("content") or ""
    out = {}
    for ln in c.splitlines():
        if "=" in ln:
            k, v = ln.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def verify(env):
    dec = {}
    deadline = time.time() + 10
    while time.time() < deadline:
        dec = _parse(env, "coordinator", "decision.txt")
        if dec == EXPECTED_DECISION:
            break
        time.sleep(0.5)
    states = {p: _parse(env, p, "state.txt") for p in PARTICIPANTS}

    dec_ok = dec == EXPECTED_DECISION
    t1_atomic = all(states[p].get("t1") == "committed" for p in PARTICIPANTS)
    t2_atomic = all(states[p].get("t2") == "aborted" for p in PARTICIPANTS)

    return {"passed": dec_ok and t1_atomic and t2_atomic, "checks": [
        {"name": "coordinator decided t1=commit, t2=abort", "ok": dec_ok, "detail": str(dec)},
        {"name": "t1 committed on every participant", "ok": t1_atomic,
         "detail": str({p: states[p].get("t1") for p in PARTICIPANTS})},
        {"name": "t2 aborted on every participant (one no-vote forces global abort)", "ok": t2_atomic,
         "detail": str({p: states[p].get("t2") for p in PARTICIPANTS})},
    ]}
