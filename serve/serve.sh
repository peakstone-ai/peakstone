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

# Prefer a llama-server on PATH (e.g. Homebrew's Metal build on macOS: `brew install llama.cpp`),
# then fall back to a locally-built tree. Override with $LLAMA_SERVER.
LLAMA_SERVER="${LLAMA_SERVER:-$(command -v llama-server || echo "$HOME/llama.cpp/build/bin/llama-server")}"

if [ "${1:-}" = "--list" ] || [ -z "${1:-}" ]; then
  echo "Available models (serve/models.toml):"
  python3 - <<'PY'
import tomllib
for n, m in tomllib.load(open("serve/models.toml", "rb")).items():
    print(f"  {n:<20} port {m['port']}  ctx {m.get('ctx', 'auto')}")
PY
  [ -z "${1:-}" ] && exit 1 || exit 0
fi

NAME="$1"; shift || true

# pull config for this model out of the TOML registry
eval "$(python3 - "$NAME" <<'PY'
import os, sys, tomllib
name = sys.argv[1]
cfg = tomllib.load(open("serve/models.toml", "rb"))
if name not in cfg:
    sys.stderr.write(f"unknown model {name!r}; run serve.sh --list\n"); sys.exit(2)
m = cfg[name]
import shlex, re
flags = m.get('flags', '')
rb = os.environ.get('PEAKSTONE_REASONING_BUDGET')   # override thinking: 0=off, -1=full, N=token cap
if rb not in (None, ''):
    flags = re.sub(r'--reasoning-budget\s+\S+', '', flags).strip()
    flags = (flags + f' --reasoning-budget {rb}').strip()
print(f"FILE={shlex.quote(m['file'])}")
print(f"PORT={m['port']}")
# ctx precedence: PEAKSTONE_CTX env > configured ctx in models.toml > rough VRAM-fit estimate
# (engine/vram.py) > DEFAULT_CTX. The estimate errs small and prints a warning when the fit is tight.
ctx = os.environ.get('PEAKSTONE_CTX') or m.get('ctx')
if not ctx:
    try:
        from peakstone.engine.serving import resolve_ctx, ServeModel, DEFAULT_CTX
        choice = resolve_ctx(ServeModel(name, m.get('port'), m.get('ctx'), m.get('file'),
                                        m.get('flags', ''), m.get('mmproj')))
        ctx = choice.ctx or DEFAULT_CTX
        if choice.warning:
            sys.stderr.write(f">>> ctx: {choice.warning}\n")
        sys.stderr.write(f">>> ctx auto={ctx} ({choice.source})\n")
    except Exception as e:  # noqa: BLE001
        ctx = 32768
        sys.stderr.write(f">>> ctx auto-estimate failed ({e}); using {ctx}\n")
print(f"CTX={ctx}")
print(f"FLAGS={shlex.quote(flags)}")
print(f"MMPROJ={shlex.quote(m.get('mmproj', ''))}")   # vision projector GGUF; empty = text-only
PY
)"

if [ ! -f "$LLAMA_SERVER" ]; then
  echo "llama-server not found at $LLAMA_SERVER (set \$LLAMA_SERVER)"; exit 1
fi
if [ ! -f "$FILE" ]; then
  echo "model file not found: $FILE  (run serve/download_models.sh $NAME)"; exit 1
fi

# Vision projector (multimodal). Present => pass --mmproj so the model accepts image input; absent in
# the registry => text-only (no flag). A declared-but-missing projector is a hard error (same as the
# model file) so vision doesn't silently degrade to text.
MMPROJ_ARG=()
if [ -n "${MMPROJ:-}" ]; then
  if [ ! -f "$MMPROJ" ]; then
    echo "vision projector not found: $MMPROJ  (run serve/download_models.sh $NAME)"; exit 1
  fi
  MMPROJ_ARG=(--mmproj "$MMPROJ")
  echo ">>> multimodal: --mmproj $MMPROJ"
fi

# LAN IP: `hostname -I` is Linux-only; macOS falls back to the primary interface address.
LANIP=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -z "${LANIP:-}" ] && LANIP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)
echo ">>> serving '$NAME' on http://0.0.0.0:$PORT/v1  (LAN: http://${LANIP:-<ip>}:$PORT/v1)"
echo ">>> ctx=$CTX  file=$FILE"

# -ngl 99: offload all layers to GPU. --jinja: use the model's embedded chat template
# (enables correct tool-calling / formatting). Extra per-model sampling from FLAGS.
exec "$LLAMA_SERVER" \
  -m "$FILE" \
  "${MMPROJ_ARG[@]}" \
  --host 0.0.0.0 --port "$PORT" \
  -ngl 99 -c "$CTX" --jinja \
  $FLAGS "$@"
