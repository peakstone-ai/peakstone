# Peakstone web

The public site at [peakstone.ai](https://peakstone.ai) — a Next.js (App Router) frontend over the
Peakstone API: leaderboard, model/run/challenge detail pages, the capability-evolution chart, and
the submit/propose docs. All data is fetched server-side from the API (30s fetch cache); there is
no client-side data layer.

## Develop

```bash
npm install
npm run dev        # http://localhost:3000, expects the API at http://localhost:8000
npm run lint       # eslint (next/core-web-vitals + typescript)
npm run build      # production build (standalone output)
```

Point at a different API with env vars:

- `NEXT_PUBLIC_API_URL` — where the **server** fetches data (may be a container-internal address).
- `NEXT_PUBLIC_API_PUBLIC_URL` — the API base rendered into pages (curl examples); must be the
  visitor-reachable URL, never the internal one.

## Deploy

`web/Dockerfile` builds the standalone bundle; `infra/docker-compose.yml` runs it behind Caddy
(site at `/`, API at `/api`). See the repo-root RELEASE.md for the deploy runbook.

## Conventions

- `lib/api.ts` — every fetcher returns a discriminated `ApiResult<T>`; an API 404 renders a real
  404 via `notFound()`, transient unreachability renders the `ApiDown` card. The TS types are
  pinned to what the API emits by `peakstone/api/tests/test_web_contract.py`.
- `lib/params.ts` — the one list of leaderboard query params (redirects, fetcher, pill links).
- No root `loading.tsx`: a root loading boundary streams the 200 header before `notFound()` can
  set a 404 — loading files live only on leaf list segments.
