# Peakstone schema — the reproducibility contract

This directory holds the **versioned contract** between the Peakstone engine (which produces results)
and the API (which ingests them). Everything else is built around it.

- **`result-bundle.schema.json`** — JSON Schema (draft 2020-12) for a **result bundle**: one model
  configuration ("run") scored on a suite, with everything needed to independently reproduce it.
- **`taxonomy.json`** — the controlled vocabularies (capability categories, verification methods,
  calibrated difficulty tiers) referenced by the schema.

## What a bundle is

A **run** = a fully-specified config — `model artifact + quant + sampling + serve/offload flags +
engine + environment` — scored on a suite. Runs are **never collapsed**: a Q4@24GB run and a
Q8@48GB run of the same model are distinct bundles. The leaderboard is a faceted query over runs
(filter by VRAM, quant, context, tok/s, hardware, trust tier).

## Reproducibility & trust

- **Content addressing.** `bundle_hash = sha256(canonical_json)` with `submitter.signature` omitted.
  The submitter signs that hash (ed25519); the server recomputes and verifies both.
- **Challenge pinning.** Each result carries `challenge_hash` (sha256 of spec + tests + meta) and the
  bundle carries `suite.content_hash`, so a score always names the exact challenge/suite version.
- **Trust tiers.** `verification = deterministic-tests` results are independently re-runnable and can
  be promoted to **community-verified** (reproduced by ≥N submitters) or **runner-verified**.
  `llm-judge` / `goal-state-env` / `human` results are "soft" (judge identity recorded).

## Versioning

The schema is versioned via `bundle_version` (and `$id` path `…/v1.json`). Breaking changes bump the
major version; the API accepts a documented range. Keep `taxonomy.json` in lockstep
(`taxonomy_version`). Adding a new capability category or verification method is a minor, additive
change.

## Validating a bundle

```bash
# any JSON Schema validator, e.g. python jsonschema:
python -c "import json,jsonschema; jsonschema.validate(json.load(open('bundle.json')), json.load(open('schema/result-bundle.schema.json')))"
```
The engine's `produce_bundle()` validates against this schema before writing.
