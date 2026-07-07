"""Reproduce a leaderboard run on local hardware: ensure the model is present (download if not) →
serve it → bench it → compare your tok/s to the published number.

The external steps (serve / health / bench / stop) are injectable so the orchestration is testable
without a GPU; the real path uses serve/serve.sh + peakstone.engine.runner on a host with llama-server.

The serve/health/stop primitives live in peakstone.engine.serving (so the model-swapping gateway can
reuse them without importing this Textual/HF dashboard layer); they're re-exported here for the
dashboard's existing call sites (reproduce.serve, reproduce.stop, reproduce._reasoning_budget, …).
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..engine import serving
from ..engine.serving import (  # re-exported: keep reproduce.* call sites + tests working
    _kill,
    reasoning_budget as _reasoning_budget,
    serve,
    serve_log_path,
    serve_log_tail,
    stop,
    wait_healthy,
)
from . import models, preflight
from .models import REPO

SERVE_SH = REPO / "serve" / "serve.sh"


@dataclass
class ReproduceResult:
    model: str
    ok: bool
    your_tps: float | None = None
    published_tps: float | None = None
    code_score: float | None = None
    passed: int = 0
    total: int = 0
    note: str = ""
    bundle: dict | None = None    # the signed bundle, for one-key submission to the leaderboard
    download: bool = False         # this job only fetched weights (no serve/bench)

    @property
    def tps_ratio(self) -> float | None:
        if self.your_tps and self.published_tps:
            return round(self.your_tps / self.published_tps, 2)
        return None


def bench(name: str, ids: list[str] | None = None, *, level: str | None = None,
          out_dir: Path | None = None, log=lambda s: None, popen=subprocess.Popen, on_proc=None,
          ctx: int | None = None, reasoning=None, max_tokens: int | None = None) -> dict | None:
    """Run the engine over the selection, streaming the runner's per-challenge output line-by-line to
    `log` so the dashboard can show progress live (each challenge solving + its ✓/✗ result). The TUI
    serves ONE model at a time (no --gateway), so judging is a separate judge-last pass."""
    out = Path(out_dir) if out_dir else (REPO / "results" / f"repro-{name}")
    out.mkdir(parents=True, exist_ok=True)
    cmd, timeout = serving.build_runner_cmd(name, ids, level=level, out=out, max_tokens=max_tokens)
    env_extra = {}
    if ctx:
        env_extra["PEAKSTONE_CTX"] = str(ctx)   # the runner's bundle records this as the served context
    rb = _reasoning_budget(reasoning)           # so the runner's bundle records the EFFECTIVE serve flags
    if rb is not None:
        env_extra["PEAKSTONE_REASONING_BUDGET"] = rb
    return serving.stream_runner(cmd, out=out, timeout=timeout, env_extra=env_extra, log=log,
                                 popen=popen, on_proc=on_proc)


def fetch(name: str, *, on_proc=None, on_dl_progress=None, cancel=None, log=lambda s: None,
          _download=models.download) -> ReproduceResult:
    """Download a model's weights as a standalone queued job — no serve/bench. Used by the quant
    menu so a download is just another job on the queue (with the same progress bar / cancel)."""
    entry = models.load_registry().get(name)
    if entry is None:
        return ReproduceResult(name, False, download=True, note=f"{name} not in serve/models.toml — add it first")
    if entry.present:
        return ReproduceResult(name, True, download=True, note="already downloaded")
    log(f"downloading {name}…")
    ok = _download(entry, log, progress=on_dl_progress, on_proc=on_proc, cancel=cancel)
    return ReproduceResult(name, bool(ok), download=True, note="downloaded" if ok else "download failed")


def reproduce(name: str, *, challenge_ids: list[str] | None = None, level: str | None = None,
              published_tps: float | None = None, on_proc=None, on_dl_progress=None, cancel=None,
              ctx: int | None = None, reasoning=None, max_tokens: int | None = None,
              log=lambda s: None, _serve=serve, _wait=wait_healthy, _bench=bench, _stop=stop,
              _download=models.download) -> ReproduceResult:
    entry = models.load_registry().get(name)
    if entry is None:
        return ReproduceResult(name, False, note=f"{name} not in serve/models.toml — add it first")
    if not entry.present:
        log("model file missing; downloading…")
        if not _download(entry, log, progress=on_dl_progress, on_proc=on_proc, cancel=cancel):
            return ReproduceResult(name, False, published_tps=published_tps, note="download failed")
    log(f"serving {name} on :{entry.port}{f' (ctx {ctx})' if ctx else ''} …")
    proc = _serve(name, ctx=ctx, reasoning=reasoning)
    if on_proc:
        on_proc(proc)          # register so the run can be cancelled (killed) mid-flight
    try:
        if not _wait(entry.port, proc=proc):
            died = proc is not None and getattr(proc, "poll", lambda: None)() is not None
            if died:
                tail = serve_log_tail(name)
                hint = "CUDA out of memory" if "out of memory" in tail.lower() else \
                       "is llama-server installed and the GPU free?"
                log(f"serve failed:\n{tail}" if tail else "serve process exited")
                note = f"llama-server for {name} exited before serving — {hint}"
            else:
                note = "model never became healthy in time (is llama-server installed / GPU free?)"
            return ReproduceResult(name, False, published_tps=published_tps, note=note)
        log(f"benchmarking ({'level ' + level if level else 'selection'}) …")
        bundle = _bench(name, challenge_ids, level=level, log=log, on_proc=on_proc, ctx=ctx,
                        reasoning=reasoning, max_tokens=max_tokens)
    finally:
        _stop(proc)
        log("stopped serving")
    if not bundle:
        return ReproduceResult(name, False, published_tps=published_tps, note="benchmark produced no bundle")

    results = bundle.get("results", [])
    tps = [r["tok_per_s"] for r in results if isinstance(r.get("tok_per_s"), (int, float))]
    codes = [r["score"]["final"] for r in results
             if r.get("verification") == "deterministic-tests" and isinstance(r.get("score"), dict)]
    passed = sum(r.get("score", {}).get("passed", 0) for r in results if isinstance(r.get("score"), dict))
    total = sum(r.get("score", {}).get("total", 0) for r in results if isinstance(r.get("score"), dict))
    return ReproduceResult(
        name, True,
        your_tps=round(sum(tps) / len(tps), 1) if tps else None,
        published_tps=published_tps,
        code_score=round(sum(codes) / len(codes), 3) if codes else None,
        passed=passed, total=total, note="done", bundle=bundle)


# --------------------------------------------------------------------------- #
# `peakstone reproduce <run-hash>` — verify a published run on your own hardware
# --------------------------------------------------------------------------- #
def _resolve_entry(plan, *, log=print, _quants=None):
    """The local registry entry matching the bundle's EXACT artifact: same hf_repo + same quant.
    Same-quant only — reproducing q4 with q5 is a different measurement, so a quant mismatch is a
    refusal, not a fudge. If the family is known but the quant isn't registered yet, register it
    from the repo's quant listing (the file then downloads through the normal path)."""
    reg = models.load_registry()
    for e in reg.values():
        if e.repo == plan.hf_repo and e.quant == plan.artifact:
            return e
    # not registered: look the quant up in the HF repo and register it under the family
    quants = (_quants or models.available_quants)(plan.hf_repo) if plan.hf_repo else []
    q = next((q for q in quants if q.get("quant") == plan.artifact), None)
    if q:
        log(f"registering {plan.family} {plan.artifact} from {plan.hf_repo} …")
        return models.register_quant(plan.family, plan.hf_repo, q["file"], plan.artifact)
    return None


def _reasoning_arg(budget: int | None):
    """Map the bundle's served --reasoning-budget back to the serve() reasoning argument."""
    if budget is None:
        return None
    return "off" if budget == 0 else "on" if budget < 0 else budget


def reproduce_main(argv=None, *, _fetch=None, _serve=serve, _wait=wait_healthy, _bench=bench,
                   _stop=stop, _download=None, _resolve=None, log=print) -> int:
    """Reproduce a published run and verify it: fetch the signed bundle, re-run its DETERMINISTIC
    result vector on this machine (exact challenge content, same artifact/quant, same budget,
    judge off — judge-graded rows aren't part of the vector), and compare.

    Exit 0 on MATCH (and COMPATIBLE — informative, never verifying), 1 on MISMATCH, 2 on any
    refusal (bad bundle, corpus drift, wrong quant, model unavailable)."""
    import argparse
    import json

    from ..engine import bundle as eng_bundle
    from ..engine import paths, repro
    from . import client, history

    ap = argparse.ArgumentParser(
        prog="peakstone reproduce",
        description="re-run a published run's deterministic results on your hardware and verify")
    ap.add_argument("run_hash", help="the run's bundle hash (from the leaderboard run page)")
    ap.add_argument("--submit", action="store_true",
                    help="on MATCH, sign and publish your confirmation (counts toward "
                         "community-verified once enough distinct accounts agree)")
    ap.add_argument("--api", default=client.API_DEFAULT, help="Peakstone API base URL")
    ap.add_argument("--out", default=None, help="results dir (default results/reproduce-<hash8>)")
    args = ap.parse_args(argv)

    # 1) fetch + client-side trust chain — a tampered bundle must fail HERE, not define the run
    fetch = _fetch or (lambda h: client.get_reproduce(args.api, h))
    try:
        fetched = fetch(args.run_hash)
    except client.APIError as e:
        log(f"!! could not fetch run {args.run_hash}: {e}")
        return 2
    original = fetched["bundle"]
    problems = repro.verify_bundle(original)
    if problems:
        log("!! fetched bundle failed verification (refusing to run it):")
        for p in problems:
            log(f"   - {p}")
        return 2

    # 2) plan against the LOCAL corpus, pinned to the bundle's challenge content
    plan = repro.plan(original, paths.challenges_dir())
    if not plan.ids:
        log("!! nothing to reproduce: the run has no deterministic (non-private) results")
        return 2
    if plan.missing or plan.hash_mismatches:
        if plan.missing:
            log(f"!! {len(plan.missing)} challenge(s) not in the local corpus: "
                f"{', '.join(plan.missing[:5])}{'…' if len(plan.missing) > 5 else ''}")
        if plan.hash_mismatches:
            log(f"!! {len(plan.hash_mismatches)} challenge(s) differ from the bundle's pinned "
                f"content: {', '.join(plan.hash_mismatches[:5])}"
                f"{'…' if len(plan.hash_mismatches) > 5 else ''}")
        log("   sync the corpus and retry:  peakstone corpus sync")
        return 2

    # 3) the exact artifact (same-quant only)
    entry = (_resolve or _resolve_entry)(plan, log=log)
    if entry is None:
        log(f"!! model not available locally: {plan.family} {plan.artifact} ({plan.hf_repo})\n"
            f"   add it (TUI models screen, or serve/models.toml) and retry")
        return 2
    if entry.quant != plan.artifact:
        log(f"!! quant mismatch: the run used {plan.artifact}, local file is {entry.quant} — "
            f"a different artifact is a different measurement, refusing")
        return 2
    if not entry.present:
        log(f"model file missing; downloading {entry.name} …")
        if not (_download or models.download)(entry, log):
            log("!! download failed")
            return 2

    fit = preflight.check(entry)
    if fit and not fit.fits_now and not fit.fits_after_free:
        log(f"!! doesn't fit: needs ~{fit.need_gb} GB VRAM, {fit.free_gb} GB free "
            f"(+{fit.freeable_gb} freeable)")
        return 2

    # 4) run — the bundle's ids, budget and serve conditions; judge OFF (outside the vector)
    out = Path(args.out) if args.out else REPO / "results" / f"reproduce-{args.run_hash[:8]}"
    n = len(plan.ids)
    log(f"reproducing {plan.family} {plan.artifact}: {n} deterministic challenge(s), "
        f"suite {plan.suite_id}@{plan.suite_version}, max_tokens={plan.max_tokens or 'default'}")
    reasoning = _reasoning_arg(plan.reasoning_budget)
    log(f"serving {entry.name} …")
    proc = _serve(entry.name, ctx=plan.context, reasoning=reasoning)
    try:
        if not _wait(entry.port, proc=proc):
            log("!! model never became healthy (is llama-server installed / GPU free?)")
            return 2
        _bench(entry.name, plan.ids, out_dir=out, log=log, ctx=plan.context,
               reasoning=reasoning, max_tokens=plan.max_tokens)
    finally:
        _stop(proc)
    results_path = out / "results.json"
    if not results_path.exists():
        log("!! the run produced no results.json")
        return 2
    data = json.loads(results_path.read_text())

    # 5) re-emit OUR bundle stamped with the ORIGINAL's suite identity + selection (the group key
    # the server verifies by) — the serve conditions env vars make model identity record the same
    # effective ctx/thinking budget the subprocess ran with
    env_overrides = {"PEAKSTONE_CTX": str(plan.context) if plan.context else None,
                     "PEAKSTONE_REASONING_BUDGET": _reasoning_budget(reasoning)}
    saved = {k: os.environ.get(k) for k in env_overrides}
    try:
        for k, v in env_overrides.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        mine = eng_bundle.produce_bundle(
            {**data.get("meta", {}), "suite_id": plan.suite_id,
             "suite_version": plan.suite_version, "selected_ids": plan.ids},
            data.get("results", []))
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    (out / "bundle.json").write_text(json.dumps(mine, indent=2))

    # 6) the verdict
    v = repro.verdict(original["results"], mine["results"])
    log("")
    if v.status == "MATCH":
        log(f"MATCH ✓ — all {v.n} deterministic results identical: "
            f"this run is confirmed on your hardware.")
    else:
        log(f"{v.status} — {len(v.flips)}/{v.n} result(s) differ:")
        for f in v.flips[:20]:
            log(f"   {f['challenge']}: published {f['original']} vs yours {f['yours']}")
        if len(v.flips) > 20:
            log(f"   … and {len(v.flips) - 20} more")
        if v.status == "COMPATIBLE":
            log("   (within tolerance — GPU nondeterminism happens even at temp 0 — but only an "
                "exact MATCH verifies)")

    history.append({"kind": "reproduce", "run_hash": args.run_hash, "model": entry.name,
                    "verdict": v.status, "flips": len(v.flips), "n": v.n})

    # 7) publish the confirmation
    if args.submit and v.status == "MATCH":
        if mine.get("model", {}).get("file_sha256") != plan.file_sha256:
            log("!! not submitting: your model file's sha256 differs from the original's — the "
                "server would treat it as a different artifact, not a reproduction")
        else:
            status, detail = client.submit_bundle(args.api, mine)
            log("submitted ✓ — recorded as a reproduction (it counts toward community-verified "
                "when submitted from a GitHub-bound account other than the run's own)"
                if status == 201 else f"submit: HTTP {status} {detail}")
    elif v.status == "MATCH" and not args.submit:
        log(f"publish your confirmation:  peakstone reproduce {args.run_hash} --submit")

    return 0 if v.status in ("MATCH", "COMPATIBLE") else 1
