"""Reference anti-entropy peer (grow-only set / G-Set CRDT).

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
