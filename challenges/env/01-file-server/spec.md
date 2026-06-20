# HTTP file server + client

Two nodes are provisioned on a private, no-internet network:

- **server** — must serve files from its working directory over HTTP. It listens on the port given
  in the `PORT` environment variable. The file `data.txt` already exists in its working directory.
- **client** — must fetch `data.txt` from the server and write the **exact bytes** it receives to a
  file named `result.txt` in its own working directory. The server's address is provided as the
  `PEER_SERVER_HOST` and `PEER_SERVER_PORT` environment variables.

Write the program for each node:

- On **server**, create `server.py` (launched as `python server.py`).
- On **client**, create `client.py` (launched as `python client.py`).

The task is solved when the client's `result.txt` contains exactly the bytes of the server's
`data.txt`. Only the Python standard library is available (no internet, no pip).
