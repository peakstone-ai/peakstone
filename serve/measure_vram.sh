#!/usr/bin/env bash
# Measure serving VRAM (MiB) for each model: load it, warm the compute buffers with one
# request, sample nvidia-smi peak, then stop. Writes a JSON map (model -> MiB) and a table.
# Only one model is resident at a time.
#
#   ./serve/measure_vram.sh [out.json] [model ...]
set -uo pipefail
cd "$(dirname "$0")/.."

OUTJSON="${1:-serve/vram.json}"; shift || true
MODELS=("$@")
[ ${#MODELS[@]} -eq 0 ] && MODELS=(glm-4.7-flash qwen3-coder devstral qwen2.5-coder-32b)

TMP=$(mktemp)
printf "%-22s %s\n" "MODEL" "VRAM (MiB, peak)"
for m in "${MODELS[@]}"; do
  port=$(python3 -c "import tomllib;print(tomllib.load(open('serve/models.toml','rb'))['$m']['port'])")
  log=$(mktemp)
  nohup bash serve/serve.sh "$m" > "$log" 2>&1 &
  SRV=$!
  ready=0
  for _ in $(seq 1 120); do
    grep -q "server is listening" "$log" 2>/dev/null && { ready=1; break; }
    kill -0 "$SRV" 2>/dev/null || break
    sleep 2
  done
  if [ "$ready" = 1 ]; then
    curl -s "http://127.0.0.1:$port/v1/chat/completions" -H 'Content-Type: application/json' \
      -d '{"messages":[{"role":"user","content":"hi"}],"max_tokens":8}' >/dev/null 2>&1
    peak=0
    for _ in 1 2 3; do
      u=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
      [ "${u:-0}" -gt "$peak" ] && peak=$u
      sleep 1
    done
  else
    peak=0; echo "  (!! $m never became ready)"
  fi
  printf "%-22s %s\n" "$m" "$peak"
  echo "$m $peak" >> "$TMP"
  kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null; sleep 3
  rm -f "$log"
done

python3 - "$TMP" "$OUTJSON" <<'PY'
import json, sys
d = {}
for line in open(sys.argv[1]):
    name, mib = line.split()
    d[name] = int(mib)
json.dump(d, open(sys.argv[2], "w"), indent=2)
print("wrote", sys.argv[2], d)
PY
rm -f "$TMP"
