#!/usr/bin/env bash
# One command to run the FULL challenge suite on every model (smallest first), regenerating the
# HTML report after each model, then run the code-quality judge and regenerate once more.
#
#   ./serve/run_all.sh [judge-model]        (default judge: qwen3-coder)
#
# Output: results/full-<stamp>/report.html  (updated incrementally after every model + the judge)
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/opt/node/bin:$PATH"

JUDGE="${1:-qwen3-coder}"
# smallest -> largest by parameter count
MODELS=(phi-4-mini qwen3.5-9b devstral qwen3.6-27b qwen3-coder glm-4.7-flash qwen3.6-35b-a3b)

STAMP=$(date +%Y%m%d-%H%M%S)
OUT="results/full-$STAMP"; mkdir -p "$OUT"
REPORT="$OUT/report.html"
echo "Full run -> $OUT"
echo "Live report -> $REPORT"

regen() {  # merge the per-model results that exist so far, regenerate the HTML report
  local inputs=()
  for mm in "${MODELS[@]}"; do
    [ -f "$OUT/$mm/results.json" ] && inputs+=("$OUT/$mm/results.json")
  done
  [ ${#inputs[@]} -eq 0 ] && return 0
  python -m bench.merge "${inputs[@]}" --out "$OUT/combined" >/dev/null 2>&1
  python -m bench.report_html "$OUT" --out "$REPORT" >/dev/null 2>&1
}

for m in "${MODELS[@]}"; do
  echo "=== [$m] serving + running full suite ==="
  port=$(python3 -c "import tomllib;print(tomllib.load(open('serve/models.toml','rb'))['$m']['port'])")
  log="$OUT/$m.server.log"
  nohup bash serve/serve.sh "$m" > "$log" 2>&1 &
  SRV=$!
  ok=0
  for _ in $(seq 1 180); do
    grep -q "server is listening" "$log" 2>/dev/null && { ok=1; break; }
    kill -0 "$SRV" 2>/dev/null || break
    sleep 2
  done
  if [ "$ok" = 1 ]; then
    python -m bench.runner --models "$m" --no-judge --out "$OUT/$m" 2>&1 | tail -3
  else
    echo "!! $m failed to serve"; tail -5 "$log"
  fi
  kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null; sleep 2
  regen
  echo "=== [$m] done; report updated ==="
done

echo "=== finalize: code-quality judge + auto recommendations ($JUDGE) ==="
jport=$(python3 -c "import tomllib;print(tomllib.load(open('serve/models.toml','rb'))['$JUDGE']['port'])")
jlog="$OUT/$JUDGE.judge.server.log"
nohup bash serve/serve.sh "$JUDGE" > "$jlog" 2>&1 &
JSRV=$!
jok=0
for _ in $(seq 1 180); do
  grep -q "server is listening" "$jlog" 2>/dev/null && { jok=1; break; }
  kill -0 "$JSRV" 2>/dev/null || break
  sleep 2
done
if [ "$jok" = 1 ]; then
  python -m bench.runner --judge-only "$OUT/combined" --judge-model "$JUDGE" 2>&1 | tail -3
  python -m bench.recommend "$OUT" --model "$JUDGE" 2>&1 | tail -2
else
  echo "!! judge $JUDGE failed to serve"; tail -5 "$jlog"
fi
kill "$JSRV" 2>/dev/null; wait "$JSRV" 2>/dev/null
regen   # final regen picks up the judged-* quality + recommendations.html

echo ""
echo "DONE. Final report: $REPORT"
