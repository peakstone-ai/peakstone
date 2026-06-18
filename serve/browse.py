#!/usr/bin/env python3
"""Serve the repo over HTTP for browsing source in a browser, forcing UTF-8.

`python -m http.server` omits `charset=utf-8` on text files (it sends e.g.
`text/x-python` or `application/octet-stream` with no charset), so the browser
falls back to its locale default (Windows-1252) and decodes UTF-8 punctuation
(em dashes, arrows, curly quotes) as mojibake like `â€"`. This handler declares
UTF-8 on every text response, so the bytes render as written.

Usage:  python serve/browse.py [port]      # default 8000, serves the repo root
"""
from __future__ import annotations

import sys
from http.server import SimpleHTTPRequestHandler, test

# Extensions that are plain text but which mimetypes maps to octet-stream (or nothing).
TEXT_EXT = (".toml", ".md", ".sh", ".yaml", ".yml", ".json", ".cfg", ".ini",
            ".txt", ".csv", ".ts", ".go", ".rs", ".js", ".env", ".lock")


class UTF8Handler(SimpleHTTPRequestHandler):
    def guess_type(self, path):
        ctype = super().guess_type(path)
        base = ctype.split(";")[0].strip()
        if base.startswith("text/"):              # keep the type, add the charset
            return f"{base}; charset=utf-8"
        if path.endswith(TEXT_EXT):               # octet-stream -> show as UTF-8 text
            return "text/plain; charset=utf-8"
        return ctype


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    test(UTF8Handler, port=port)
