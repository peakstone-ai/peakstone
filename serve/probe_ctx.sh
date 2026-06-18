#!/usr/bin/env bash
# Probe the max context that fits entirely in VRAM for a model (q4 KV on GPU, flash-attn).
# Requires the GPU to be FREE.
#   ./serve/probe_ctx.sh <model-name> [ctx ...]
# Defaults to a ladder if no ctx values are given.
set -uo pipefail
cd "$(dirname "$0")/.."
MODEL_NAME="${1:?usage: probe_ctx.sh <model-name> [ctx ...]}"; shift || true
CTXS=("$@"); [ ${#CTXS[@]} -eq 0 ] && CTXS=(65536 131072 196608 262144)
LS="${LLAMA_SERVER:-$HOME/llama.cpp/build/bin/llama-server}"
FILE=$(python3 -c "import tomllib;print(tomllib.load(open('serve/models.toml','rb'))['$MODEL_NAME']['file'])")
PORT=8090

echo "### $MODEL_NAME  (q4 KV on GPU)"
printf "%-10s %8s %10s\n" "ctx" "loaded?" "VRAM(GB)"
for ctx in "${CTXS[@]}"; do
  log=$(mktemp)
  $LS -m "$FILE" --host 127.0.0.1 --port "$PORT" -ngl 99 --jinja -c "$ctx" \
      -fa on --cache-type-k q4_0 --cache-type-v q4_0 > "$log" 2>&1 &
  SRV=$!; ok=0
  for _ in $(seq 1 120); do
    grep -q "server is listening" "$log" 2>/dev/null && { ok=1; break; }
    kill -0 "$SRV" 2>/dev/null || break
    sleep 2
  done
  if [ "$ok" = 1 ]; then
    peak=0
    for _ in 1 2 3; do u=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits|head -1); [ "${u:-0}" -gt "$peak" ] && peak=$u; sleep 1; done
    printf "%-10s %8s %10s\n" "$ctx" "YES" "$(python3 -c "print(round($peak/1024,1))")"
  else
    printf "%-10s %8s %10s\n" "$ctx" "no(OOM)" "-"
  fi
  kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null; sleep 3; rm -f "$log"
done
echo "PROBE-DONE-$MODEL_NAME"
