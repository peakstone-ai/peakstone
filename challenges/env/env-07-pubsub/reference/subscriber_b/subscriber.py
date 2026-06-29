"""Reference subscriber: continuously mirror our topic's messages into received.txt, in order."""
import os
import time
import urllib.request

with open("topic.txt") as f:
    TOPIC = f.read().strip()
URL = (f"http://{os.environ['PEER_BROKER_HOST']}:{os.environ['PEER_BROKER_PORT']}"
       f"/messages?topic={TOPIC}")

while True:
    try:
        body = urllib.request.urlopen(URL, timeout=5).read().decode()
        with open("received.txt", "w") as f:
            f.write(body)
    except Exception:
        pass
    time.sleep(0.3)
