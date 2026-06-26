#!/usr/bin/env python3
"""Generate env-05-partition-heal (Python p2p): converge after a network partition heals.

Four peers, split into two sides by a firewall: A={peer0,peer1}, B={peer2,peer3}. Each peer seeds a
distinct element and runs an anti-entropy gossip of a grow-only set (a G-Set CRDT). While partitioned
each side can only learn its own two elements; once the verifier HEALS the network, cross-side gossip
must reconcile so all four peers converge on the full set. Requires a provider with a real firewall
(docker/microvm) — LocalProvider can't partition, so this is docker-gated.

Run:  python challenges/env/gen_partition.py
"""
from pathlib import Path

OUT = Path(__file__).resolve().parent / "env-05-partition-heal"
SIDE_A = ["peer0", "peer1"]
SIDE_B = ["peer2", "peer3"]
PEERS = SIDE_A + SIDE_B
ELEMENTS = {"peer0": "alpha", "peer1": "bravo", "peer2": "charlie", "peer3": "delta"}

PEER_PY = r'''"""Reference anti-entropy peer (grow-only set / G-Set CRDT).

Serve our current set; forever, union it with every reachable peer's set and rewrite result.txt.
Set union is idempotent + commutative, so this converges regardless of message order or which links
are up — including AFTER a partition heals, because we keep retrying every peer."""
import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ["PORT"])
known = {open("element.txt").read().strip()}
lock = threading.Lock()

peers = []
for k, host in os.environ.items():
    if k.startswith("PEER_") and k.endswith("_HOST"):
        name = k[len("PEER_"):-len("_HOST")]
        port = os.environ.get(f"PEER_{name}_PORT")
        if port:
            peers.append(f"http://{host}:{port}/")


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        with lock:
            body = json.dumps(sorted(known)).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


threading.Thread(target=lambda: HTTPServer(("0.0.0.0", PORT), H).serve_forever(), daemon=True).start()

# anti-entropy forever: pull each peer's set and merge (cross-side pulls fail while partitioned,
# then succeed once the network heals — the set only grows, so re-merging is safe)
while True:
    for url in peers:
        try:
            remote = set(json.loads(urllib.request.urlopen(url, timeout=2).read()))
            with lock:
                known |= remote
        except Exception:
            pass
    with lock:
        snapshot = ",".join(sorted(known))
    open("result.txt", "w").write(snapshot)
    time.sleep(0.3)
'''

VERIFY_PY = '''"""Goal-state verifier for env-05-partition-heal.

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
'''

META = '''id = "env-05-partition-heal"
title = "Partition recovery (CRDT anti-entropy converges after a heal)"
type = "goal-state-env"
category = "multi-machine"
difficulty = 5
max_turns = 14
timeout = 60
published_at        = "2026-06-30"
published_at_source = "author"
'''

SPEC = '''# Partition recovery

Four peers run a grow-only set (G-Set CRDT). They start **split by a network partition**: `peer0` and
`peer1` (side A) can reach each other but not `peer2`/`peer3`; side B (`peer2`, `peer3`) is symmetric.
Each peer seeds one distinct element (`element.txt`).

Implement `peer.py` so that the peers run **anti-entropy gossip**: each serves its current set and
continuously merges in its reachable peers' sets, writing the sorted, comma-joined set to
`result.txt`. While partitioned, each side will only know its own two elements. **After the partition
heals**, every peer must converge on the union of all four elements.

The merge must be safe to repeat (a set union is idempotent + commutative), and peers must keep
retrying every peer so reconciliation resumes once cross-side links come back.

Discovery: `PORT` (your listen port) and `PEER_<NAME>_HOST` / `PEER_<NAME>_PORT` for each peer.
'''


def main() -> None:
    for name in PEERS:
        fx = OUT / "fixtures" / name
        fx.mkdir(parents=True, exist_ok=True)
        (fx / "element.txt").write_text(ELEMENTS[name] + "\n")
        ref = OUT / "reference" / name
        ref.mkdir(parents=True, exist_ok=True)
        (ref / "peer.py").write_text(PEER_PY)

    nodes = []
    for name in PEERS:
        needs = [p for p in PEERS if p != name]
        nodes.append(
            f'[[nodes]]\nname = "{name}"\nimage = "python:3.12-slim"\nstart = "python peer.py"\n'
            f'background = true\nports = [9000]\nneeds = {needs!r}\n')
    # firewall: block every cross-side pair (each entry blocks both directions)
    links = [f'[[links]]\nfrom = "{a}"\nto = "{b}"\nfirewall = "blocked"\n'
             for a in SIDE_A for b in SIDE_B]
    (OUT / "env.toml").write_text(
        "# Four peers, partitioned A={peer0,peer1} | B={peer2,peer3} by a firewall. The verifier heals\n"
        "# the network at runtime and requires CRDT convergence. Needs docker/microvm (real firewall).\n\n"
        + "\n".join(nodes) + "\n" + "\n".join(links))
    (OUT / "meta.toml").write_text(META)
    (OUT / "spec.md").write_text(SPEC)
    (OUT / "verify.py").write_text(VERIFY_PY)
    print(f"wrote {OUT} — A={SIDE_A} B={SIDE_B}, union={sorted(ELEMENTS.values())}")


if __name__ == "__main__":
    main()
