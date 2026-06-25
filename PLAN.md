# PLAN.md — Peakstone

> **Peakstone** (peakstone.ai) — a public, reproducible benchmark *platform* that tracks the
> evolution of open models' real capabilities — from solving simple verifiable assignments to
> (eventually) one-shotting complex multi-machine projects via iteration. Community-run, community-
> authored, independently reproducible.
>
> The name: tsunami "high-water-mark" stones record how far the wave reached; Peakstone records how
> far the capability *frontier* has reached — permanent, reproducible markers ("set in stone") of a
> moving peak.

## 1. Context & vision

We already have a solid local harness (`bench/`): it serves GGUF models via llama.cpp, runs a
progressive suite of **verifiable** coding challenges (deterministic tests), and can additionally
grade solutions with an LLM judge. It measures coding-correctness, library fluency, self-repair
(`--retries`), instruction adherence, tool-calling, prompt-injection resistance, and an early
plan→code→test "planner" mode.

The pivot: turn that harness into a **website + platform** where:
- anyone runs the open CLI against their own models and **publishes scores** per capability category;
- results are **independently reproducible** (every submission embeds everything needed to re-run it);
- users **author new challenges** to probe where models differ;
- the headline view is **capability-vs-time** — watching open models climb from simple assignments
  to complex, iterated, multi-component projects.

Future capability tiers (architected for, not built day one): tool-calling + recursion/iteration,
**multi-machine projects** (server/client, p2p) via an SSH-to-machine or microVM-on-VLAN
environment, and later vision-to-UI / game-playing for multimodal models.

## 2. Decisions (locked 2026-06-20)

| Decision | Choice | Why |
|---|---|---|
| Execution & trust | **Decentralized submit + verified tier** | Models run on users' GPUs; the site never needs compute. Trust via full repro metadata + a "verified" badge (consensus or trusted re-run). |
| Database | **PostgreSQL + JSONB** | Leaderboards = aggregation/joins/time-series across model×category×difficulty×date (Postgres' strength); JSONB keeps per-test payloads & env metadata open-schema. |
| First milestone | **Reproducible coding leaderboard** | Ship the credible core (existing verifiable suite) first; everything extends it. |
| Stack | **FastAPI + Next.js + Postgres** | Python backend reuses the harness AS the engine (no rewrite); React/Next for charts. |

## 3. Core principle — reproducibility is the schema

You can't host every GPU, so the platform's integrity rests on the **result bundle**: a signed,
self-contained artifact a submitter produces locally and uploads. Deterministic (test-based)
challenges are then *independently re-runnable*; judge-based ones store the judge's identity and are
flagged "soft". The bundle is the contract between `/engine` and `/api` and lives in `/schema`.

### Result-bundle schema (v1 sketch, JSON)
```jsonc
{
  "bundle_version": "1.0",
  "submitted_at": "2026-06-20T10:00:00Z",
  "submitter": { "handle": "psch", "pubkey": "...", "signature": "<sig over bundle hash>" },
  "harness":   { "name": "openagentbench-engine", "version": "0.1.0", "git_commit": "..." },
  "model": {
    "family": "Qwen3-Coder-Next",          // for grouping in evolution charts
    "artifact": "UD-Q4_K_XL",               // the specific quant/file identity
    "hf_repo": "unsloth/Qwen3-Coder-Next-GGUF",
    "hf_revision": "<commit sha>",          // EXACT weights version
    "file_sha256": "<sha256 of gguf>",
    "params_total": "80B", "params_active": "3B", "release_date": "2026-02-19",
    "engine": { "name": "llama.cpp", "version": "b1-ef8268f", "build_flags": "-DGGML_CUDA=ON ..." },
    "sampling": { "temperature": 0.2, "top_p": 0.8, "top_k": 20, "seed": 1234 },
    "context": 262144,
    "serve_flags": "-ngl 99 -fit off --n-cpu-moe 34 --parallel 1 -fa on"
  },
  "environment": { "gpu": "RTX 4090", "vram_gb": 24, "driver": "595.71.05",
                   "cpu": "Ryzen 9 9950X", "ram_gb": 64, "os": "Ubuntu 24.04", "offload": "n-cpu-moe 34" },
  "suite": { "id": "core-coding", "version": "2026.06", "content_hash": "<sha256 of suite>" },
  "results": [
    {
      "challenge_id": "py-12-txn-kvstore", "challenge_hash": "<sha256>",
      "category": "architecture", "verification": "deterministic-tests", "difficulty": 5,
      "capabilities": ["code-correctness"],
      "score": { "final": 1.0, "passed": 12, "total": 12 },
      "attempts": 1, "passed_on_attempt": 1, "tok_per_s": 59, "latency_s": 12.1,
      "transcript": { "prompt": "...", "raw_output": "...", "extracted_files": {"solution.py": "..."},
                      "stdout": "...", "stderr": "" },
      "judge": null
    }
  ],
  "aggregate": { "overall": 0.41, "by_category": { "architecture": 0.93, "...": 0.0 } }
}
```
The whole bundle is content-addressed (`bundle_hash = sha256(canonical_json)`); the submitter signs
that hash. Transcripts may be stored inline (small) or as content-addressed blobs (large suites).

## 4. Capability taxonomy

Three orthogonal axes so the model extends to every future test type without schema churn:

1. **Capability category** (what's tested): `code-correctness`, `library-fluency`, `self-repair`,
   `tool-calling`, `multi-step-agentic`, `planning`, `distributed/multi-machine`,
   `instruction-following`, `safety` (injection/refusal/secure-code), `vision-to-code`, `game-playing`.
2. **Verification method** (how it's scored → drives trust): `deterministic-tests` |
   `llm-judge` | `goal-state-env` | `human`.
3. **Difficulty tier**: 1–5.

A challenge *declares* the capabilities it requires (e.g. `tool-calling`, `multi-turn`,
`networked-env`, `vision`). A model's per-category score is aggregated over the challenges it
attempted in that category. The website's hero view = **per-category score vs. model release date**.
The current `meta.toml` fields map directly: `category/type → capability category`,
`scoring → verification method`, `difficulty → seed tier` (calibrated below).

> **Category is *what* skill; difficulty is *which models pass*.** These are orthogonal. The simple
> categories are stable (models just saturate them); the evolution happens along the difficulty axis.

### 4a. Calibrated difficulty tiers (data-driven, not author-assigned)
Authors give a **seed difficulty** at creation, but the canonical difficulty is **computed from
submissions** — *what fraction of the model population passes it* — NOT raw parameter count
(capability ≠ params: a strong 9B beats a weak 30B, MoE active≠total, quant & training-era dominate).
We *show* the param/release-date correlation as a derived view, but bucket by demonstrated capability:

| Tier | Name | Discriminates | Example (2026) |
|---|---|---|---|
| **T0** | Saturated / floor | ~everything, incl. old/small | fizzbuzz, palindrome |
| **T1** | Foundational | competent small (good ~7–9B) | csv group-by, binary search-insert |
| **T2** | Proficient | strong mid (~30B-class / good MoE) | LRU+TTL cache, zod/pydantic validation |
| **T3** | Advanced | current frontier open models | architecture set (txn-KV, mini-SQL, scheduler) |
| **T4** | Frontier / unsolved | nothing reliably passes yet | the live edge — where authors aim |

Challenges **migrate down tiers over time** (T4→…→T0) as models improve — *that migration IS the
evolution story*. Each challenge also exposes a derived stat **"smallest/oldest model that passes"**
(the 10B/30B/80B intuition, as evidence). The corpus deliberately keeps **all** tiers including T0 —
the trivial challenges are what discriminate *old/pre-coding-agent* models and anchor the floor of
the evolution chart. (The 14 we pruned *locally* were pruned only for run-time; they belong in the
platform corpus tagged T0.)

### 4b. Challenge lifecycle & suite governance
The **corpus** (every published challenge) is open; the **suite** (what counts officially) is curated.

```
author writes  ──►  submitted  ──►  review (admin + community: reference must pass in sandbox,
                                     resource limits, dedupe)  ──►  published-to-CORPUS (runnable,
                                     uncanonized)  ──►  admin CANONIZES into a versioned SUITE
```
- **Corpus** = all `published` challenges (any tier, any author). Anyone may run any subset to probe
  models — useful for discovering where models differ before a challenge is official.
- **Suite** = a named, **versioned**, admin-blessed selection (e.g. `official-coding-2026.06`).
  **Official leaderboards & evolution charts are per-suite**, so a score always carries the exact
  suite version it was measured on (this is what keeps "models improving over time" from being
  confounded by the benchmark itself changing). Community/unofficial suites are allowed and labelled.
- New challenges accrete mostly at the **T3/T4 frontier**; as the frontier saturates, admins cut a
  new suite version that adds the harder challenges (older versions stay queryable for back-compat).

## 5. Trust / verification tiers
- **self-reported** — any valid signed bundle. Shown, but visibly unverified.
- **community-verified** — a *deterministic* challenge result reproduced by ≥N independent
  submitters within tolerance (exact for pass/total; small band for tok/s). Auto-promoted.
- **runner-verified** — re-run by a trusted runner (a maintainer or CI box) for spot-checks /
  flagged models. Highest badge.
Judge-based and goal-state results stay "soft" (judge identity/version recorded; not auto-verifiable).

## 6. Data model (Postgres, abbreviated)
- `model_families` (id, name, vendor, release_date, modality) — the thing the evolution chart plots.
- `model_artifacts` (id, family_id, quant, hf_repo, hf_revision, file_sha256, params_total/active).
- `challenges` (id, slug, category, verification, **seed_difficulty**, capabilities[], content_hash,
  version, spec, tests_ref, author_id, status: draft|submitted|review|published).
- `challenge_calibration` (materialized: challenge_id, **calibrated_tier** T0–T4, pass_rate,
  smallest_passing_params, oldest_passing_release — recomputed from `results` as submissions arrive).
- `suites` (id, name, version, content_hash, challenge_ids[], **official** bool, curator_id) — an
  admin-canonized, versioned selection; leaderboards are scoped to a (suite, version).
- `submissions` (id, submitter_id, artifact_id, engine, env JSONB, suite_id, bundle_hash, signature,
  submitted_at, trust_tier).
- `results` (id, submission_id, challenge_id, challenge_hash, score JSONB, passed, total, tok_per_s,
  latency_s, transcript_ref, judge JSONB) — one row per challenge per submission.
- `verifications` (submission_id, verifier, status, reproduced_score).
- `capability_scores` (materialized view: family_id, category, difficulty, best/median score, n) for
  fast leaderboards & charts.
- `users` (handle, pubkey, role).
JSONB carries the open-schema bits (env, score breakdowns, future capability-specific fields).

### 6a. Runs are faceted, never collapsed — "fits-my-hardware" leaderboards
A **run** = a `submission` = one *fully-specified config* `(artifact + quant + ctx + serve/offload
flags + hardware + driver + engine version)` scored on a suite. **We never pre-collapse runs** — a
Q4@24GB run and a Q8@48GB run of the same model are distinct points. The leaderboard is therefore a
**query with filters**, not a fixed table:
- **Filter dimensions:** VRAM budget, quant, context length, min tok/s, hardware class, driver,
  engine version, trust tier. Under an active filter, each family collapses to its **best
  *qualifying* run**.
- **Hero use case:** filter `≤24GB VRAM` → runs needing more (bigger quant / longer ctx) drop out,
  surfacing the realistic ranking for that card. "Best coder that fits my 3090" = one query. Few
  leaderboards answer this; for local models it's *the* question.
- **VRAM filter semantics:** filter by a config's **minimum VRAM to run** (property of the config),
  best evidenced by the smallest-VRAM run that achieved it — another reason to keep every run and
  want multiple submitters (they collectively pin down each config's hardware envelope). Measured
  tok/s stays hardware-specific, shown per run.
- **Evolution chart:** runs plot separately by default; "group by family" and "best-per-family under
  filter X" are display toggles — enabling e.g. *"evolution of models that fit 24GB"*.
- **Calibration uses best-qualifying-run-per-family**, so a bad quant doesn't distort a challenge's
  difficulty tier (we measure a family's capability at its best).

## 7. Monorepo layout
```
/engine     today's bench/ harness, refactored into a library + CLI that emits result bundles
            (serve, run, extract, sandbox, scoring, judge — already exist). Adds: bundle writer,
            signing, env capture, content-hashing of challenges/suites.
/schema     the result-bundle JSON Schema + capability taxonomy enums (shared contract, versioned).
/api        FastAPI: submission ingest + validation, leaderboard/query endpoints, verification jobs.
/web        Next.js: leaderboards, capability-vs-time charts, model & challenge pages, submit flow.
/challenges the public challenge set (current meta.toml/spec.md/tests/reference format, formalized).
/db         migrations (Alembic).
/infra      docker-compose (Postgres + api + web), sandbox runners.
```
The existing repo restructures in place: `bench/ → engine/` (**done**), `challenges/` stays, `serve/`
trimmed to the reusable local model-serving helpers, lab cruft + `results/` cleared.

## 8. Security
- **Untrusted code runs sandboxed.** Already partly done: `sandbox.py` uses subprocess + timeout +
  the new `RLIMIT_AS` memory cap. For the platform: run challenge tests and agent-generated code in
  containers (cgroups: cpu/mem/pids/no-net by default). The P3 multi-machine tier uses microVMs
  (Firecracker) on an isolated network.
- **User-authored challenges** go through a moderation queue + automated checks (reference solution
  must pass its own tests in the sandbox; resource limits) before `published`.
- Submissions are signed; abuse/sybil handled by trust tiers + rate limits, not gatekeeping.

## 9. Phased roadmap
- **P1 — Reproducible coding leaderboard (MVP).**
  1. Define `/schema` result-bundle v1 + capability taxonomy.
  2. Refactor `bench/ → engine/`: emit & sign bundles; capture full model/env/challenge metadata;
     content-hash challenges + suites.
  3. Postgres schema + Alembic migrations; FastAPI submission ingest (validate schema + signature +
     re-derive bundle hash) and leaderboard/query endpoints.
  4. Next.js: overall + per-category leaderboards, model pages, **capability-vs-release-date charts**,
     a "how to submit" CLI guide.
  5. Seed by re-running the engine on a handful of models to produce the first real bundles.
  6. **community-verified** tier (auto-promote deterministic results reproduced ≥N times).
- **P2 — Challenge authoring + efficiency metrics.** (a) ✅ **DONE (core) — Open-corpus authoring +
  moderation.** `engine/propose.py` builds a content-addressed, ed25519-signed challenge proposal
  from a local dir (validates structure + runs the reference *author-side* — the API never executes
  untrusted code, by design). API: `POST /proposals` (signed, deduped) → `GET /proposals` queue →
  `POST /proposals/{id}/review` (admin-signed approve/reject) → materializes a versioned, attributed
  `Challenge` (published); `POST /challenges/{id}/deprecate` (admin-signed). Admins = ed25519
  allowlist (`PEAKSTONE_ADMIN_KEYS`); actions signed as `<decision>:<hash>` (no replay). Sandbox
  hardened with RLIMIT_FSIZE + no core dumps. Web: read-only `/proposals` queue + propose how-to.
  _Deferred:_ per-challenge threaded discussion; file-upload web authoring form (CLI is the path).
  (b) ✅ **DONE — No-LLM automated metrics.** `engine/metrics.py` records deterministic,
  judge-free axes per result — `loc`, `solution_bytes`, `peak_rss_mb` (GNU `/usr/bin/time -v` over
  the test run, all 5 languages), `test_wall_s` — carried in the bundle's `metrics` object (schema
  `$defs.result.metrics`). The API aggregates them per run and the leaderboard is sortable by any
  axis (`?sort=loc&order=asc`, advertised in `/facets.sort_axes`); the web shows an **Efficiency**
  column + a "Rank by" control, so a model can be correct-but-bloated vs correct-and-lean.
  _Deferred to a later slice:_ binary/artifact size + compile time (the corpus is library+tests, no
  `main` to build) and a dedicated runtime perf harness (ops/sec); cyclomatic/lint/dep-count.
- **P3 — Agentic & multi-machine.** ✅ **DONE (foundation).** `engine/env/`: the
  **`EnvironmentProvider` abstraction** (`base.py`) — provision N isolated nodes → `write_file` /
  `run` / `read_logs` + peer discovery (`PORT`, `PEER_<NAME>_HOST/PORT`) → teardown. Two impls
  behind one interface: **local multi-process** (`local.py`, tests/CI) and **docker-compose**
  (`docker.py`, `internal: true` no-internet network, images pinned by digest). Goal-state-env
  challenges ship a topology (`env.toml`) + a deterministic `verify(env)` verifier + `fixtures/` +
  `reference/`; `harness.run_once` seeds → launches servers (waits ready) → runs clients → verifies.
  First example `challenges/env/01-file-server` (server/client byte transport) passes on **both
  providers**. `agent.py` is the live-LLM run mode (write→run→verify loop). Bundle carries
  `result.env` (provider + image digests + verifier checks + turns-to-green); `verification=
  goal-state-env`; deterministic verifier → can reach runner-verified. **Network capability layer
  (`capabilities.py`):** a challenge declares network conditions in `env.toml` (`[network]` egress/
  dns, `[[links]]` latency/loss/firewall/nat); providers advertise capabilities at a *fidelity*
  (docker: egress/dns/firewall/nat **real**, link shaping **simulated**); `match`/`select_provider`
  pick the cheapest sufficient provider and record fidelity in `result.env.network_fidelity` (gates
  trust); capabilities double as **preconditions** the harness asserts (`check_preconditions`, e.g.
  egress really blocked) before scoring. **Reproducibility policy: real-host providers
  (ssh-to-hosts) are excluded by design** — `public_ip`/`real_dns` are unsatisfiable rather than run
  under non-reproducible conditions. **Docker now *applies* `[[links]]` conditions** (not just
  advertises): a privileged `nicolaka/netshoot` sidecar joins each node's netns and runs `tc` netem
  (latency/loss/bandwidth) + `iptables` (firewall), so node containers stay unprivileged; applied
  rules recorded in `provenance.network.applied`. **Firecracker microVM provider — Milestone 1
  done + verified on hardware** (`firecracker.py` + `firecracker_agent/`): `provision()` boots a real
  microVM per node (`firecracker --no-api --config-file`) with a static Go guest agent as PID 1 over
  **vsock** — write_file/read_file/run/read_logs, ~1s boot. Needs only `/dev/kvm` + binary +
  kernel/rootfs (no TAP/CAP_NET_ADMIN). Guest image built sudo-free via `mkfs.ext4 -d`
  (`firecracker_agent/build-image.sh`). **Milestone 2 done + verified:** multi-node node↔node
  networking over an isolated host bridge + a pre-created user-owned tap pool (`fc-net-setup.sh`, run
  once as root → no runtime CAP_NET_ADMIN). Each VM gets a static IP; guest eth0+lo brought up
  post-boot over vsock; peers resolve by name via injected `/etc/hosts` + the `PEER_<NAME>_HOST/PORT`
  contract; no-uplink bridge → real `egress=blocked`. Verified: two microVMs, client fetches from
  server by name over the bridge, internet unreachable. Its win over docker is *isolation* (real
  kernel boundary for untrusted agent code). 22 tests (real microVM boot+exec, 2-VM bridge comms,
  docker firewall/netem). **Agent run-mode wired end-to-end:** `python -m peakstone.engine.runner --env
  --models <m> [--env-provider auto|local|docker|microvm]` runs goal-state-env challenges through the
  agent tool-loop (auto-selecting the cheapest satisfying provider) and emits goal-state-env bundle
  rows. The API scores them as a **separate `agent_score` axis** (not folded into code/safety) and
  the leaderboard faces on it (`?sort=agent_score` → "Agentic leaderboard"); the web shows an Agentic
  column + dynamic heading. Agent loop tested without a live model via a stub client. **p2p/convergence
  example** (`challenges/env/02-gossip-max`): 3 fully-connected peers gossip until all converge on
  the global max; deterministic verifier polls for convergence; passes on local + docker. **Planner
  env type** (`engine/env/planner.py`, runner `--planner <m> --coder <c>`): planner writes a plan →
  fixed coder executes → tests verify; scored on a separate **planner_score** axis (the same coder
  isolates planning from coding); web shows a Planner column + "Planner leaderboard". Stub-tested
  (plan→reference-code→tests) + verified live with two real agents (planner wrote a recursive-descent
  plan, coder implemented it → 10/10 on py-05-calc). **Link-condition completion:** docker shaping now
  supports **multiple shaped destinations per source** (prio qdisc + per-dst `tc` filters,
  `netshape.py`); microvm **firewall** is applied **in-guest** via blackhole routes (no host
  privilege) — microvm link *shaping* stays on docker (CI guest kernel lacks `sch_netem`). P3 is
  complete; only a netem-enabled custom guest kernel (for microvm shaping) remains as optional future
  work.
- **P4 — Multimodal.** vision-to-UI (build interface from screenshot/video), game-playing, for
  models that support it.

## 10. Immediate next steps (P1, in order)
1. ✅ **DONE** — name (Peakstone) + license (Apache-2.0 / CC-BY-4.0) + `/schema/result-bundle.schema.json`
   v1 + `taxonomy.json` (validated). Repo cleaned of lab cruft; `bench/ → engine/` carve-out done.
2. ✅ **DONE (P1.2)** — `engine/bundle.py` `produce_bundle()` (model identity + file SHA-256 + env +
   content-hashed challenges + transcripts + scores), schema-validated, content-addressed,
   ed25519-signed via `engine/keys.py` (auth-agnostic). `runner --bundle` emits it.
3. ✅ **DONE (P1.3)** — `infra/docker-compose.yml` (Postgres + api) + Dockerfile. **Alembic done:**
   `api/alembic/` with env wired to `Base.metadata` + `PEAKSTONE_DATABASE_URL`; initial revision
   `df8d401ae31a` (`alembic upgrade head`; `alembic check` clean). `create_all` kept for dev/tests.
4. ✅ **DONE (P1.4)** — `api/`: `POST /submissions` (trust chain), faceted `GET /leaderboard`
   (incl. `max_vram_gb` "fits-my-hardware" filter), `GET /models/{family}`, `GET /facets`,
   `GET /challenges[/{id}]`. **Identity binding done:** provider-pluggable account binding
   (`api/identity.py`) — key-ownership proof (signed nonce) + OAuth account proof; GitHub wired
   behind `PEAKSTONE_GITHUB_CLIENT_ID/SECRET` (503 until configured). **Community-verified tier
   done:** a run is promoted once ≥`PEAKSTONE_COMMUNITY_MIN_IDENTITIES` (default 2) distinct
   identities reproduce its deterministic result vector (`repro_sig`); two keys on one bound
   account count once (anti-self-verify). 7 pytest cases in `api/tests/`. Verified SQLite + Postgres.
5. ✅ **DONE (P1.5)** — `web/` Next.js 16 (React 19, Tailwind 4): coder leaderboard with the VRAM
   filter pills **+ quant/trust selects**, model detail page (uncollapsed runs, submitter handle),
   **challenge corpus + per-challenge mini-leaderboards** (`/challenges`), capability-vs-release-date
   evolution chart (recharts), and a "how to submit" CLI guide. `npm run build` green; verified live
   end-to-end (VRAM + quant filters narrow correctly; challenge pages render).

## 11. Open questions to resolve as we build
- ~~Project name & domain~~ **DECIDED: Peakstone / peakstone.ai.** License: Apache-2.0 (code +
  challenges, via DCO) + CC-BY-4.0 (result data); name reserved as trademark (`NOTICE`,
  `TRADEMARK.md` in place). Copyright holder = **The Peakstone Authors** (swap to a personal name or
  formed entity later if desired). Still TODO: grab GitHub org `peakstone` + PyPI `peakstone`.
- Identity (design **decided**, providers TBD): the **ed25519 pubkey is the root identity** (durable,
  portable); auth providers are **pluggable bindings** that merely attest "account ↔ pubkey", keyed
  by an internal user id — never a provider's id. Tables: `keys` (pubkey → user) + `identity_links`
  (user ↔ provider account, many per user). GitHub OAuth ships first (dev-friendly); GitLab/Google/
  email-magic-link/wallet(SIWE)/ORCID are additive later. A keypair alone works (pseudonymous, no
  OAuth). The engine/bundle layer is auth-agnostic — it only signs and embeds pubkey+signature.
- Transcript storage: inline vs. object store (S3-compatible) for large suites; retention.
- Anti-gaming for non-deterministic/judge challenges (seed disclosure, multi-run medians).
- Calibration mechanics (DEFERRED until we build it): exact pass-rate thresholds for the T0–T4
  bands, and the minimum number of distinct models before a `calibrated_tier` is "stable" vs.
  "provisional".
- `model_families` still needs grouping rules for the *family* node (base vs. fine-tunes), but
  quants/ctx/hardware are NOT collapsed — they remain distinct runs (see §6a).

> Resolved this round: **suite governance** — open corpus + admin-canonized versioned suites;
> official leaderboards are per-(suite, version). **Difficulty** — empirical/calibrated tiers from
> submission data, not param-bucketed. **Run granularity** — every (quant, ctx, hardware, driver,
> engine) is a distinct, never-collapsed run; the leaderboard is a faceted query, with a
> "fits-my-hardware" (VRAM/perf) filter as a headline feature (§6a).
