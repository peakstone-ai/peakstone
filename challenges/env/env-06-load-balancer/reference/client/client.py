"""Reference client: send 9 sequential GETs to the router; write each response to result.txt."""
import os
import time
import urllib.request

URL = f"http://{os.environ['PEER_ROUTER_HOST']}:{os.environ['PEER_ROUTER_PORT']}/"
N = 9


def _get():
    for _ in range(100):  # the router may still be starting
        try:
            return urllib.request.urlopen(URL, timeout=5).read().decode()
        except Exception:
            time.sleep(0.1)
    return "ERR"


results = [_get() for _ in range(N)]
with open("result.txt", "w") as f:
    f.write("\n".join(results))
