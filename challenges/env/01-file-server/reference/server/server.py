"""Reference: serve the working directory over HTTP on $PORT."""
import os
import socketserver
from http.server import SimpleHTTPRequestHandler

PORT = int(os.environ["PORT"])


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass


socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
    httpd.serve_forever()
