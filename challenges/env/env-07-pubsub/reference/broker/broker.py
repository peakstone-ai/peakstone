"""Reference broker: per-topic ordered message lists over HTTP."""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ["PORT"])
topics: dict[str, list[str]] = {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body=b""):
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_POST(self):
        if urlparse(self.path).path != "/publish":
            return self._send(404)
        n = int(self.headers.get("Content-Length", 0) or 0)
        data = json.loads(self.rfile.read(n) or b"{}")
        topics.setdefault(data["topic"], []).append(data["message"])
        self._send(200)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path != "/messages":
            return self._send(404)
        topic = parse_qs(u.query).get("topic", [""])[0]
        self._send(200, "\n".join(topics.get(topic, [])).encode())


HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
