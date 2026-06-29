# Publish/subscribe broker

Four nodes are provisioned on a private, no-internet network. Build a topic-based pub/sub system.

Nodes and the program each one runs:

- **broker** — create **`broker.py`** (launched as `python broker.py`). Listens on `$PORT` and keeps,
  per topic, the **ordered list** of messages published to it. Endpoints:
  - `POST /publish` with a JSON body `{"topic": "<name>", "message": "<text>"}` — append the message
    to that topic's list. Respond `200`.
  - `GET /messages?topic=<name>` — respond `200` with that topic's messages so far, **one per line**
    in publish order (empty body if the topic has none).

- **publisher** — create **`publisher.py`** (launched as `python publisher.py`). The broker is at
  `PEER_BROKER_HOST`/`PEER_BROKER_PORT`. Publish **exactly this sequence, in this order**:
  | topic | message |
  |-------|---------|
  | `alpha` | `one` |
  | `alpha` | `two` |
  | `alpha` | `three` |
  | `beta`  | `red` |
  | `beta`  | `green` |
  Then exit.

- **subscriber_a**, **subscriber_b** — identical subscribers. Create **`subscriber.py`** (launched as
  `python subscriber.py`) on each. A subscriber reads the topic it follows from a file `topic.txt`
  in its working directory (already present), then keeps its file `received.txt` up to date with that
  topic's messages from the broker — **one per line, in order**. (Poll the broker periodically; the
  publisher may not have sent everything yet.)

The task is solved when each subscriber's `received.txt` contains exactly its topic's messages in
publish order: `subscriber_a` (topic `alpha`) → `one`,`two`,`three`; `subscriber_b` (topic `beta`)
→ `red`,`green`.

Only the Python standard library is available (no internet, no pip). Retry connections that are
briefly refused while a peer is starting.
