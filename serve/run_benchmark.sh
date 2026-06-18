#!/usr/bin/env bash
# Full benchmark: for each model, start its llama-server, run the whole challenge
# suite against it, stop the server, move on. Then merge into one leaderboard.
# Only one model is in VRAM at a time (24GB).
#
#   ./serve/run_benchmark.sh                       # all 4 models, tests-only scoring
#   ./serve/run_benchmark.sh glm-4.7-flash qwen3-coder
#   JUDGE=1 ./serve/run_benchmark.sh devstral      # enable LLM judge (self-judged)
#   EXTRA="--retries 2" ./serve/run_benchmark.sh phi-4-mini qwen3-coder   # pass thru runner flags
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/opt/node/bin:$PATH"

MODELS=("$@")
[ ${#MODELS[@]} -eq 0 ] && MODELS=(glm-4.7-flash qwen3-coder devstral qwen2.5-coder-32b)

STAMP=$(date +%Y%m%d-%H%M%S)
OUT="results/bench-$STAMP"
mkdir -p "$OUT"
echo "Benchmark -> $OUT   models: ${MODELS[*]}"

for m in "${MODELS[@]}"; do
  port=$(python3 -c "import tomllib;print(tomllib.load(open('serve/models.toml','rb'))['$m']['port'])")
  echo "=== [$m] starting server on :$port ==="
  bash serve/serve.sh "$m" > "$OUT/$m.server.log" 2>&1 &
  SRV=$!

  ready=0
  for _ in $(seq 1 180); do
    grep -q "server is listening" "$OUT/$m.server.log" 2>/dev/null && { ready=1; break; }
    kill -0 "$SRV" 2>/dev/null || { echo "server for $m died:"; tail -5 "$OUT/$m.server.log"; break; }
    sleep 2
  done
  if [ "$ready" != 1 ]; then
    echo "!! $m never became ready; skipping"; kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null; continue
  fi

  echo "=== [$m] evaluating ==="
  JUDGE_FLAG="--no-judge"; [ "${JUDGE:-0}" = "1" ] && JUDGE_FLAG=""
  python -m bench.runner --models "$m" $JUDGE_FLAG ${EXTRA:-} --out "$OUT/$m" 2>&1 | tail -25

  echo "=== [$m] stopping server ==="
  kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null
  sleep 3
done

echo "=== merging ==="
python -m bench.merge "$OUT"/*/results.json --out "$OUT/combined"
echo ""
echo "DONE. Leaderboard: $OUT/combined/leaderboard.md"
