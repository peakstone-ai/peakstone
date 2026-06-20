# Multi-machine / agentic environments (P3)

Goal-state-env challenges put a model in front of **N isolated, no-internet nodes** and score it on
whether it drives the system into a goal state — "the client got the right bytes", "all peers
converged" — not on a unit-test diff.

## Pieces
- **`base.py`** — the `EnvironmentProvider` / `Environment` / `Node` interface. A node gives the
  agent `write_file` / `read_file` / `run` (with peer discovery via `PORT`, `PEER_<NAME>_HOST/PORT`)
  / `read_logs`.
- **`local.py`** — `LocalProvider`: each node is an isolated workdir + subprocesses on localhost
  ports. Cheap, dependency-free; what the tests use. **Not** a security boundary.
- **`docker.py`** — `DockerComposeProvider`: each node is a container on an `internal: true` network
  (real no-internet isolation), images recorded by digest for reproducibility. Same EnvSpec.
- **`harness.py`** — `run_once` (seed → launch background servers + wait ready → run clients →
  verify) and `run_reference` (validate a challenge with its reference, no LLM).
- **`agent.py`** — the live-LLM run mode: the model iterates write → run → `verify` until green.
- **`spec.py`** — loads a challenge dir into an `EnvChallenge`.

Firecracker-microVM and ssh-to-real-hosts are future providers behind the same interface.

## Authoring a goal-state-env challenge
```
challenges/env/<slug>/
  meta.toml          # type="goal-state-env", difficulty, max_turns, timeout
  env.toml           # [[nodes]] name/start/background/ports/needs/image
  spec.md            # the task shown to the agent
  verify.py          # def verify(env) -> {"passed": bool, "checks": [{name, ok, detail}]}
  fixtures/<node>/   # read-only inputs seeded onto a node
  reference/<node>/  # reference solution files per node (validates the challenge)
```

Validate the reference reaches the goal state on both providers:
```python
from pathlib import Path
from engine.env import load_env_challenge, run_reference, LocalProvider, get_provider
ch = load_env_challenge(Path("challenges/env/01-file-server"))
run_reference(ch, LocalProvider())          # local
run_reference(ch, get_provider("docker"))   # containers, pinned images
```

The verifier is deterministic and ships with the challenge, so goal-state-env runs can reach the
*runner-verified* trust tier. An env result carries provider + image digests + verifier checks +
turns-to-green in the bundle's `result.env`.
