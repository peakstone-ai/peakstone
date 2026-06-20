# Gossip convergence — global maximum

Three peer nodes (`peer0`, `peer1`, `peer2`) are on a private network, each running the **same**
program `peer.py` (launched as `python peer.py`). There is no coordinator.

- Each peer starts with an integer in `value.txt` in its working directory.
- Each peer listens on the port given by the `PORT` environment variable.
- Each peer is told its two peers' addresses via environment variables
  `PEER_<NAME>_HOST` / `PEER_<NAME>_PORT` (e.g. `PEER_PEER1_HOST`, `PEER_PEER1_PORT`).

Write `peer.py` so that, by exchanging information with its peers, **every** peer determines the
**global maximum** of all three starting values and writes it (as a decimal string) to `result.txt`
in its working directory. The peers must converge even though they start at different times.

Only the Python standard library is available (no internet, no pip). The same `peer.py` runs on all
three nodes.
