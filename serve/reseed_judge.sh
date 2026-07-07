#!/usr/bin/env bash
# R8 re-seed: grade the official board's generation-only seed runs (judge-LAST), re-stamped to the
# CURRENT standard level, and submit the judged bundles. Run on the SEED MACHINE (bundles are
# re-signed with this box's key — it must be the trusted operator key) with `peakstone serve` up:
# the judge rides the gateway, which swaps the configured [judge] model in once per pass.
#
#   ./serve/reseed_judge.sh                    # auto-discover: latest standard run per model
#   ./serve/reseed_judge.sh qwen3-coder …      # explicit roster
#   DRY_RUN=1 ./serve/reseed_judge.sh          # show what would run, do nothing
#
# Per model: latest level-standard results.json + latest agentic env-results.json are merged
# (--also, append-only — --overlay is retired), filtered + re-stamped to level standard@current
# (--level, which also records selected_ids → the model-independent suite hash), judged, and the
# signed bundle (judge model + params recorded) is submitted. Afterwards: retire the superseded
# gen-only submissions server-side.
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/opt/node/bin:$PATH"

GATEWAY="${PEAKSTONE_GATEWAY_URL:-http://127.0.0.1:12434}"
STAMP=$(date +%Y%m%d-%H%M%S)
OUT="results/reseed-$STAMP"
mkdir -p "$OUT"

curl -fsS -m 5 "$GATEWAY/health" >/dev/null || { echo "!! gateway not reachable at $GATEWAY — run \`peakstone serve --detach\` first" >&2; exit 1; }

# model<TAB>standard-results.json<TAB>env-results.json(or empty) — newest per model, partials (<100 rows) skipped
mapfile -t PLAN < <(python3 - "$@" <<'PY'
import glob, json, os, sys
roster = set(sys.argv[1:])
std, env = {}, {}
for p in glob.glob("results/**/results.json", recursive=True):
    if "/judged" in p or "/reseed-" in p:
        continue
    try:
        d = json.load(open(p)); meta = d.get("meta", {})
    except Exception:
        continue
    if meta.get("suite_id") != "level-standard" or len(d.get("results", [])) < 100:
        continue
    for m in (meta.get("models") or []):
        if std.get(m) is None or os.path.getmtime(p) > os.path.getmtime(std[m]):
            std[m] = p
for p in glob.glob("results/agentic-*/*/env-results.json"):
    m = p.split("/")[-2]
    if env.get(m) is None or os.path.getmtime(p) > os.path.getmtime(env[m]):
        env[m] = p
for m in sorted(std):
    if roster and m not in roster:
        continue
    print(f"{m}\t{std[m]}\t{env.get(m, '')}")
PY
)
[ ${#PLAN[@]} -ge 1 ] || { echo "!! no standard runs found (roster: $*)" >&2; exit 1; }

echo "Re-seed plan ($OUT):"
printf '  %s\n' "${PLAN[@]}"
[ "${DRY_RUN:-}" = 1 ] && exit 0

fail=0
for line in "${PLAN[@]}"; do
  IFS=$'\t' read -r model stdrun envres <<<"$line"
  outdir="$OUT/$model"
  echo; echo "=== [$model] judging $stdrun ${envres:+(+ $envres)}"
  also=(); [ -n "$envres" ] && also=(--also "$envres")
  if ! python -u -m peakstone.engine.runner --judge-only "$stdrun" --bundle --level standard \
        "${also[@]}" --out "$outdir" --gateway "$GATEWAY" > "$OUT/$model.log" 2>&1; then
    echo "!! [$model] judge pass failed — see $OUT/$model.log"; fail=1; continue
  fi
  tail -3 "$OUT/$model.log" | sed 's/^/    /'
  echo "=== [$model] submitting $outdir/bundle.json"
  python3 - "$outdir/bundle.json" <<'PY' || { echo "!! [$model] submit failed"; fail=1; }
import json, os, sys
from peakstone.dashboard.client import API_DEFAULT, submit_bundle
api = os.environ.get("PEAKSTONE_API_URL", API_DEFAULT)
status, detail = submit_bundle(api, json.load(open(sys.argv[1])))
print(f"    -> {status} {detail[:140]}")
sys.exit(0 if status in (201, 409) else 1)
PY
done
echo; echo "== done (failures: $fail). Remember: retire the superseded gen-only submissions server-side."
exit "$fail"
