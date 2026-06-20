# Peakstone API

Submission ingest + faceted leaderboards (FastAPI + SQLAlchemy 2.0). Reuses `engine/` for bundle
hashing + signature verification, and `schema/` for validation.

## Run — dev (SQLite, zero infra)
```bash
pip install -r api/requirements.txt
uvicorn api.main:app --reload            # creates ./peakstone.db on startup
```

## Run — prod (Postgres via compose)
```bash
docker compose -f infra/docker-compose.yml up --build   # api on :8000, postgres on :5432
alembic upgrade head                                     # apply schema migrations (see below)
```

## Endpoints
| Method | Path | Purpose |
|---|---|---|
| `POST` | `/submissions` | validate (schema + content-hash + ed25519 signature) → store a run |
| `GET` | `/leaderboard` | **faceted** — `?suite&version&max_vram_gb&quant&trust`; each family collapses to its best *qualifying* run |
| `GET` | `/models/{family}` | every run for a family, **uncollapsed** (quants/contexts/hardware) |
| `GET` | `/facets` | distinct `quants` / `suites` / `trust_tiers` for the filter UI |
| `GET` | `/challenges` | the corpus with empirical pass-rate (calibrated difficulty) |
| `GET` | `/challenges/{id}` | per-challenge mini-leaderboard (best result per family) |
| `POST` | `/account/key-challenge` | issue a nonce the key signs to prove ownership |
| `GET` | `/auth/{provider}/authorize-url` | build the provider OAuth consent URL (503 if unconfigured) |
| `POST` | `/account/bind` | bind a key to an account: signed nonce + OAuth `code` |
| `GET` | `/account?pubkey=` | who a key belongs to (user + linked providers) |
| `GET` | `/healthz` | liveness |

Produce a bundle to submit: `python -m engine.runner --models <m> --bundle` → `bundle.json`, then
`curl -X POST localhost:8000/submissions -H 'content-type: application/json' --data @bundle.json`.

## Trust chain (ingest)
1. JSON Schema valid → 2. re-derived `bundle_hash` matches the claimed one → 3. ed25519 signature
over that hash verifies. Stored as `trust_tier='self-reported'`. Duplicate bundle → 409; bad
schema/hash/signature → 400.

**Community-verified** is computed automatically: every run records a `repro_sig` (a fingerprint of
its deterministic result vector). Once ≥ `PEAKSTONE_COMMUNITY_MIN_IDENTITIES` (default 2) *distinct
identities* submit the same `(artifact, suite, repro_sig)`, all runs in that group are promoted.
An identity is the key's bound account if linked, else the key itself — so two keys on one account
count once (anti-self-verify). `runner-verified` is set out-of-band and never downgraded.

## Identity binding (`api/identity.py`)
The ed25519 key is the **root** identity; accounts are optional, additive bindings (no lock-in).
Binding requires two proofs in one `POST /account/bind`: (1) the key signs a server nonce
(`/account/key-challenge`), and (2) an OAuth `code` from the provider. GitHub is the first provider,
gated on `PEAKSTONE_GITHUB_CLIENT_ID` / `PEAKSTONE_GITHUB_CLIENT_SECRET` (endpoints return 503 until
set). New providers are a single entry in `identity.PROVIDERS`.

## Migrations (Alembic)
Schema is versioned in `api/alembic/`; `env.py` reads `PEAKSTONE_DATABASE_URL` and diffs against
`api/models.py`.
```bash
alembic upgrade head                          # apply
alembic revision --autogenerate -m "msg"      # after editing models.py
alembic check                                 # CI: fail if models drift from migrations
```
`Base.metadata.create_all` (in `init_db`) is retained for dev/tests only.

## Tests
`pytest api/tests/` — trust chain, community-verified promotion, anti-self-verify, account binding
(stubbed OAuth), facets, challenges. No network / GPUs needed.
