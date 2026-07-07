#!/usr/bin/env bash
# R8 re-seed: grade the official board's generation-only seed runs (judge-LAST) and submit the
# judged bundles. Run on the SEED MACHINE (the bundle is re-signed with this box's key — it must
# be the trusted operator key) with `peakstone serve` up: the judge rides the gateway, which
# swaps the configured [judge] model (qwen3.6-35b-a3b) in once and grades the whole run.
#
#   ./serve/reseed_judge.sh results/job-aaaa results/job-bbbb …
#
# Each judged bundle keeps the ORIGINAL run's identity (suite, budget — now recorded correctly in
# sampling) and adds the judge model + params to every judged row. It submits as a NEW bundle;
# after all models are re-seeded, retire the old gen-only submissions server-side.
# NOTE: pre-fix runs recorded no selected_ids, so these re-emitted bundles still hash the
# executed set — suite_hash_match stays a FLAG until the next full fresh seed run.
set -euo pipefail
cd "$(dirname "$0")/.."

GATEWAY="${PEAKSTONE_GATEWAY_URL:-http://127.0.0.1:12434}"
[ $# -ge 1 ] || { echo "usage: $0 <gen-run-dir>..." >&2; exit 2; }

for run in "$@"; do
  [ -f "$run/results.json" ] || { echo "!! $run has no results.json — skipping" >&2; continue; }
  out="$run/judged-$(date +%Y%m%d-%H%M%S)"
  echo "== judging $run -> $out"
  python -m peakstone.engine.runner --judge-only "$run" --bundle --out "$out" --gateway "$GATEWAY"
  echo "== submitting $out/bundle.json"
  python - "$out/bundle.json" <<'PY'
import json, os, sys
from peakstone.dashboard.client import API_DEFAULT, submit_bundle
api = os.environ.get("PEAKSTONE_API_URL", API_DEFAULT)
status, detail = submit_bundle(api, json.loads(open(sys.argv[1]).read()))
print(f"   -> {status} {detail}")
sys.exit(0 if status in (201, 409) else 1)
PY
done
echo "== done. Remember: retire the superseded gen-only submissions on the server."
