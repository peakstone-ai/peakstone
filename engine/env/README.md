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

Firecracker-microVM is a future provider behind the same interface (it adds a real kernel boundary
for untrusted agent code). **ssh-to-real-hosts is intentionally excluded** — real public IPs / DNS /
ISP firewalls would give genuine real-world conditions but destroy reproducibility, which is the
platform's whole point.

## Network capabilities (`capabilities.py`)
A challenge declares the network conditions its test is only valid under; a provider advertises what
it can offer, at a fidelity. The matcher picks the cheapest sufficient provider and records the
fidelity in provenance.

```toml
# env.toml — optional network requirements
[network]
egress = "blocked"          # nodes must NOT reach the internet (or "allowed")
dns    = "internal"         # service-name resolution between nodes (or "real" — unsupported, see below)

[[links]]                   # conditions on the edge between two nodes
from = "client"
to   = "server"
latency_ms = 50
loss = 0.01
firewall = "open"           # or "blocked"
nat = true
```

- **Requirements → capability keys** (`required_caps`): `egress_control`, `internal_dns`,
  `link_shaping`, `firewall`, `nat`, `udp`, `public_ip`, `real_dns`, `kernel_isolation`.
- **Provider advertisement** (`PROVIDER_CAPS`): `local` (≈ none), `docker` (egress/dns/firewall/nat
  **real**, link shaping **simulated**), `microvm` (+ `kernel_isolation`, impl deferred).
- **Fidelity** is `real` (e.g. a docker `internal:` network genuinely blocks egress) or `simulated`
  (netem latency). It's recorded in `result.env.network_fidelity` and is meant to gate trust — a
  result under simulated conditions isn't comparable to one under real conditions.
- **Reproducibility policy:** `public_ip` / `real_dns` are in the vocabulary but **no provider offers
  them** → such a challenge is `UnsatisfiableEnv` by design, not silently run under weaker conditions.
- **Application (docker):** the provider *applies* the conditions, it doesn't just advertise them.
  A privileged sidecar (`nicolaka/netshoot`) joins each node's network namespace and runs `tc`
  netem (latency/loss/bandwidth) and `iptables` (firewall) — so node containers stay unprivileged
  and tool-free, and the rules persist in the netns. Applied rules are recorded in
  `provenance.network.applied`.
- **Preconditions:** capabilities double as checks. `check_preconditions` asserts the declared
  conditions actually hold (egress really blocked, a blocked link really unreachable) before scoring,
  so a challenge can't pass under the wrong network.

```python
from engine.env import select_provider, Requirements, run_reference
select_provider(Requirements(egress="blocked"))      # -> docker (real fidelity)
select_provider(Requirements())                       # -> local
run_reference(ch, LocalProvider())                    # raises UnsatisfiableEnv if local can't satisfy
```

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
