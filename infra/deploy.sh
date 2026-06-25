#!/usr/bin/env bash
# Peakstone server deploy — pull, build, migrate, restart. Idempotent; run it again to update.
#
# First time on the box:
#   git clone https://github.com/peakstone-ai/peakstone && cd peakstone
#   cp infra/.env.example infra/.env && $EDITOR infra/.env   # set domain + DB password
#   ./infra/deploy.sh
#
# To update later:  git pull && ./infra/deploy.sh
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root (compose build context is here)

compose="docker compose -f infra/docker-compose.yml --env-file infra/.env"

if [[ ! -f infra/.env ]]; then
  echo "infra/.env not found — copy infra/.env.example to infra/.env and set your domain + DB password." >&2
  exit 1
fi

echo ">> Building and (re)starting db + api + caddy ..."
# api's start command runs `alembic upgrade head` before serving, so the schema is migrated here.
$compose up -d --build

echo ">> Waiting for the API to report healthy ..."
domain=$(grep -E '^PEAKSTONE_DOMAIN=' infra/.env | cut -d= -f2-)
for _ in $(seq 1 30); do
  if $compose exec -T api python -c "import urllib.request,sys; urllib.request.urlopen('http://localhost:8000/healthz'); " 2>/dev/null; then
    echo ">> API healthy. Serving https://${domain}"
    exit 0
  fi
  sleep 2
done

echo "!! API did not become healthy in time. Check logs:  $compose logs api" >&2
exit 1
