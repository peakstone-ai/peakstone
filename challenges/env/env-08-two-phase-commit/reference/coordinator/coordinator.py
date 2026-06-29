"""Reference coordinator: run 2PC for t1 then t2 across all participants; record decisions."""
import json
import os
import time
import urllib.request

PARTICIPANTS = [
    f"http://{os.environ[f'PEER_{n}_HOST']}:{os.environ[f'PEER_{n}_PORT']}"
    for n in ("PARTICIPANT0", "PARTICIPANT1", "PARTICIPANT2")
]
TXNS = ["t1", "t2"]


def post(base, path, txn):
    body = json.dumps({"txn": txn}).encode()
    req = urllib.request.Request(base + path, data=body, headers={"Content-Type": "application/json"})
    for _ in range(100):  # participants may still be starting
        try:
            return urllib.request.urlopen(req, timeout=5).read().decode()
        except Exception:
            time.sleep(0.1)
    return ""


decisions = {}
for txn in TXNS:
    votes = [post(base, "/prepare", txn) for base in PARTICIPANTS]
    decision = "commit" if all(v == "yes" for v in votes) else "abort"
    action = "/commit" if decision == "commit" else "/abort"
    for base in PARTICIPANTS:
        post(base, action, txn)
    decisions[txn] = decision

with open("decision.txt", "w") as f:
    f.write("\n".join(f"{t}={decisions[t]}" for t in TXNS))
