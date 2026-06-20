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
  output contract (`--agents-md`), tool-calling/agentic/injection modes, and a planner eval.
- **`challenges/`** — the challenge corpus (`spec.md` + `tests/` + `reference/` per challenge).
- **`schema/`** — the **result-bundle JSON Schema** (the reproducibility contract) + capability
  taxonomy.
- **`serve/`** — local model-serving helpers (run your own GGUF models to test).

Not yet built: the submission API, Postgres store, and web leaderboards (P1.3–P1.5 in PLAN.md).

## Quickstart — run the engine against a local model

```bash
# 0. Sanity-check the suite itself (no model needed): reference solutions must all pass
python -m engine.runner --reference --models reference

# 1. Serve a model over an OpenAI-compatible API (any engine works; helper for llama.cpp GGUFs):
./serve/serve.sh <model-name>          # see serve/models.toml for the local registry

# 2. Evaluate it
export PATH="$HOME/opt/node/bin:$PATH"   # JS/TS test runners need this Node
python -m engine.runner --models <model-name>
python -m engine.runner --models <model-name> --retries 2 --agents-md   # self-repair + output contract
```

Scoring: `final = pass_rate` for `tests` challenges; `0.7*pass_rate + 0.3*judge` for `both`.
Each run records full per-challenge transcripts and the model/environment metadata needed to
reproduce it. See `engine/runner.py --help` for filters (`--lang`, `--type`, `--difficulty`,
`--ids`) and modes (judge, retries, agents-md, planner eval).

## Add a challenge

Create `challenges/<lang-or-category>/NN-slug/` with `meta.toml`, `spec.md`, `tests/`, and a
`reference/` solution, then verify it passes its own tests:

```bash
python -m engine.runner --reference --models reference --ids <id>
```

See **[CONTRIBUTING.md](./CONTRIBUTING.md)** for the challenge schema, the corpus → admin-canonized
suite lifecycle, and the DCO sign-off. Several challenges test **library fluency** with offline-safe
libs (Python: numpy/pandas/pydantic/networkx/...; JS/TS: lodash/date-fns/zod/mathjs in `engine/jsenv`).

## License

- **Code & challenges:** Apache-2.0 ([LICENSE](./LICENSE)), via DCO ([CONTRIBUTING.md](./CONTRIBUTING.md)).
- **Submitted result data:** CC-BY-4.0 ([DATA-LICENSE.md](./DATA-LICENSE.md)).
- The **Peakstone** name and "official"/"verified" designations are reserved ([TRADEMARK.md](./TRADEMARK.md)).
