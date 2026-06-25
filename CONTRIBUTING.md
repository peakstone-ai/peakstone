# Contributing

Thanks for helping build an open, reproducible benchmark for open-model capabilities!

## Licensing of contributions

- **Code and challenges** (engine, API, web, and challenge `spec.md` / `tests/` / `reference/`) are
  contributed under the **Apache License 2.0** ([LICENSE](./LICENSE)).
- **Submitted result data** (scores + metadata in result bundles) is published under
  **CC-BY-4.0** ([DATA-LICENSE.md](./DATA-LICENSE.md)).

By contributing, you certify the **Developer Certificate of Origin** ([DCO](./DCO)) — i.e. that you
wrote the contribution or have the right to submit it under these licenses. We use the DCO instead of
a CLA, so there's nothing to sign: just **sign off your commits**.

```bash
git commit -s -m "your message"   # appends: Signed-off-by: Your Name <you@example.com>
```

Use a real name and a reachable email. (`git config user.name` / `user.email` set the values.)

## Contributing a challenge

A challenge enters the open **corpus**; an admin later **canonizes** select challenges into a
versioned **suite** (official leaderboards are per-suite). To add one:

1. Create `challenges/<lang-or-category>/NN-slug/` with `meta.toml`, `spec.md`, `tests/`, and a
   `reference/` solution (see existing challenges and `engine/challenges.py` for the schema).
2. Declare its **capability category**, **verification method** (`deterministic-tests` /
   `llm-judge` / `goal-state-env`), and a **seed difficulty** — the platform calibrates the real
   difficulty tier (T0–T4) from submission data over time.
3. Your `reference/` solution **must pass its own `tests/` in the sandbox** (`python -m peakstone.engine.runner
   --reference --models reference --ids <id>`). Reference-verifiable challenges are what make the
   leaderboard trustworthy.
4. Keep it deterministic where possible. Untrusted code runs sandboxed; resource-heavy or unsafe
   challenges will be rejected in review.

## Submitting results

Run the engine against your own served model and submit the signed result bundle (see the platform's
"How to submit" guide). Every bundle must embed the full model + environment + challenge metadata so
the run is independently reproducible.

## Code style

Match the surrounding code (the engine is stdlib-first Python). Keep changes focused; add or update
tests where it makes sense.
