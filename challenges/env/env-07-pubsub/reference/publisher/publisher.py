"""Reference publisher: publish the fixed sequence to the broker, in order, then exit."""
import json
import os
import time
import urllib.request

BROKER = f"http://{os.environ['PEER_BROKER_HOST']}:{os.environ['PEER_BROKER_PORT']}/publish"
SEQUENCE = [
    ("alpha", "one"), ("alpha", "two"), ("alpha", "three"),
    ("beta", "red"), ("beta", "green"),
]


def publish(topic, message):
    body = json.dumps({"topic": topic, "message": message}).encode()
    req = urllib.request.Request(BROKER, data=body, headers={"Content-Type": "application/json"})
    for _ in range(100):  # broker may still be starting
        try:
            urllib.request.urlopen(req, timeout=5).read()
            return
        except Exception:
            time.sleep(0.1)


for t, m in SEQUENCE:
    publish(t, m)
