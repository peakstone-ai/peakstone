# Peakstone — Release & Deploy Runbook

Step-by-step for cutting a release and deploying `peakstone.ai` (site + API + Postgres behind Caddy).
Work top to bottom; each step has a check. Placeholders: `<DOMAIN>` = peakstone.ai, `<SERVER>` = the
deploy box, `<GPU-BOX>` = the machine with the GPU that runs the seed benchmarks.

---

## 0. Pre-flight (on your dev machine)

- [ ] **Tests green.** (Firecracker microVM networking tests need KVM + a tap pool; skip them.)
  ```bash
  python -m pytest peakstone -q --ignore=peakstone/engine/env/tests/test_firecracker.py
  ```
- [ ] **Web builds.**
  ```bash
  cd web && PATH=~/opt/node/bin:$PATH npm run build && cd ..
  ```
- [ ] **Commit + push + tag.** (Confirm `RELEASE-REVIEW.md` is NOT committed — it's gitignored.)
  ```bash
  git status                      # clean tree
  git push origin main
  git tag -a v0.1.0 -m "Peakstone v0.1.0" && git push origin v0.1.0
  ```

## 1. GitHub OAuth app (enables `peakstone login` / account binding)

- [ ] Create an OAuth app: <https://github.com/settings/developers> → **New OAuth App**.
  - Homepage URL: `https://<DOMAIN>`
  - **Authorization callback URL: `http://127.0.0.1:53682/callback`**  ← the CLI loopback port
    (`peakstone login`). Without this exact callback, login fails.
- [ ] Copy the **Client ID** and generate a **Client Secret** (used in step 3).

## 2. Get the seed key's public key (for the trusted/ranked tier)

Runs signed by this key ingest as **runner-verified** and appear on the ranked board (M2). Run this
on **<GPU-BOX>** (the machine that will submit the seed runs) — it creates the key on first use:
```bash
python -c "from peakstone.engine import keys; print(keys.load_or_create_keypair()[1])"
```
- [ ] Save the printed base64 pubkey → `PEAKSTONE_TRUSTED_PUBKEYS` in step 3.

## 3. Configure the server (`<SERVER>`)

- [ ] DNS **A record** `<DOMAIN>` → `<SERVER>` public IP; ports **80 + 443** reachable.
- [ ] Docker + compose installed.
- [ ] Clone + config:
  ```bash
  git clone https://github.com/peakstone-ai/peakstone && cd peakstone
  cp infra/.env.example infra/.env
  ```
- [ ] Edit `infra/.env` — all of these matter:
  - `PEAKSTONE_DOMAIN=<DOMAIN>`
  - `POSTGRES_PASSWORD=` a strong password (**not** the placeholder)
  - `PEAKSTONE_OFFICIAL_SUITE=level-standard@2026.06`
  - `PEAKSTONE_TRUSTED_PUBKEYS=` the pubkey from step 2  ← **or the ranked board is empty**
  - `PEAKSTONE_GITHUB_CLIENT_ID=` / `PEAKSTONE_GITHUB_CLIENT_SECRET=` from step 1

## 4. Deploy

- [ ] Build + migrate + start (db + api + web + caddy; Caddy auto-provisions the TLS cert):
  ```bash
  ./infra/deploy.sh
  ```
  Serves the **site at `/`** and the **API at `/api/*`** on `<DOMAIN>`.

## 5. Verify the deploy

- [ ] API health: `curl https://<DOMAIN>/api/healthz` → `{"status":"ok"}`
- [ ] Site loads: open `https://<DOMAIN>/` → the leaderboard (empty until seeded — that's fine).
- [ ] Leaderboard API: `curl https://<DOMAIN>/api/leaderboard` → JSON, scoped to `level-standard@2026.06`.

## 6. Seed the official board (from `<GPU-BOX>`, hours of GPU)

Runs each model on the official level and submits a **signed** bundle to prod (signed by the step-2
key, so they rank). One model in VRAM at a time.
- [ ] Weights present for the roster (`serve/download_models.sh`), then:
  ```bash
  API=https://<DOMAIN>/api nohup ./serve/seed_official.sh > seed.out 2>&1 &
  tail -f seed.out
  ```
- [ ] (Optional, strongest isolation for ranked runs) prepend `PEAKSTONE_SANDBOX=firecracker` after
  building the toolchain rootfs: `FC_TOOLCHAIN=1 peakstone/engine/env/firecracker_agent/build-image.sh`.

## 7. Post-deploy checks

- [ ] Ranked board populated: `https://<DOMAIN>/` shows models in the **ranked** tier (not all
  "provisional"). If all provisional → `PEAKSTONE_TRUSTED_PUBKEYS` didn't match the seed key.
- [ ] Run explorer works: click a model → a run → a challenge → the proposed solution renders.
- [ ] `peakstone login --api https://<DOMAIN>/api` completes and shows `@yourhandle`.

## 8. Publish the client (optional — PyPI)

Lets others `pipx install "peakstone[dashboard]"`.
- [ ] `python -m build && twine upload dist/*` (version = the git tag).
- [ ] Tell users to point at the public API path: `peakstone --api https://<DOMAIN>/api`.

## 9. Update / rollback

- Update: `git pull && ./infra/deploy.sh` (migrations run first; idempotent).
- Rollback: `git checkout <previous-tag> && ./infra/deploy.sh`.
- Logs: `docker compose -f infra/docker-compose.yml --env-file infra/.env logs -f api`.

---

## Appendix A — local / LAN dev (never touches the deploy)

Config-driven via `~/.peakstone/config.toml` (untracked). To expose on your LAN, set `host="0.0.0.0"`
under `[api]` (and `[gateway]`), then run the services directly — plain HTTP, no Caddy/TLS:
```bash
python -m peakstone.api                                        # API  → 0.0.0.0:8000
cd web && PATH=~/opt/node/bin:$PATH npx next dev -H 0.0.0.0    # site → 0.0.0.0:3000
```
Reach from another device at `http://<lan-ip>:3000` / `:8000` (use **http://** and the explicit port).
Local smoke test of the full Docker stack: `docker compose -f infra/docker-compose.yml up --build`
(self-signed `https://localhost/`).

## Appendix B — the "don't forget" list

| Thing | Symptom if missed |
| --- | --- |
| `PEAKSTONE_TRUSTED_PUBKEYS` = seed key pubkey | Ranked board empty (all provisional) |
| GitHub OAuth callback `http://127.0.0.1:53682/callback` | `peakstone login` fails |
| `PEAKSTONE_GITHUB_CLIENT_ID/SECRET` in `infra/.env` | login: "provider not configured" |
| `POSTGRES_PASSWORD` changed from placeholder | Weak DB creds on a public box |
| Clients use the **`/api`** path | 404 hitting `https://<DOMAIN>/leaderboard` directly |
| DNS A record + ports 80/443 open | Caddy can't get a cert / site unreachable |
