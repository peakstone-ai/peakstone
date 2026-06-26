# Leader election + aggregation

Four peers (`peer0`..`peer3`) run on a private network, fully connected — each can reach the other
three. There is **no coordinator**. Every peer starts with:

- `priority.txt` — a unique integer priority,
- `value.txt` — an integer value.

Implement `peer.py` so the peers cooperatively:

1. **Elect a leader** = the peer with the highest priority.
2. **Aggregate**: every non-leader peer hands its value to the leader. The leader computes the
   **sum of all four values** (including its own) once it has heard from everyone, and writes
   `SUM=<total>` to `result.txt`. Each non-leader writes `OK` to `result.txt`.

Discovery contract (environment variables):

- `PORT` — the port your peer must listen on.
- `PEER_<NAME>_HOST` / `PEER_<NAME>_PORT` — address of each other peer (e.g. `PEER_PEER1_HOST`).

No peer knows its own name, so identify the leader by its priority value. The leader must not
finalize until it has collected a value from **every** peer (count them from the discovery vars).
