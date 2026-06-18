#!/usr/bin/env bash
# Launch llama-server for one model from serve/models.toml, exposing an
# OpenAI-compatible API on the LAN (0.0.0.0).
#
#   ./serve/serve.sh <model-name> [extra llama-server args...]
#   ./serve/serve.sh --list
#
# Reachable at  http://<this-machine-LAN-IP>:<port>/v1
set -euo pipefail
cd "$(dirname "$0")/.."

LLAMA_SERVER="${LLAMA_SERVER:-$HOME/llama.cpp/build/bin/llama-server}"

if [ "${1:-}" = "--list" ] || [ -z "${1:-}" ]; then
  echo "Available models (serve/models.toml):"
  python3 - <<'PY'
import tomllib
for n, m in tomllib.load(open("serve/models.toml", "rb")).items():
    print(f"  {n:<20} port {m['port']}  ctx {m['ctx']}")
PY
  [ -z "${1:-}" ] && exit 1 || exit 0
fi

NAME="$1"; shift || true

# pull config for this model out of the TOML registry
eval "$(python3 - "$NAME" <<'PY'
import sys, tomllib
name = sys.argv[1]
cfg = tomllib.load(open("serve/models.toml", "rb"))
if name not in cfg:
    sys.stderr.write(f"unknown model {name!r}; run serve.sh --list\n"); sys.exit(2)
m = cfg[name]
import shlex
print(f"FILE={shlex.quote(m['file'])}")
print(f"PORT={m['port']}")
print(f"CTX={m['ctx']}")
print(f"FLAGS={shlex.quote(m.get('flags',''))}")
PY
)"

if [ ! -f "$LLAMA_SERVER" ]; then
  echo "llama-server not found at $LLAMA_SERVER (set \$LLAMA_SERVER)"; exit 1
fi
if [ ! -f "$FILE" ]; then
  echo "model file not found: $FILE  (run serve/download_models.sh $NAME)"; exit 1
fi

LANIP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo ">>> serving '$NAME' on http://0.0.0.0:$PORT/v1  (LAN: http://${LANIP:-<ip>}:$PORT/v1)"
echo ">>> ctx=$CTX  file=$FILE"

# -ngl 99: offload all layers to GPU. --jinja: use the model's embedded chat template
# (enables correct tool-calling / formatting). Extra per-model sampling from FLAGS.
exec "$LLAMA_SERVER" \
  -m "$FILE" \
  --host 0.0.0.0 --port "$PORT" \
  -ngl 99 -c "$CTX" --jinja \
  $FLAGS "$@"
