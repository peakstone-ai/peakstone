#!/usr/bin/env bash
# Self-repair pass — measures iterative debugging cheaply. Re-runs ONLY the challenges a model FAILED
# in its prior standard run, this time with self-repair (`--retries`: the failing test output is fed
# back so the model can fix its own code), then merges the recovered results back over the original
# run and resubmits. Touches only the failures, so it's far cheaper than a full re-run, and the
# merged bundle gains the self-repair signal (attempts / passed_on_attempt).
#
# Prereqs: the API is up and the model has a prior `--level standard` run submitted.
#
#   ./serve/repair_failures.sh <model> [results.json]
#   RETRIES=2 PASS_THRESHOLD=0.999 API=http://localhost:8000 ./serve/repair_failures.sh qwen3-coder
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/opt/node/bin:$PATH"

API="${API:-http://localhost:8000}"
RETRIES="${RETRIES:-2}"
THRESH="${PASS_THRESHOLD:-0.999}"
TIMEOUT="${PER_MODEL_TIMEOUT:-4h}"
m="${1:?usage: repair_failures.sh <model> [results.json]}"
res="${2:-}"
curl -fsS "$API/healthz" >/dev/null 2>&1 || { echo "!! API not reachable at $API/healthz"; exit 1; }

# locate the model's most recent standard run if a results.json wasn't given
if [ -z "$res" ]; then
  res=$(python3 - "$m" <<'PY'
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
fi
[ -n "$res" ] || { echo "!! no standard results.json found for $m (pass one explicitly)"; exit 1; }

STAMP=$(date +%Y%m%d-%H%M%S); OUT="results/repair-$m-$STAMP"; mkdir -p "$OUT"

# the failures to retry: coding challenges in the standard set scored below the pass threshold
python3 - "$res" "$THRESH" "$OUT/failed.ids" <<'PY'
import sys, json, pathlib
from peakstone.engine import challenges as C
from peakstone.engine.levels import load_levels, resolve
res, thr, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
want = set(resolve(load_levels()[1]["standard"], C.load_challenges(pathlib.Path("challenges"))))
rows = json.load(open(res))["results"]
fail = [r["challenge"] for r in rows
        if (r.get("final_score") or 0) < thr and r.get("scoring") in ("tests", "both")
        and r["challenge"] in want]
open(out, "w").write("\n".join(fail))
print(f"{len(fail)} failed coding challenges in standard to retry")
PY
n=$(grep -cve '^$' "$OUT/failed.ids" || true)
[ "${n:-0}" -gt 0 ] || { echo "no failures to repair — nothing to do"; exit 0; }
echo "=== [$m] $n failures → self-repair (--retries $RETRIES); base=$res ==="

bash serve/serve.sh "$m" > "$OUT/server.log" 2>&1 & SRV=$!
ready=0
for _ in $(seq 1 180); do
  grep -q "server is listening" "$OUT/server.log" 2>/dev/null && { ready=1; break; }
  kill -0 "$SRV" 2>/dev/null || { echo "!! server died:"; tail -5 "$OUT/server.log"; break; }
  sleep 2
done
[ "$ready" = 1 ] || { echo "!! $m never ready"; kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null; exit 1; }

timeout "$TIMEOUT" python -u -m peakstone.engine.runner --models "$m" \
    --ids-file "$OUT/failed.ids" --retries "$RETRIES" --no-judge --bundle --out "$OUT" > "$OUT/run.log" 2>&1
rc=$?; [ "$rc" = 124 ] && echo "!! hit the $TIMEOUT timeout — partial"
kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null; pkill -f "llama-server.*$m" 2>/dev/null
tail -4 "$OUT/run.log" | sed 's/^/    /'

[ -f "$OUT/results.json" ] || { echo "!! no retry results.json produced"; exit 1; }
echo "=== [$m] merging recovered results over the original run + submitting ==="
python3 scripts/repack_to_standard.py "$res" --overlay "$OUT/results.json" --submit "$API" --out "$OUT/combined.bundle.json"
echo "Done — repaired run under $OUT/"
