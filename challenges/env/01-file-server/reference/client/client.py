"""Reference: fetch data.txt from the server peer and write the exact bytes to result.txt."""
import os
import urllib.request

host = os.environ["PEER_SERVER_HOST"]
port = os.environ["PEER_SERVER_PORT"]
data = urllib.request.urlopen(f"http://{host}:{port}/data.txt", timeout=10).read()
with open("result.txt", "wb") as f:
    f.write(data)
