#!/usr/bin/env bash
# With llama-swap running (serve/llama-swap.service on :8080) you normally DON'T need this —
# just send a request with the model you want and llama-swap loads/swaps it automatically.
# This is a convenience to pre-warm a model (so the agent's first request is instant) or to
# check what's loaded.
#
#   ./serve/use.sh                 # list configured models + what's currently loaded
#   ./serve/use.sh qwen3-coder     # pre-load (warm up) that model now
#   ./serve/use.sh glm-planner     # swap to the planner
set -uo pipefail
HOST="${LLAMA_SWAP:-http://localhost:8080}"
curl() { command env -u LD_LIBRARY_PATH curl "$@"; }   # avoid conda libcurl noise

if [ -z "${1:-}" ]; then
  echo "configured models:"
  curl -s "$HOST/v1/models" | python3 -c "import sys,json;[print(' ',m['id']) for m in json.load(sys.stdin)['data']]"
  echo "currently loaded:"
  curl -s "$HOST/running" | python3 -c "import sys,json;r=json.load(sys.stdin)['running'];print('  (none)' if not r else '\n'.join('  %s [%s]'%(m['model'],m['state']) for m in r))"
  exit 0
fi

echo "warming up '$1' (llama-swap will load/swap it)..."
curl -s "$HOST/v1/chat/completions" -H 'Content-Type: application/json' \
  -d "{\"model\":\"$1\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":1}" >/dev/null \
  && echo "ready: $1 on $HOST/v1  (model=\"$1\")" \
  || echo "request failed — is llama-swap running?  (sudo systemctl status llama-swap)"
