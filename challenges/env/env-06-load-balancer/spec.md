# Round-robin load balancer

Five nodes are provisioned on a private, no-internet network. Build a load balancer that spreads
client requests evenly across three backends.

Nodes and the program each one runs:

- **backend0**, **backend1**, **backend2** — identical backends. Create **`server.py`** (launched as
  `python server.py`) on each. A backend listens on the port in `$PORT` and serves HTTP `GET /`:
  - on each request it has handled, it responds with the body `ok`;
  - it records **the total number of requests it has handled so far** in a file `count.txt` in its
    working directory (just the integer, e.g. `3`).

- **router** — create **`router.py`** (launched as `python router.py`). It listens on `$PORT` and
  serves HTTP `GET /`. For each request it receives, it forwards the request to **one backend chosen
  round-robin** (backend0, then backend1, then backend2, then backend0, …) and returns that backend's
  response body to the caller. The backends are reachable at `PEER_BACKEND0_HOST`/`PEER_BACKEND0_PORT`,
  `PEER_BACKEND1_HOST`/`PEER_BACKEND1_PORT`, and `PEER_BACKEND2_HOST`/`PEER_BACKEND2_PORT`.

- **client** — create **`client.py`** (launched as `python client.py`). It sends **exactly 9**
  HTTP `GET /` requests to the router **one at a time** (waiting for each response before sending the
  next), at `PEER_ROUTER_HOST`/`PEER_ROUTER_PORT`. It writes the 9 response bodies to `result.txt`,
  **one per line**.

The task is solved when, after the client finishes:
- `result.txt` on the client has 9 lines, each `ok`;
- each backend's `count.txt` is `3` (the 9 requests were spread evenly, 3 per backend).

Only the Python standard library is available (no internet, no pip). Servers may take a moment to
start — clients/forwarders should retry a connection that is briefly refused.
