"""Reference backend: respond `ok` and record how many requests we've handled in count.txt."""
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ["PORT"])
handled = 0


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def do_GET(self):
        global handled
        handled += 1
        with open("count.txt", "w") as f:
            f.write(str(handled))
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
