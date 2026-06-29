#!/usr/bin/env bash
# Seed the official board from the CLI — robust enough to leave running overnight.
#
# For each model: serve it, run the OFFICIAL standard level (generation-only / --no-judge, the
# single-GPU path), produce a signed bundle, submit it to the local API, stop the server, next.
# One model in VRAM at a time. A model that dies, never serves, or hangs past PER_MODEL_TIMEOUT is
# killed and the loop moves on — one bad model never blocks the rest. All output goes to log FILES
# (no terminal pipe), so there's no pipe-buffer deadlock like the TUI's --stream-output path.
#
# The API must already be running against your seed DB, e.g.:
#   PEAKSTONE_DATABASE_URL=sqlite:///seed.db python -m uvicorn peakstone.api.main:app --port 8000
#
# Usage:
#   ./serve/seed_official.sh                                  # the default remaining roster
#   ./serve/seed_official.sh devstral qwen3-coder            # an explicit list
#   API=http://localhost:8000 PER_MODEL_TIMEOUT=8h ./serve/seed_official.sh qwen3-coder
#   nohup ./serve/seed_official.sh > seed.out 2>&1 &  tail -f seed.out   # detach + watch
#
# phi-4-mini was already seeded via the TUI, so it's omitted from the default list (re-running it
# would just re-submit → 409). Add it back if you want a fresh bundle.
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/opt/node/bin:$PATH"

API="${API:-http://localhost:8000}"
TIMEOUT="${PER_MODEL_TIMEOUT:-6h}"
MAX_TOKENS="${MAX_TOKENS:-8192}"          # cap generation — stops runaway 16k-token rambles
MODELS=("$@")
[ ${#MODELS[@]} -eq 0 ] && MODELS=(qwen3.5-9b devstral qwen3-coder)

STAMP=$(date +%Y%m%d-%H%M%S)
OUT="results/seed-$STAMP"; mkdir -p "$OUT"
echo "Seed -> $OUT   API=$API   timeout/model=$TIMEOUT   models: ${MODELS[*]}"

# fail fast if the API/DB the bundles must land in isn't up
if ! curl -fsS "$API/healthz" >/dev/null 2>&1; then
  echo "!! API not reachable at $API/healthz — start it first:"
  echo "   PEAKSTONE_DATABASE_URL=sqlite:///seed.db python -m uvicorn peakstone.api.main:app --port 8000"
  exit 1
fi

for m in "${MODELS[@]}"; do
  echo; echo "=== [$m] $(date '+%F %T') starting ==="
  port=$(python3 -c "import tomllib;print(tomllib.load(open('serve/models.toml','rb'))['$m']['port'])" 2>/dev/null) \
    || { echo "!! $m not in serve/models.toml — skipping"; continue; }

  bash serve/serve.sh "$m" > "$OUT/$m.server.log" 2>&1 &
  SRV=$!
  ready=0
  for _ in $(seq 1 180); do
    grep -q "server is listening" "$OUT/$m.server.log" 2>/dev/null && { ready=1; break; }
    kill -0 "$SRV" 2>/dev/null || { echo "!! server for $m died:"; tail -5 "$OUT/$m.server.log"; break; }
    sleep 2
  done
  if [ "$ready" != 1 ]; then
    echo "!! $m never became ready — skipping"; kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null; continue
  fi

  echo "=== [$m] running standard (no-judge), log: $OUT/$m.run.log  (timeout $TIMEOUT) ==="
  mdir="$OUT/$m"
  timeout "$TIMEOUT" python -u -m peakstone.engine.runner --models "$m" \
      --level standard --no-judge --bundle --max-tokens "$MAX_TOKENS" --out "$mdir" > "$OUT/$m.run.log" 2>&1
  rc=$?
  [ "$rc" = 124 ] && echo "!! [$m] hit the $TIMEOUT timeout — killed; moving on"
  echo "    last lines:"; tail -3 "$OUT/$m.run.log" | sed 's/^/    /'

  echo "=== [$m] stopping server ==="
  kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null
  pkill -f "llama-server.*$m" 2>/dev/null   # belt-and-suspenders: free the VRAM before the next model

  bundle="$mdir/bundle.json"
  if [ -f "$bundle" ]; then
    echo "=== [$m] submitting bundle ==="
    python3 - "$API" "$bundle" <<'PY' || echo "!! [$m] submit failed (is the API up?)"
import json, sys
from peakstone.dashboard.client import submit_bundle
api, path = sys.argv[1], sys.argv[2]
status, detail = submit_bundle(api, json.load(open(path)))
print(f"    submit: HTTP {status}  {detail[:140]}")
PY
  else
    echo "!! [$m] no bundle produced (run failed or timed out) — nothing to submit"
  fi
done
echo; echo "Seed complete. Per-model logs + bundles under $OUT/"
