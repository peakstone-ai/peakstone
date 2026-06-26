"""Reference peer: elect the highest-priority leader, then collect every value at the leader.

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
