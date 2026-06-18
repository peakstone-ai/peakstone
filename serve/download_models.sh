#!/usr/bin/env bash
# Download all (or one) GGUF model defined in models.toml into models/<name>/.
# Usage: ./download_models.sh [name ...]   (no args = all)
set -euo pipefail
cd "$(dirname "$0")/.."

export HF_HUB_ENABLE_HF_TRANSFER=1   # faster multi-threaded download

# name|repo|filename
# Active roster (7 contestants) + qwen3.5-4b (speculative-decoding draft for qwen3.6-27b).
ENTRIES=(
  "glm-4.7-flash|unsloth/GLM-4.7-Flash-GGUF|GLM-4.7-Flash-UD-Q4_K_XL.gguf"
  "qwen3-coder|unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF|Qwen3-Coder-30B-A3B-Instruct-UD-Q4_K_XL.gguf"
  "devstral|unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF|Devstral-Small-2-24B-Instruct-2512-UD-Q4_K_XL.gguf"
  "phi-4-mini|unsloth/Phi-4-mini-instruct-GGUF|Phi-4-mini-instruct-Q6_K.gguf"
  "qwen3.6-27b|unsloth/Qwen3.6-27B-GGUF|Qwen3.6-27B-UD-Q4_K_XL.gguf"
  "qwen3.6-35b-a3b|unsloth/Qwen3.6-35B-A3B-GGUF|Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf"
  "qwen3.5-9b|unsloth/Qwen3.5-9B-GGUF|Qwen3.5-9B-UD-Q6_K_XL.gguf"
  "qwen3.5-4b|unsloth/Qwen3.5-4B-GGUF|Qwen3.5-4B-Q4_K_M.gguf"
  # VibeThinker-3B (Weibo AI): 3B dense reasoner on Qwen2.5-Coder-3B, competition math/coding.
  # Only a Q8_0 community GGUF exists (3.3GB; trivial for the 4090). NOT tool-call/agentic trained.
  "vibethinker-3b|bms22/VibeThinker-3B-Q8_0-GGUF|vibethinker-3b-q8_0.gguf"
  # --- tested & dropped (files deleted); uncomment any line to reproduce ---
  # "qwen2.5-coder-32b|bartowski/Qwen2.5-Coder-32B-Instruct-GGUF|Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf"
  # "qwen2.5-coder-14b|bartowski/Qwen2.5-Coder-14B-Instruct-GGUF|Qwen2.5-Coder-14B-Instruct-Q6_K.gguf"
  # "qwen2.5-coder-7b|bartowski/Qwen2.5-Coder-7B-Instruct-GGUF|Qwen2.5-Coder-7B-Instruct-Q6_K.gguf"
  # "qwen3-8b|unsloth/Qwen3-8B-GGUF|Qwen3-8B-UD-Q6_K_XL.gguf"
  # "qwen3.5-9b-coder|mradermacher/Qwen3.5-9B-Coder-GGUF|Qwen3.5-9B-Coder.Q6_K.gguf"
  # "qwen3.5-9b-py-coder|Jackrong/Qwen3.5-9B-Python-Coder-GGUF|Qwen3.5-9B.Q6_K.gguf"
)

want=("$@")
match() { [ ${#want[@]} -eq 0 ] && return 0; for w in "${want[@]}"; do [ "$w" = "$1" ] && return 0; done; return 1; }

for e in "${ENTRIES[@]}"; do
  IFS='|' read -r name repo file <<<"$e"
  match "$name" || continue
  echo ">>> $name : $repo / $file"
  hf download "$repo" "$file" --local-dir "models/$name"
done
echo "Done. Files:"; ls -lh models/*/*.gguf 2>/dev/null || true
