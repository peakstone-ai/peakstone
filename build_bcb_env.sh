#!/usr/bin/env bash
# Build the pinned BigCodeBench eval environment used by the harness.
#
# BigCodeBench's reference (and model) solutions were authored against an older library
# stack (pandas<3 still has DataFrame.applymap, numpy<2, etc.) and its official image runs
# Python 3.10. Those pins have no wheels on modern Python, so we isolate them in a dedicated
# conda env instead of the harness's base env. peakstone/engine/config.toml's [run.envs] maps
# the `bigcodebench` suite to this env's interpreter; sandbox.py also pins TZ=UTC for it.
#
# Usage:  bash build_bcb_env.sh
# Then:   python -m peakstone.engine.runner --reference --models reference \
#             --ids $(ls -d challenges/bigcodebench/bcb-*/ | sed -E 's#.*/(bcb-[0-9]+)-.*#\1#' | paste -sd,)
set -uo pipefail

ENV="${PEAKSTONE_BCB_ENV:-peakstone-bcb}"
CONDA="${CONDA_EXE:-$HOME/miniconda3/bin/conda}"
REQ_URL="https://raw.githubusercontent.com/bigcode-project/bigcodebench/main/Requirements/requirements-eval.txt"
ENV_PY="$("$CONDA" info --base)/envs/$ENV/bin/python"
ENV_PIP="$("$CONDA" info --base)/envs/$ENV/bin/pip"

echo "[bcb-env] creating conda env '$ENV' (python 3.10)"
"$CONDA" create -y -n "$ENV" python=3.10

echo "[bcb-env] installing pytest (the runner invokes 'python -m pytest') + pinned requirements"
"$ENV_PIP" install --upgrade pip wheel setuptools
"$ENV_PIP" install pytest

REQ_FILE="$(mktemp)"
curl -fsSL "$REQ_URL" -o "$REQ_FILE"
if ! "$ENV_PIP" install --prefer-binary -r "$REQ_FILE"; then
  echo "[bcb-env] bulk install failed; retrying per-package so one bad pin doesn't abort the rest"
  while read -r line; do
    line="${line%%#*}"; line="$(echo "$line" | xargs)"
    [ -z "$line" ] && continue
    "$ENV_PIP" install --prefer-binary "$line" || echo "[bcb-env] FAILED: $line"
  done < "$REQ_FILE"
fi
rm -f "$REQ_FILE"

echo "[bcb-env] done. Key versions:"
"$ENV_PY" - <<'PY'
for m in ("numpy","pandas","scipy","sklearn","matplotlib","pytest"):
    try:
        print(f"  {m:12}", __import__(m).__version__)
    except Exception as e:
        print(f"  {m:12} MISSING ({type(e).__name__})")
PY
echo "[bcb-env] interpreter: $ENV_PY"
echo "[bcb-env] ensure peakstone/engine/config.toml [run.envs].bigcodebench points here."
