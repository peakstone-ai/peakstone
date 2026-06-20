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
```

## Endpoints
| Method | Path | Purpose |
|---|---|---|
| `POST` | `/submissions` | validate (schema + content-hash + ed25519 signature) → store a run |
| `GET` | `/leaderboard` | **faceted** — `?suite&version&max_vram_gb&quant&trust`; each family collapses to its best *qualifying* run |
| `GET` | `/models/{family}` | every run for a family, **uncollapsed** (quants/contexts/hardware) |
| `GET` | `/healthz` | liveness |

Produce a bundle to submit: `python -m engine.runner --models <m> --bundle` → `bundle.json`, then
`curl -X POST localhost:8000/submissions -H 'content-type: application/json' --data @bundle.json`.

## Trust chain (ingest)
1. JSON Schema valid → 2. re-derived `bundle_hash` matches the claimed one → 3. ed25519 signature
over that hash verifies. Stored as `trust_tier='self-reported'`; community/runner verification is
computed later (P1.6). Duplicate bundle → 409; bad schema/hash/signature → 400.

## TODO (hardening)
- **Alembic migrations** — dev currently uses `Base.metadata.create_all`; production needs versioned
  migrations (autogenerate from `api/models.py`).
- **Identity binding** — pubkey is the root identity; GitHub OAuth (then other providers) to bind a
  pubkey to a handle/account is not yet implemented (PLAN.md §11).
