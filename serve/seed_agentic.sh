#!/usr/bin/env bash
# Agentic seed pass — fills the Agentic column. For each model: serve it, run the goal-state-env
# (multi-machine) challenges through the live agent loop, then MERGE those results into the model's
# existing `--level standard` run and re-submit — so the leaderboard row shows code + held-out +
# safety + agentic together (one submission, agentic excluded from the coding score).
#
# Prereqs: the API is up, and each model already has a standard run submitted (run seed_official.sh
# first). Some env challenges need network shaping (Docker); with provider=auto those run on Docker
# if it's up, else they're skipped — the rest run on the local provider.
#
#   ./serve/seed_agentic.sh                                   # default roster
#   ./serve/seed_agentic.sh qwen3-coder                       # one model
#   API=http://localhost:8000 ENV_PROVIDER=local PER_MODEL_TIMEOUT=2h ./serve/seed_agentic.sh
#   nohup ./serve/seed_agentic.sh > agentic.out 2>&1 &  tail -f agentic.out
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/opt/node/bin:$PATH"

API="${API:-http://localhost:8000}"
PROVIDER="${ENV_PROVIDER:-auto}"
TIMEOUT="${PER_MODEL_TIMEOUT:-2h}"
MODELS=("$@")
[ ${#MODELS[@]} -eq 0 ] && MODELS=(phi-4-mini qwen3.5-9b devstral qwen3-coder)

STAMP=$(date +%Y%m%d-%H%M%S)
OUT="results/agentic-$STAMP"; mkdir -p "$OUT"
echo "Agentic seed -> $OUT   API=$API   provider=$PROVIDER   models: ${MODELS[*]}"
curl -fsS "$API/healthz" >/dev/null 2>&1 || {
  echo "!! API not reachable at $API/healthz — start it first"; exit 1; }

for m in "${MODELS[@]}"; do
  echo; echo "=== [$m] $(date '+%F %T') agentic run ==="
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
  [ "$ready" = 1 ] || { echo "!! $m never ready — skipping"; kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null; continue; }

  mdir="$OUT/$m"
  echo "=== [$m] driving env challenges (provider=$PROVIDER, timeout $TIMEOUT) ==="
  timeout "$TIMEOUT" python -u -m peakstone.engine.runner --env --models "$m" \
      --bundle --env-provider "$PROVIDER" --out "$mdir" > "$OUT/$m.run.log" 2>&1
  rc=$?; [ "$rc" = 124 ] && echo "!! [$m] agentic run hit $TIMEOUT — killed; moving on"
  tail -5 "$OUT/$m.run.log" | sed 's/^/    /'

  kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null; pkill -f "llama-server.*$m" 2>/dev/null

  envres="$mdir/env-results.json"
  [ -f "$envres" ] || { echo "!! [$m] no env-results.json produced — nothing to merge"; continue; }

  # find this model's most recent standard run to merge the agentic results into
  std=$(python3 - "$m" <<'PY'
import sys, glob, json, os
m = sys.argv[1]; best = None
for p in glob.glob("results/**/results.json", recursive=True):
    try: meta = json.load(open(p)).get("meta", {})
    except Exception: continue
    if meta.get("suite_id") == "level-standard" and m in (meta.get("models") or []):
        if best is None or os.path.getmtime(p) > os.path.getmtime(best): best = p
print(best or "")
PY
)
  if [ -n "$std" ]; then
    echo "=== [$m] merging agentic into standard ($std) + submitting ==="
    python3 scripts/repack_to_standard.py "$std" --also "$envres" --submit "$API" --out "$mdir/combined.bundle.json"
  else
    echo "=== [$m] no prior standard run found — submitting agentic-only bundle ==="
    python3 - "$API" "$mdir/bundle.json" <<'PY' || echo "!! [$m] submit failed"
import json, sys
from peakstone.dashboard.client import submit_bundle
st, detail = submit_bundle(sys.argv[1], json.load(open(sys.argv[2])))
print(f"    submit: HTTP {st}  {detail[:140]}")
PY
  fi
done
echo; echo "Agentic seed complete. Logs + bundles under $OUT/"
