"""Reference participant: vote from votes.txt, record commit/abort outcome per transaction."""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

PORT = int(os.environ["PORT"])
TXN_ORDER = ["t1", "t2"]

with open("votes.txt") as f:
    _votes = [ln.strip() for ln in f if ln.strip()]
VOTE = {TXN_ORDER[i]: _votes[i] for i in range(len(TXN_ORDER)) if i < len(_votes)}

state: dict[str, str] = {}


def _write_state():
    with open("state.txt", "w") as f:
        f.write("\n".join(f"{t}={state[t]}" for t in sorted(state)))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _read(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _send(self, code, body=b""):
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_POST(self):
        path = urlparse(self.path).path
        txn = self._read().get("txn", "")
        if path == "/prepare":
            self._send(200, VOTE.get(txn, "no").encode())
        elif path == "/commit":
            state[txn] = "committed"
            _write_state()
            self._send(200)
        elif path == "/abort":
            state[txn] = "aborted"
            _write_state()
            self._send(200)
        else:
            self._send(404)


HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
