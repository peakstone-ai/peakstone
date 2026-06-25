# Multi-machine / agentic environments (P3)

Goal-state-env challenges put a model in front of **N isolated, no-internet nodes** and score it on
whether it drives the system into a goal state — "the client got the right bytes", "all peers
converged" — not on a unit-test diff.

## Setup / requirements per provider

| Provider | Needs | One-time setup |
|---|---|---|
| **local** | nothing (stdlib) | — |
| **docker** | Docker Engine + Compose v2 | running daemon; user in the `docker` group. Link shaping pulls the `nicolaka/netshoot` sidecar image on first use. |
| **microvm** (Firecracker) | `/dev/kvm` + KVM-capable host | see below |

**Firecracker — host setup**
1. **KVM access:** `sudo usermod -aG kvm $USER` (note `-aG`, append) then re-login. Confirm with
   `python -c "import os; os.close(os.open('/dev/kvm', os.O_RDWR))"`.
2. **Guest artifacts** (firecracker binary + kernel + agent + rootfs), no sudo:
   ```bash
   bash engine/env/firecracker_agent/build-image.sh      # → ~/.peakstone/fc  (PEAKSTONE_FC_HOME)
   ```
   This alone enables **single-node, vsock-only** microVMs (no networking needed).
3. **Multi-node networking** (only for challenges with >1 node), run **once as root**:
   ```bash
   sudo engine/env/firecracker_agent/fc-net-setup.sh     # isolated bridge + user-owned tap pool
   ```
   The taps are persistent + owned by you, so the harness attaches VMs **without `CAP_NET_ADMIN`**.
   The bridge has no uplink → guests have no internet (that's `egress=blocked`). The devices don't
   survive a reboot — the script prints a systemd unit to persist them.

Env overrides: `PEAKSTONE_FC_HOME`, `PEAKSTONE_FC_BIN/KERNEL/ROOTFS`, `PEAKSTONE_FC_MEM_MIB`,
`PEAKSTONE_FC_BRIDGE`, `PEAKSTONE_FC_TAP_PREFIX`, `PEAKSTONE_FC_SUBNET`, `PEAKSTONE_FC_TAP_COUNT`.

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

- **`firecracker.py`** + **`firecracker_agent/`** — `FirecrackerProvider` (microvm). Its headline
  advantage over docker is **isolation** — a real kernel boundary for untrusted agent code — not
  network realism (docker already covers DNS/firewall/NAT/egress).
  - **Milestone 1 (done, verified):** single-node **vsock-only exec**. `provision()` boots a real
    microVM per node (`firecracker --no-api --config-file`) with the Go guest agent
    (`firecracker_agent/main.go`) as PID 1 over vsock — `write_file`/`read_file`/`run`/`read_logs`.
    Needs only `/dev/kvm` + the binary + a kernel/rootfs (no TAP, no `CAP_NET_ADMIN`); boots in ~1s.
  - **Milestone 2:** multi-node **node↔node networking** over an isolated bridge + user-owned tap
    pool (`fc-net-setup.sh`). Each VM gets a static IP; the guest's `eth0` is configured post-boot
    over vsock; peers resolve **by name** via an injected `/etc/hosts` and the `PEER_<NAME>_HOST/PORT`
    contract. No-uplink bridge → `egress=blocked` is real. Firewall (`[[links]] firewall="blocked"`)
    is applied **in-guest** via blackhole routes (no host privilege); link *shaping* (latency/loss)
    routes to docker — the CI guest kernel has no `sch_netem`.
  - **Build the guest artifacts / set up networking:** see the Setup section above.

**ssh-to-real-hosts is intentionally excluded** — real public IPs / DNS / ISP firewalls would give
genuine real-world conditions but destroy reproducibility, which is the platform's whole point.

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
  **real**, link shaping **simulated**), `microvm` (egress/dns/**firewall**/kernel-isolation **real**;
  **no** link shaping — see below).
- **Fidelity** is `real` (e.g. a docker `internal:` network genuinely blocks egress) or `simulated`
  (netem latency). It's recorded in `result.env.network_fidelity` and is meant to gate trust — a
  result under simulated conditions isn't comparable to one under real conditions.
- **Reproducibility policy:** `public_ip` / `real_dns` are in the vocabulary but **no provider offers
  them** → such a challenge is `UnsatisfiableEnv` by design, not silently run under weaker conditions.
- **Application (docker):** a privileged sidecar (`nicolaka/netshoot`) joins each node's netns and
  runs `tc` netem (latency/loss/bandwidth, **multiple shaped destinations per source** via a `prio`
  qdisc + per-dst `u32` filters — see `netshape.py`) and `iptables` (firewall). Node containers stay
  unprivileged and tool-free; rules persist in the netns and are recorded in `provenance.applied_network`.
- **Application (microvm):** conditions apply **in-guest** (each microVM is root in its own kernel —
  no host privilege). Firewall = `ip route` blackhole; **link shaping is not supported** because the
  Firecracker CI guest kernel has no `sch_netem`, so latency/loss challenges route to docker.
- **Preconditions:** capabilities double as checks. `check_preconditions` asserts the declared
  conditions actually hold (egress really blocked, a blocked link really unreachable) before scoring,
  so a challenge can't pass under the wrong network.

```python
from engine.env import select_provider, Requirements, run_reference
select_provider(Requirements(egress="blocked"))      # -> docker (real fidelity)
select_provider(Requirements())                       # -> local
run_reference(ch, LocalProvider())                    # raises UnsatisfiableEnv if local can't satisfy
```

## Running a model against env challenges
```bash
python -m peakstone.engine.runner --env --models <model> [--env-provider auto|local|docker|microvm] [--bundle]
```
The model drives the tool loop until each challenge's verifier passes. `--env-provider auto` (default)
picks the cheapest provider that satisfies each challenge's network requirements. Results are
goal-state-env rows: the API scores them as a separate **`agent_score`** axis (not blended into
coding), and the leaderboard faces on it (`?sort=agent_score`).

## Planner env type
A planner challenge scores *planning*, not coding: the planner model writes an implementation plan,
a **fixed** coder model executes it, and the task's tests verify. The same coder for every planner
isolates the plan's contribution.
```bash
python -m peakstone.engine.runner --planner <planner-model> --coder <coder-model> --bundle
```
Runs over the regular coding challenges; emits `category=planner` rows scored on the **`planner_score`**
axis (`?sort=planner_score` → "Planner leaderboard"). `engine/env/planner.py` exposes
`generate_plan` / `execute_plan` / `run_planner_task` with pluggable clients.

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
