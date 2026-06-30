# Peakstone

**A public, reproducible benchmark platform for the capabilities of open models** — from solving
simple verifiable assignments to (eventually) iterating their way through complex, multi-machine
projects. Community-run, community-authored, independently reproducible.

> *Tsunami "high-water-mark" stones record how far the wave reached. Peakstone records how far the
> open-model capability frontier has reached — permanent, reproducible markers ("set in stone") of a
> moving peak.*

See **[PLAN.md](./PLAN.md)** for the full vision, architecture, and roadmap.

## Status

Early. **P1 (reproducible coding leaderboard)** is in progress. What exists today:

- **`engine/`** — the test harness: serves a model over an OpenAI-compatible API, runs a suite of
  **verifiable** challenges (deterministic tests), scores them, and (soon) emits a signed
  **result bundle**. Also supports LLM-judge grading, self-repair (`--retries`), a global-rules
  output contract (`--agents-md`), tool-calling/agentic/injection modes, and a planner eval. Ships
  the **result-bundle JSON Schema** (the reproducibility contract) + capability taxonomy as packaged
  data in `engine/schema/`, so a bare `pip install` can produce and validate bundles.
- **`challenges/`** — the challenge corpus (`spec.md` + `tests/` + `reference/` per challenge). Part
  of the repo workspace, not the PyPI wheel; running the suite needs a checkout (set `PEAKSTONE_REPO`
  if the package and corpus live apart).
- **`serve/`** — local model-serving helpers (run your own GGUF models to test).
- **`gateway/`** — `peakstone serve`: a standing, **llama-swap-style OpenAI-compatible gateway** on one
  port. It picks (and hot-swaps) the backend `llama-server` from the `model` field of each request, so
  it doubles as a local OpenAI endpoint for everyday use — not just benchmarking. It also owns the
  **benchmark job queue** (sqlite-persisted), so the TUI/CLI are thin clients: runs survive quitting
  the dashboard.

- **`api/`** — the submission/leaderboard API (FastAPI + Postgres) that runs on peakstone.ai. Validates
  signed result bundles, serves faceted leaderboards, and moderates the open challenge corpus.
  Deployed from this repo via Docker (see **Running the server** below); not part of the PyPI client.
- **`web/`** — the Next.js leaderboard frontend.

## Quickstart — run the engine against a local model

```bash
# 0. Sanity-check the suite itself (no model needed): reference solutions must all pass
python -m peakstone.engine.runner --reference --models reference

# 1. Serve a model over an OpenAI-compatible API (any engine works; helper for llama.cpp GGUFs):
./serve/serve.sh <model-name>          # see serve/models.toml for the local registry
# …or run the model gateway, which hot-swaps models per request (see "Model gateway" below):
peakstone serve                        # then add `--gateway http://localhost:12434` to step 2

# 2. Evaluate it
export PATH="$HOME/opt/node/bin:$PATH"   # JS/TS test runners need this Node
python -m peakstone.engine.runner --models <model-name>
python -m peakstone.engine.runner --models <model-name> --retries 2 --agents-md   # self-repair + output contract
```

Scoring: `final = pass_rate` for `tests` challenges; `0.7*pass_rate + 0.3*judge` for `both`.
Each run records full per-challenge transcripts and the model/environment metadata needed to
reproduce it. See `peakstone/engine/runner.py --help` for filters (`--lang`, `--type`, `--difficulty`,
`--ids`) and modes (judge, retries, agents-md, planner eval).

### Offline test sandbox (Linux)

Each test runs **offline**, in a throwaway network namespace (loopback only). This keeps a solution
that does real network I/O — e.g. a BigCodeBench task that `wget`/HTTP/FTPs past the test's mocks —
from hanging to the per-challenge timeout: the call fails fast instead.

It uses unprivileged user namespaces, which **Ubuntu's AppArmor disables by default**. Enable them:

```bash
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0          # this boot
echo 'kernel.apparmor_restrict_unprivileged_userns=0' | sudo tee /etc/sysctl.d/99-peakstone.conf   # persist
# older kernels: kernel.unprivileged_userns_clone=1
```

Without it the harness still works — it just falls back to a plain subprocess (no network isolation),
so a runaway network call can burn the full challenge timeout. Verify it's active:
`unshare -rn -- true` should exit 0. (No-op on macOS, which mocks-or-Docker-isolates instead.)

### Running on macOS (Apple Silicon)

The harness, dashboard, and serving all run on macOS. The engine auto-detects the platform —
hardware stats come from `sysctl`/`ioreg`/`vm_stat` (the dashboard shows the unified-memory GPU
live), and it uses GNU `time` only when present. One-time toolchain setup:

```bash
# Python: engine deps + the optional library-challenge references + the dashboard TUI
pip install jsonschema cryptography pytest numpy pandas pydantic networkx more-itertools \
            python-dateutil sortedcontainers "textual>=0.60"

# JS/TS challenges: install the jsenv libs, plus tsx + typescript on PATH (the TS runner needs them)
( cd peakstone/engine/jsenv && npm install )
npm install -g tsx typescript

# Serving (optional — only to run a model): a Metal build of llama.cpp
brew install llama.cpp        # serve.sh finds `llama-server` on PATH automatically
```

On Apple Silicon, memory is **unified** (weights + KV share system RAM), so pick a model that fits
your RAM with headroom — on a 16 GB Mac, `vibethinker-3b` (3.3 GB) or `phi-4-mini` (~9 GB) rather
than the 22 GB roster tuned for a 24 GB NVIDIA card.

For the multi-machine agentic env challenges, the **local** provider works everywhere, and the
**docker** provider gives full isolation *plus network shaping* (`tc` latency / `iptables` link
partitions) on macOS too — those run inside Docker Desktop's Linux VM, so start Docker Desktop and
use `--env-provider docker`. Only **firecracker** is genuinely Linux-only (it needs `/dev/kvm`,
which Apple Silicon does not provide).

## Dashboard (TUI)

A Textual terminal UI shows your **local GPU/CPU/RAM** live, next to the leaderboard **filtered to
what fits your hardware** — so you can see how models that actually run on your machine compare:

```bash
pip install peakstone[dashboard]            # client only — engine (harness) + dashboard (TUI)
peakstone --api https://peakstone.ai        # or default http://localhost:8000
```

The published package is the **client**: the engine and the dashboard, nothing server-side. The
submission API (`api/`) is the *server* and is deployed from this repo, never installed from PyPI —
see **Running the server** below.

See **[peakstone/dashboard/README.md](./peakstone/dashboard/README.md)**.

## Model gateway (`peakstone serve`)

A standing, **llama-swap-style** OpenAI-compatible gateway on a single port (default `:12434`). The
`model` field of each request selects the backend — the gateway loads/swaps the right `llama-server`
on demand — so it's a drop-in local OpenAI endpoint for editors, scripts, and agents, *and* the
serving layer the benchmark harness runs on.

```bash
peakstone serve                              # foreground; or `peakstone serve --detach`
# point any OpenAI client at it:
curl http://localhost:12434/v1/chat/completions \
  -d '{"model": "<model-name>", "messages": [{"role":"user","content":"hi"}]}'
```

**Browser chat UI.** The gateway also serves a single-file chat app at **`http://localhost:12434/chat`**
(root `/` redirects there). It's a multi-conversation UI with editable system prompts, image input,
streaming + reasoning, and a **model selector** populated live from `GET /v1/models` — picking a model
just puts its name in the request body, so the gateway loads/swaps it into VRAM on demand. Because it's
served from the gateway origin it shares `/v1` (no CORS) and is reachable on the LAN at the gateway's
host:port. On a trusted network, `peakstone serve --host 0.0.0.0 --open` drops auth so any device can
use it tokenlessly; otherwise paste the token into the chat's ⚙ Settings (see auth below).

The gateway also owns the **benchmark job queue** (persisted to `results/jobs.db`), so the TUI/CLI are
thin clients over it — **runs keep going after you quit the dashboard**, and reconnecting shows their
state. Drive it headless with the `jobs` CLI:

```bash
peakstone jobs add <model-name> --level standard   # queue a run on the daemon
peakstone jobs list                                # queued / running / done
peakstone jobs logs <id>                            # stream a job's log
peakstone jobs cancel <id>
```

`peakstone` (the TUI) auto-spawns the gateway detached on startup; disable with `--no-gateway` or
`PEAKSTONE_NO_GATEWAY=1`. Config lives under `[gateway]` in `peakstone/engine/config.toml`
(host/port/`idle_timeout_s` — unload the model and free VRAM after a quiet spell; `0` = never).

**Use it from another machine (auth).** Loopback requests (`127.0.0.1`) need no token, so the TUI, the
CLI, and anything on the box just work. To reach it over a LAN — e.g. an editor on your laptop driving
the GPU box — bind it publicly and present the token; non-loopback requests without a valid one get
`401`:

```bash
peakstone serve --host 0.0.0.0          # prints the token; also saved to ~/.peakstone/gateway_token (0600)
# from the laptop — OpenAI base URL http://<gpu-box>:12434/v1, API key = that token:
curl http://<gpu-box>:12434/v1/chat/completions \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"model": "<model-name>", "messages": [{"role":"user","content":"hi"}]}'
```

The token is generated on first run; override it with `PEAKSTONE_GATEWAY_TOKEN`. On a trusted LAN you
can skip tokens entirely with `peakstone serve --host 0.0.0.0 --open` (auth disabled — any reachable
device can drive the GPU, so use it only at home).

**Sharing one GPU.** Only one model is resident at a time. While a benchmark job runs it *pins* the GPU
to that model: chat requests for the same model are served, but a request for a *different* model gets
`503 busy` rather than evicting the run mid-flight. With no job running, any model loads/swaps on demand.

## Running the server (peakstone.ai)

The leaderboard API + Postgres + automatic-HTTPS proxy run as one Docker stack (`infra/`). On a
Linux box reachable on a public IP:

```bash
git clone https://github.com/peakstone-ai/peakstone && cd peakstone
cp infra/.env.example infra/.env        # set PEAKSTONE_DOMAIN + a strong POSTGRES_PASSWORD
./infra/deploy.sh                        # build, migrate (alembic), start db + api + caddy
```

[Caddy](https://caddyserver.com) provisions and renews the TLS cert for `PEAKSTONE_DOMAIN`
automatically — point its DNS A record at the box and open ports 80 + 443; there's no certbot to
manage. **To update:** `git pull && ./infra/deploy.sh`. Migrations (`alembic upgrade head`) run on
every deploy before the app starts. Postgres is internal-only (not published to the host); only the
proxy is exposed. For a local self-signed smoke test, leave `PEAKSTONE_DOMAIN=localhost` and run
`docker compose -f infra/docker-compose.yml up --build`.

## Add a challenge

Create `challenges/<lang-or-category>/NN-slug/` with `meta.toml`, `spec.md`, `tests/`, and a
`reference/` solution, then verify it passes its own tests:

```bash
python -m peakstone.engine.runner --reference --models reference --ids <id>
```

See **[CONTRIBUTING.md](./CONTRIBUTING.md)** for the challenge schema, the corpus → admin-canonized
suite lifecycle, and the DCO sign-off. Several challenges test **library fluency** with offline-safe
libs (Python: numpy/pandas/pydantic/networkx/...; JS/TS: lodash/date-fns/zod/mathjs in `peakstone/engine/jsenv`).

## License

- **Code & challenges:** Apache-2.0 ([LICENSE](./LICENSE)), via DCO ([CONTRIBUTING.md](./CONTRIBUTING.md)).
- **Submitted result data:** CC-BY-4.0 ([DATA-LICENSE.md](./DATA-LICENSE.md)).
- The **Peakstone** name and "official"/"verified" designations are reserved ([TRADEMARK.md](./TRADEMARK.md)).
