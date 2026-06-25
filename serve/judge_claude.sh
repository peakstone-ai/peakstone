#!/usr/bin/env bash
# Judge stored solutions with Claude (or any in-session agent) as the judge.
# NO model server, NO OpenAI/Claude endpoint, NO VRAM — the grading happens in-session.
#
# It's a two-phase flow with an agent step in the middle:
#
#   1) export   dump the stored solutions (code + spec + test outcome) for the judge to read
#                 ./serve/judge_claude.sh export <results-path> [out.json] [ids-csv]
#
#   2) (Claude reads out.json, scores each solution, and writes a scores.json — format below.
#      Grounding correctness in the included test results is the whole advantage here.)
#
#   3) apply    fold those scores into a comparable leaderboard (writes judged-claude-*/)
#                 ./serve/judge_claude.sh apply <results-path> <scores.json>
#
# scores.json format:
#   {"judge": "claude",
#    "scores": [{"model": "...", "challenge": "...",
#                "correctness": 0-10, "readability": 0-10, "efficiency": 0-10,
#                "rationale": "..."}]}
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/opt/node/bin:$PATH"

cmd="${1:-help}"; shift || true
case "$cmd" in
  export)
    SRC="${1:?usage: judge_claude.sh export <results-path> [out.json] [ids-csv]}"
    OUT="${2:-/tmp/llmlab_tojudge.json}"
    IDS="${3:-}"
    if [ -n "$IDS" ]; then
      python -m peakstone.engine.export_solutions "$SRC" --ids "$IDS" --out "$OUT"
    else
      python -m peakstone.engine.export_solutions "$SRC" --out "$OUT"
    fi
    echo ""
    echo "Now have Claude read $OUT and write a scores.json, then run:"
    echo "  ./serve/judge_claude.sh apply $SRC <scores.json>"
    ;;
  apply)
    SRC="${1:?usage: judge_claude.sh apply <results-path> <scores.json>}"
    SCORES="${2:?usage: judge_claude.sh apply <results-path> <scores.json>}"
    python -m peakstone.engine.apply_judge "$SRC" "$SCORES" --judge-name claude
    ;;
  *)
    sed -n '2,20p' "$0"
    ;;
esac
