# Releasing Peakstone

The PyPI package is the **client** (`peakstone` = `peakstone.engine` + `peakstone.dashboard`). The
server (`peakstone.api`) is never published to PyPI — it deploys from this repo via Docker
(`infra/`, see the README). Releases are tag-driven and use **PyPI Trusted Publishing** (OIDC), so
there are no API tokens stored anywhere.

## One-time setup (per maintainer org)

1. **Reserve the name** and configure a *pending* trusted publisher on PyPI — do this once before
   the first publish, while the project doesn't exist yet:
   - PyPI → *Your projects* → *Publishing* → *Add a pending publisher*:
     - PyPI project name: `peakstone`
     - Owner / repository: `peakstone-ai/peakstone`
     - Workflow filename: `release.yml`
     - Environment: `pypi`
   - Repeat on **test.pypi.org** with environment `testpypi` for dry-runs.
2. **Create the GitHub environments** `pypi` and `testpypi` (repo → Settings → Environments). Add
   required reviewers on `pypi` if you want a manual approval gate before a real publish.

That's it — no secrets. The workflow authenticates to PyPI with a short-lived OIDC token minted by
GitHub Actions.

## Cut a release

```bash
./scripts/cut_release.sh 0.2.0        # bumps pyproject, commits "release: v0.2.0", tags v0.2.0
git push origin main && git push origin v0.2.0
```

Pushing the tag runs `.github/workflows/release.yml`, which:
1. builds the sdist + wheel and runs `twine check`,
2. **verifies the tag matches the `pyproject.toml` version** (fails the release otherwise),
3. publishes to PyPI via the trusted publisher, and
4. creates a GitHub Release with the artifacts + auto-generated notes.

## Dry-run to TestPyPI first

From the **Actions** tab → *Release* → *Run workflow* → target `testpypi`. Then verify the install:

```bash
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ "peakstone[dashboard]"
peakstone --help
```

(The `--extra-index-url` is needed because TestPyPI doesn't mirror dependencies like `textual`.)

## Versioning

`version` in `pyproject.toml` is the single source of truth; `scripts/cut_release.sh` bumps it and
tags `v<version>` so the two can never drift (the release workflow enforces it). Use PEP 440 —
`0.2.0`, or `0.2.0rc1` for a pre-release.
