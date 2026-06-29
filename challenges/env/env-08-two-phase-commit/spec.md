# Two-phase commit

Four nodes are provisioned on a private, no-internet network. Implement the two-phase commit (2PC)
protocol so that two transactions, `t1` then `t2`, are decided **atomically** — every participant
reaches the *same* outcome for a transaction, even though they vote independently.

Nodes and the program each one runs:

- **participant0**, **participant1**, **participant2** — identical participants. Create
  **`participant.py`** (launched as `python participant.py`) on each. It listens on `$PORT`. Each
  participant's vote is fixed by a file `votes.txt` in its working directory (already present): two
  lines, the vote (`yes` or `no`) for `t1` then for `t2`. Endpoints (JSON body `{"txn": "<id>"}`):
  - `POST /prepare` — respond `200` with the body `yes` or `no` (this transaction's vote from `votes.txt`).
  - `POST /commit` — record this transaction's outcome as `committed`. Respond `200`.
  - `POST /abort` — record this transaction's outcome as `aborted`. Respond `200`.
  The participant maintains a file `state.txt` listing each decided transaction, one per line as
  `<txn>=<committed|aborted>`, sorted by transaction id (e.g. `t1=committed`).

- **coordinator** — create **`coordinator.py`** (launched as `python coordinator.py`). For each
  transaction `t1` then `t2`, it runs 2PC against all three participants (reachable at
  `PEER_PARTICIPANT0_HOST`/`PEER_PARTICIPANT0_PORT`, …`PARTICIPANT1`…, …`PARTICIPANT2`…):
  1. send `POST /prepare` to every participant and collect the votes;
  2. if **all** voted `yes`, the decision is `commit`; if **any** voted `no`, it is `abort`;
  3. send `POST /commit` (or `POST /abort`) to **every** participant accordingly.
  It records the decisions in a file `decision.txt`, one per line as `<txn>=<commit|abort>`, in order
  (`t1` then `t2`).

The task is solved when:
- the coordinator's `decision.txt` is `t1=commit` then `t2=abort`;
- **every** participant's `state.txt` is `t1=committed` then `t2=aborted` — i.e. all three commit
  `t1` together, and all three abort `t2` together (the single `no` vote forces a global abort).

Only the Python standard library is available (no internet, no pip). Retry connections that are
briefly refused while a peer is starting.
