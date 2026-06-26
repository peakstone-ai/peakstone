# Quorum-replicated key-value store

Three replica nodes (`peer0`, `peer1`, `peer2`) form a key-value store with **N=3, W=2, R=2**
(W+R>N, so a quorum read always observes the latest quorum write). A separate `client` drives it.

Implement the replica program (`peer.go`) and the `client.go` so that:

- A **PUT** to any replica (the coordinator) stores the value and replicates it to a **write quorum
  of W=2** replicas (itself + one peer), then acknowledges. It must NOT assume every replica gets a
  copy.
- A **GET** from any replica performs a **quorum read (R=2)** across replicas and returns the value
  with the highest version — so a replica that did not receive a particular write still returns the
  correct value.
- The client must: PUT `k1=alpha` via `peer0`, PUT `k2=beta` via `peer1`, then GET both `k1` and
  `k2` **from `peer2`**, and write them to `result.txt` as:

  ```
  k1=alpha
  k2=beta
  ```

`peer2` will be the replica left without those keys, so reading them back from `peer2` only succeeds
with a working quorum read. Use only the Go standard library (`net/http`).

Discovery contract: `PORT` (your listen port) and `PEER_<NAME>_HOST` / `PEER_<NAME>_PORT` for peers.
