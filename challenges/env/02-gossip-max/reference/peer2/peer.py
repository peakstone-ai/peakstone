"""Reference gossip peer: serve our current best-known max, poll peers, converge, write result.txt."""
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ["PORT"])
best = int(open("value.txt").read().strip())


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(str(best).encode())

    def log_message(self, *a):
        pass


threading.Thread(target=lambda: HTTPServer(("0.0.0.0", PORT), Handler).serve_forever(),
                 daemon=True).start()

# discover peers from the PEER_<NAME>_HOST / PEER_<NAME>_PORT environment contract
peers = []
for key, host in os.environ.items():
    if key.startswith("PEER_") and key.endswith("_HOST"):
        name = key[len("PEER_"):-len("_HOST")]
        port = os.environ.get(f"PEER_{name}_PORT")
        if port:
            peers.append(f"http://{host}:{port}/")

# gossip: repeatedly take the max of ourselves and every peer until it settles
for _ in range(40):
    for url in peers:
        try:
            best = max(best, int(urllib.request.urlopen(url, timeout=2).read()))
        except Exception:
            pass
    time.sleep(0.2)

with open("result.txt", "w") as f:
    f.write(str(best))

time.sleep(120)  # keep serving so peers still converging can read our value
