#!/usr/bin/env bash
# Cut a Peakstone release: bump the version, commit, tag, and push.
# The pushed tag triggers .github/workflows/release.yml, which builds and publishes to PyPI.
#
#   ./scripts/cut_release.sh 0.2.0
#
set -euo pipefail
cd "$(dirname "$0")/.."

new="${1:-}"
if [[ -z "$new" ]]; then echo "usage: $0 <version>   e.g. $0 0.2.0" >&2; exit 1; fi
if ! [[ "$new" =~ ^[0-9]+\.[0-9]+\.[0-9]+([abrc.][0-9a-z.]+)?$ ]]; then
  echo "!! '$new' is not a PEP 440 version (e.g. 0.2.0, 0.2.0rc1)" >&2; exit 1
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo "!! working tree not clean — commit or stash first" >&2; exit 1
fi

cur=$(python -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
echo ">> $cur -> $new"

# bump both version strings in lockstep: pyproject's [project].version (the source of truth for the
# built dist) and peakstone/__init__.py's __version__ (the fallback used when running from a source
# checkout / the COPY'd API Docker image, where dist metadata is absent).
python - "$new" <<'PY'
import re, sys
new = sys.argv[1]
edits = [
    ("pyproject.toml", r'(?m)^(version\s*=\s*)"[^"]+"'),
    ("peakstone/__init__.py", r'(?m)^(__version__\s*=\s*)"[^"]+"'),
]
for p, pat in edits:
    s = open(p).read()
    s, n = re.subn(pat, rf'\1"{new}"', s, count=1)
    assert n == 1, f"could not find the version line in {p}"
    open(p, "w").write(s)
PY

git add pyproject.toml peakstone/__init__.py
git commit -q -m "release: v$new"
git tag -a "v$new" -m "v$new"
echo ">> committed + tagged v$new. Push to publish:"
echo "     git push origin $(git rev-parse --abbrev-ref HEAD) && git push origin v$new"
