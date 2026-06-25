#!/usr/bin/env bash
# Planner evaluation (plan -> fixed coder -> tests), decoupled so only one model is in VRAM
# at a time. Phase A: each planner writes a plan per architecture task. Phase B: a single fixed
# coder (qwen3-coder) implements every plan and we test the result. Then merge into one
# Planner leaderboard.
#
#   ./serve/planner_eval.sh                         # default planners over the architecture set
#   ./serve/planner_eval.sh glm-planner qwen3.6-35b-a3b
#   CODER=devstral TYPE=architecture ./serve/planner_eval.sh glm-planner
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/opt/node/bin:$PATH"

PLANNERS=("$@")
[ ${#PLANNERS[@]} -eq 0 ] && PLANNERS=(glm-planner qwen3.6-35b-a3b qwen3.6-27b vibethinker-3b)
CODER="${CODER:-qwen3-coder}"
TYPE="${TYPE:-architecture}"

STAMP=$(date +%Y%m%d-%H%M%S)
OUT="results/planner-$STAMP"
mkdir -p "$OUT"
echo "Planner eval -> $OUT   planners: ${PLANNERS[*]}   coder: $CODER   type: $TYPE"

# Serve a model and block until it is ready; sets SRV to its pid. Returns 1 on failure.
serve_wait() {
  bash serve/serve.sh "$1" > "$OUT/$1.server.log" 2>&1 &
  SRV=$!
  for _ in $(seq 1 180); do
    grep -q "server is listening" "$OUT/$1.server.log" 2>/dev/null && return 0
    kill -0 "$SRV" 2>/dev/null || { echo "server for $1 died:"; tail -5 "$OUT/$1.server.log"; return 1; }
    sleep 2
  done
  return 1
}
stop_srv() { kill "${SRV:-}" 2>/dev/null; wait "${SRV:-}" 2>/dev/null; sleep 3; }

# --- Phase A: generate plans with each planner (one in VRAM at a time) ---
for p in "${PLANNERS[@]}"; do
  echo "=== [plan] $p ==="
  if ! serve_wait "$p"; then echo "!! $p never became ready; skipping"; stop_srv; continue; fi
  python -m peakstone.engine.runner --gen-plans "$p" --type "$TYPE" --max-tokens "${MAXTOK:-16384}" \
    --out "$OUT/plans-$p" 2>&1 | tail -10
  stop_srv
done

# --- Phase B: one fixed coder implements every planner's plans (+ a solo baseline) ---
echo "=== [exec] coder=$CODER ==="
if ! serve_wait "$CODER"; then echo "!! coder $CODER never became ready"; stop_srv; exit 1; fi
# solo baseline: the fixed coder doing the same tasks WITHOUT a plan -> the Planner leaderboard's
# "vs baseline" lift is each planner's downstream score minus this.
python -m peakstone.engine.runner --models "$CODER" --type "$TYPE" --no-judge --out "$OUT/baseline-$CODER" 2>&1 | tail -6
for p in "${PLANNERS[@]}"; do
  [ -d "$OUT/plans-$p" ] || continue
  python -m peakstone.engine.runner --exec-plans "$OUT/plans-$p" --coder "$CODER" --type "$TYPE" \
    --no-judge --out "$OUT/exec-$p" 2>&1 | tail -10
done
stop_srv

echo "=== merging ==="
python -m peakstone.engine.merge "$OUT"/exec-*/results.json "$OUT"/baseline-*/results.json --out "$OUT/combined"
echo ""
echo "DONE. Planner leaderboard: $OUT/combined/leaderboard.md"
