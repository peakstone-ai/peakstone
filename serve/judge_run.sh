#!/usr/bin/env bash
# Post-hoc code-quality judging. Loads ONLY the judge model, scores solutions stored in a
# prior run's results, then stops. Decouples judging from generation, so you never need two
# models in VRAM at once: run the benchmark with --no-judge, then judge afterward with this.
#
#   ./serve/judge_run.sh <results-dir-or-results.json> [judge-model]   (default judge: qwen3-coder)
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/opt/node/bin:$PATH"

SRC="${1:?usage: judge_run.sh <results-path> [judge-model]}"
JUDGE="${2:-qwen3-coder}"

port=$(python3 -c "import tomllib;print(tomllib.load(open('serve/models.toml','rb'))['$JUDGE']['port'])")
log=$(mktemp)
nohup bash serve/serve.sh "$JUDGE" > "$log" 2>&1 &
SRV=$!
echo ">>> loading judge '$JUDGE' on :$port"
ready=0
for _ in $(seq 1 180); do
  grep -q "server is listening" "$log" 2>/dev/null && { ready=1; break; }
  kill -0 "$SRV" 2>/dev/null || break
  sleep 2
done
if [ "$ready" != 1 ]; then echo "judge server failed to start:"; tail -8 "$log"; kill "$SRV" 2>/dev/null; exit 1; fi

python -m engine.runner --judge-only "$SRC" --judge-model "$JUDGE"
rc=$?
kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null
rm -f "$log"
exit $rc
