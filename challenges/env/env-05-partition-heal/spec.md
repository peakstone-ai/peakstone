# Partition recovery

Four peers run a grow-only set (G-Set CRDT). They start **split by a network partition**: `peer0` and
`peer1` (side A) can reach each other but not `peer2`/`peer3`; side B (`peer2`, `peer3`) is symmetric.
Each peer seeds one distinct element (`element.txt`).

Implement `peer.py` so that the peers run **anti-entropy gossip**: each serves its current set and
continuously merges in its reachable peers' sets, writing the sorted, comma-joined set to
`result.txt`. While partitioned, each side will only know its own two elements. **After the partition
heals**, every peer must converge on the union of all four elements.

The merge must be safe to repeat (a set union is idempotent + commutative), and peers must keep
retrying every peer so reconciliation resumes once cross-side links come back.

Discovery: `PORT` (your listen port) and `PEER_<NAME>_HOST` / `PEER_<NAME>_PORT` for each peer.
