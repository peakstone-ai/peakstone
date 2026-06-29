"""Reference router: forward each GET to the next backend, round-robin."""
import os
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ["PORT"])
BACKENDS = [
    f"http://{os.environ[f'PEER_{n}_HOST']}:{os.environ[f'PEER_{n}_PORT']}/"
    for n in ("BACKEND0", "BACKEND1", "BACKEND2")
]
_next = 0


def _forward(url):
    for _ in range(100):  # backends may still be starting
        try:
            return urllib.request.urlopen(url, timeout=5).read()
        except Exception:
            time.sleep(0.1)
    return b""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        global _next
        target = BACKENDS[_next % len(BACKENDS)]
        _next += 1
        body = _forward(target)
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
