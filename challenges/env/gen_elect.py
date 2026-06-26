#!/usr/bin/env python3
"""Generate env-03-elect-collect (Python p2p): leader election + reliable aggregation.

Four peers, fully connected, no coordinator. Each has a distinct priority and an integer value.
The peers must (1) agree on the leader = highest priority, (2) every follower hands its value to the
leader, (3) the leader sums ALL values and writes SUM=<total>; followers write OK. Harder than
gossip-max: it needs leader determination AND bidirectional collection with termination (the leader
must know it has heard from everyone). No node knows its own name, so identity is by priority.

Run:  python challenges/env/gen_elect.py   (emits per-node files; this script isn't part of the hash)
"""
from pathlib import Path

OUT = Path(__file__).resolve().parent / "env-03-elect-collect"
# distinct priorities -> unambiguous leader (peer1, prio 23); values sum to 100
PEERS = {"peer0": (7, 10), "peer1": (23, 20), "peer2": (15, 30), "peer3": (4, 40)}

PEER_PY = r'''"""Reference peer: elect the highest-priority leader, then collect every value at the leader.

Protocol (no node knows its own name; identity is the priority integer):
  - serve GET / -> our priority; POST / -> a follower handing us {prio, value}
  - learn every peer's priority; the global max priority is the leader
  - if we are the leader: collect values from all N peers (dedup by priority), write SUM=<total>
  - else: POST our value to the leader's address, write OK
"""
import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ["PORT"])
PRIO = int(open("priority.txt").read().strip())
VALUE = int(open("value.txt").read().strip())

# peers: name -> base url, from the PEER_<NAME>_HOST/PORT discovery contract
peers = {}
for k, host in os.environ.items():
    if k.startswith("PEER_") and k.endswith("_HOST"):
        name = k[len("PEER_"):-len("_HOST")]
        port = os.environ.get(f"PEER_{name}_PORT")
        if port:
            peers[name] = f"http://{host}:{port}/"
N = len(peers) + 1                       # total membership = peers + self

values = {PRIO: VALUE}                    # priority -> value, deduped by the unique priority
lock = threading.Lock()


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(str(PRIO).encode())

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        with lock:
            values[int(body["prio"])] = int(body["value"])
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


threading.Thread(target=lambda: HTTPServer(("0.0.0.0", PORT), H).serve_forever(), daemon=True).start()

# discover every peer's priority (retry until all reachable)
peer_prio = {}
while len(peer_prio) < len(peers):
    for name, url in peers.items():
        if name not in peer_prio:
            try:
                peer_prio[name] = int(urllib.request.urlopen(url, timeout=2).read())
            except Exception:
                pass
    time.sleep(0.2)

leader_prio = max(list(peer_prio.values()) + [PRIO])

if PRIO == leader_prio:                   # we are the leader: gather all N values, then total them
    deadline = time.time() + 30
    while time.time() < deadline:
        with lock:
            have = len(values)
        if have >= N:
            break
        time.sleep(0.1)
    with lock:
        total = sum(values.values())
    open("result.txt", "w").write(f"SUM={total}")
else:                                      # follower: hand our value to the leader, then we're done
    leader = next(n for n, p in peer_prio.items() if p == leader_prio)
    payload = json.dumps({"prio": PRIO, "value": VALUE}).encode()
    while True:
        try:
            req = urllib.request.Request(peers[leader], data=payload,
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=2)
            break
        except Exception:
            time.sleep(0.2)
    open("result.txt", "w").write("OK")

time.sleep(120)   # keep serving so the leader can still collect from slow followers
'''

VERIFY_PY = '''"""Goal-state verifier for env-03-elect-collect.

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
'''

META = '''id = "env-03-elect-collect"
title = "Leader election + aggregation (highest-priority peer totals all values)"
type = "goal-state-env"
category = "multi-machine"
difficulty = 5
max_turns = 14
timeout = 40
published_at        = "2026-06-30"
published_at_source = "author"
'''

SPEC = '''# Leader election + aggregation

Four peers (`peer0`..`peer3`) run on a private network, fully connected — each can reach the other
three. There is **no coordinator**. Every peer starts with:

- `priority.txt` — a unique integer priority,
- `value.txt` — an integer value.

Implement `peer.py` so the peers cooperatively:

1. **Elect a leader** = the peer with the highest priority.
2. **Aggregate**: every non-leader peer hands its value to the leader. The leader computes the
   **sum of all four values** (including its own) once it has heard from everyone, and writes
   `SUM=<total>` to `result.txt`. Each non-leader writes `OK` to `result.txt`.

Discovery contract (environment variables):

- `PORT` — the port your peer must listen on.
- `PEER_<NAME>_HOST` / `PEER_<NAME>_PORT` — address of each other peer (e.g. `PEER_PEER1_HOST`).

No peer knows its own name, so identify the leader by its priority value. The leader must not
finalize until it has collected a value from **every** peer (count them from the discovery vars).
'''


def main() -> None:
    for name, (prio, val) in PEERS.items():
        fx = OUT / "fixtures" / name
        fx.mkdir(parents=True, exist_ok=True)
        (fx / "priority.txt").write_text(f"{prio}\n")
        (fx / "value.txt").write_text(f"{val}\n")
        ref = OUT / "reference" / name
        ref.mkdir(parents=True, exist_ok=True)
        (ref / "peer.py").write_text(PEER_PY)

    nodes = []
    for name in PEERS:
        needs = [p for p in PEERS if p != name]
        nodes.append(
            f'[[nodes]]\nname = "{name}"\nimage = "python:3.12-slim"\nstart = "python peer.py"\n'
            f'background = true\nports = [9000]\nneeds = {needs!r}\n')
    (OUT / "env.toml").write_text(
        "# Four peers, fully connected, no coordinator. Elect the highest-priority leader; the leader\n"
        "# sums every peer's value. Discovery via PORT + PEER_<NAME>_HOST/PORT.\n\n"
        + "\n".join(nodes))
    (OUT / "meta.toml").write_text(META)
    (OUT / "spec.md").write_text(SPEC)
    (OUT / "verify.py").write_text(VERIFY_PY)
    print(f"wrote {OUT} — {len(PEERS)} peers, leader=peer1(prio 23), SUM=100")


if __name__ == "__main__":
    main()
