"""Peakstone API — submission ingest + faceted leaderboards.

Run (dev, SQLite):   python -m peakstone.api            # host/port from [api] in config.toml
Run (LAN):           add [api] host="0.0.0.0" to ~/.peakstone/config.toml, or --host 0.0.0.0
Run (Postgres):      PEAKSTONE_DATABASE_URL=postgresql+psycopg://... python -m peakstone.api
"""
from __future__ import annotations

import lzma
import os
import re
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from sqlalchemy import case, distinct, func, select
from sqlalchemy.orm import Session

from . import identity, ingest, models, proposals
from .db import get_session, init_db
from ..engine import contamination, scoreboard, versions
from ..engine.bundle import reasoning_mode

# Capability categories that are safety/honesty, not coding ability — scored separately so a strong
# coder isn't penalised (or flattered) in the headline code score (mirrors the report's split).
SAFETY = {"injection", "refusal", "hallucination", "security", "secure-code"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # promote any stored runs signed by a now-trusted operator key (trust is stamped at ingest, so
    # keys added to PEAKSTONE_TRUSTED_PUBKEYS later need reconciling for the ranked board).
    from .db import SessionLocal
    with SessionLocal() as db:
        n = ingest.reconcile_trusted_keys(db)
        if n:
            print(f"[startup] promoted {n} run(s) by trusted keys to runner-verified")
        # re-derive repro_sigs from stored raw bundles (idempotent) — whenever the sig formula
        # changes (e.g. challenge_hash joining the fingerprint), old rows must regroup or new
        # submissions would never match them and community verification would silently stall.
        n = ingest.recompute_repro_sigs(db)
        if n:
            print(f"[startup] recomputed repro_sig on {n} stored submission(s)")
        # backfill goal-state-env provenance onto Result rows ingested before the env column
        # existed (the public agent_score gates on it — see scoreboard.summarize_rows).
        n = ingest.backfill_result_env(db)
        if n:
            print(f"[startup] backfilled env provenance on {n} result row(s)")
    yield


app = FastAPI(title="Peakstone API", version="0.1.0", lifespan=lifespan)


class _XzBody:
    """ASGI middleware: transparently decompress an xz/lzma request body (Content-Encoding: xz) so the
    route sees plain JSON. Bundles are large transcript-heavy JSON; the client compresses the upload
    (~6.5-8x) to cut bandwidth. Uncompressed requests (every other endpoint) pass straight through.

    Zip-bomb guarded — /submissions is public, so a tiny body must not expand to GBs: cap the on-wire
    size, decompress with a hard OUTPUT cap, and bound the lzma dictionary via memlimit. Real bundles
    are ~1.4 MB raw / ~0.2 MB xz, so the defaults leave generous headroom."""

    MAX_COMPRESSED = int(os.environ.get("PEAKSTONE_MAX_UPLOAD_MB", "8")) * 1024 * 1024
    MAX_DECOMPRESSED = int(os.environ.get("PEAKSTONE_MAX_BUNDLE_MB", "64")) * 1024 * 1024
    LZMA_MEMLIMIT = 128 * 1024 * 1024                    # bounds a malicious xz dictionary allocation

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        from starlette.responses import JSONResponse

        async def reject(detail, code):
            return await JSONResponse({"detail": detail}, status_code=code)(scope, receive, send)

        headers = scope["headers"]
        is_xz = any(k == b"content-encoding" and v.strip().lower() == b"xz" for k, v in headers)
        # Cap the on-wire size for EVERY request, not just xz: a plain (uncompressed) multi-GB POST to a
        # public endpoint would otherwise be buffered + json-parsed whole -> memory exhaustion, sidestepping
        # the bomb guard simply by not compressing. xz bodies cap at the on-wire size; plain bodies at the
        # full decompressed cap (the route materialises the whole body before any handler runs).
        cap = self.MAX_COMPRESSED if is_xz else self.MAX_DECOMPRESSED
        for k, v in headers:                             # reject an oversized declared length up front
            if k == b"content-length":
                try:
                    if int(v) > cap:
                        return await reject("request body too large", 413)
                except ValueError:
                    pass
                break

        body = b""                                       # read once, hard-capped (covers chunked / lying CL)
        while True:
            msg = await receive()
            body += msg.get("body", b"")
            if len(body) > cap:
                return await reject("request body too large", 413)
            if not msg.get("more_body"):
                break

        if not is_xz:
            return await self._replay(scope, body, send)
        try:                                             # output-capped → a bomb is rejected, not materialized
            d = lzma.LZMADecompressor(memlimit=self.LZMA_MEMLIMIT)
            out = d.decompress(body, self.MAX_DECOMPRESSED + 1)
            if len(out) > self.MAX_DECOMPRESSED or not d.eof:
                return await reject("decompressed body too large", 413)
        except (lzma.LZMAError, EOFError, OSError):
            return await reject("invalid xz body", 400)
        scope = {**scope, "headers": [(k, v) for k, v in headers if k != b"content-encoding"]}
        return await self._replay(scope, out, send)

    async def _replay(self, scope, body, send):
        """Hand `body` to the app as a single request message, with content-length fixed to match."""
        headers = [(k, str(len(body)).encode() if k == b"content-length" else v)
                   for k, v in scope["headers"]]
        if not any(k == b"content-length" for k, _ in headers):
            headers.append((b"content-length", str(len(body)).encode()))
        scope = {**scope, "headers": headers}
        sent = False

        async def receive2():
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        return await self.app(scope, receive2, send)


class _RateLimit:
    """Per-client sliding-window rate limit (review R15) — two buckets, since writes are where the
    storage/DoS exposure lives. In-process (per worker): coarse, but it kills the trivial flood;
    put a real limiter at the proxy for distributed abuse. Set a limit to 0 to disable it."""
    READS_PER_MIN = int(os.environ.get("PEAKSTONE_RATE_READS_PER_MIN", "600"))
    WRITES_PER_MIN = int(os.environ.get("PEAKSTONE_RATE_WRITES_PER_MIN", "120"))

    def __init__(self, app):
        self.app = app
        self._hits: dict[tuple, deque] = defaultdict(deque)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        write = scope.get("method", "GET") in ("POST", "PUT", "PATCH", "DELETE")
        limit = self.WRITES_PER_MIN if write else self.READS_PER_MIN
        if limit > 0:
            key = ((scope.get("client") or ("?",))[0], write)
            q, now = self._hits[key], time.monotonic()
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= limit:
                await send({"type": "http.response.start", "status": 429,
                            "headers": [(b"content-type", b"application/json"),
                                        (b"retry-after", b"60")]})
                await send({"type": "http.response.body",
                            "body": b'{"detail":"rate limit exceeded; retry in a minute"}'})
                return
            q.append(now)
            if len(self._hits) > 4096:            # bound memory under an address-spray
                self._hits = defaultdict(deque, {k: v for k, v in self._hits.items() if v})
        return await self.app(scope, receive, send)


app.add_middleware(_XzBody)
app.add_middleware(_RateLimit)


# Response cache for the two hot, expensive aggregates (review R15: /leaderboard re-summarizes
# every submission per request; the web hits it on every page view). TTL-bounded and cleared on
# any board-mutating write, so tests and freshly-submitted runs always see current data.
_CACHE_TTL_S = float(os.environ.get("PEAKSTONE_CACHE_TTL_S", "30"))
_response_cache: dict[tuple, tuple[float, dict]] = {}


def _cached(key: tuple, build):
    if _CACHE_TTL_S <= 0:
        return build()
    hit = _response_cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < _CACHE_TTL_S:
        return hit[1]
    val = build()
    if len(_response_cache) > 512:                # bound memory under key-spray (vram filter etc.)
        _response_cache.clear()
    _response_cache[key] = (now, val)
    return val


def _cache_clear():
    _response_cache.clear()


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/version")
def version_info():
    """Client-version policy: the dashboard shows an upgrade nudge when it's behind `latest`, and a
    stronger one (or a refused submission) when it's below `min_supported`."""
    return {"latest": CLIENT_LATEST, "min_supported": CLIENT_MIN, "api": versions.pkg_version()}


@app.post("/submissions", status_code=201)
def post_submission(bundle: dict = Body(...), db: Session = Depends(get_session),
                    x_peakstone_client: str | None = Header(default=None)):
    """Validate (schema + content-hash + signature) and store a result bundle. An xz-compressed body
    (Content-Encoding: xz) is transparently decompressed by the _XzBody middleware before this runs, so
    large transcript-heavy uploads cost ~6.5-8x less bandwidth. Clients below the minimum supported
    version are refused (they'd produce incompatible bundles) — the header is advisory, sent by the CLI."""
    if x_peakstone_client and versions.is_outdated(x_peakstone_client, CLIENT_MIN):
        raise HTTPException(426, f"client {x_peakstone_client} is below the minimum supported "
                                 f"{CLIENT_MIN}; upgrade with `peakstone update`")
    try:
        sub = ingest.ingest_bundle(db, bundle)
    except ingest.IngestError as e:
        msg = str(e)
        raise HTTPException(status_code=409 if "already submitted" in msg else 400, detail=msg)
    _cache_clear()   # the board changed — cached aggregates must not outlive it
    return {"id": sub.id, "bundle_hash": sub.bundle_hash, "trust_tier": sub.trust_tier,
            "n_results": len(sub.results), "suite": f"{sub.suite_name}@{sub.suite_version}"}


# Axis math lives in engine/scoreboard.py (shared with the TUI's offline local board + `check`).
# The API adapts ORM rows to the dicts it consumes; parity is gated by the exact-value tests below.
_avg = scoreboard.avg
METRIC_AXES = scoreboard.METRIC_AXES
SORT_ORDER = scoreboard.SORT_ORDER

# The default leaderboard lens is the contamination-filtered (held-out) score, scoped to the official
# suite so it's apples-to-apples. A model needs at least this much held-out evidence to be *ranked*
# rather than *provisional* (shown below, by all-corpus code score) — a model is never dropped from
# the default board for lacking a held-out score, only demoted. Thresholds are tunable as the corpus
# accrues dated challenges (the board self-heals: provisional models cross the bar over time).
HELD_OUT_MIN_CLEAN = 5
HELD_OUT_MIN_COVERAGE = 0.5
# "name@version" of the suite the default board scopes to. Unset (dev) -> the board spans all suites.
OFFICIAL_SUITE = os.environ.get("PEAKSTONE_OFFICIAL_SUITE")

# Client-version policy (served at /version; the dashboard nudges to upgrade, submissions below MIN are
# refused). LATEST defaults to the server's own package version; bump PEAKSTONE_CLIENT_MIN when an old
# client would produce incompatible bundles.
CLIENT_LATEST = os.environ.get("PEAKSTONE_CLIENT_LATEST") or versions.pkg_version()
CLIENT_MIN = os.environ.get("PEAKSTONE_CLIENT_MIN") or "0.1.0"


# ORM Result → the bundle-shaped dict engine.scoreboard consumes. getattr-with-default so the API
# tests can pass SimpleNamespace fakes lacking most attributes (test_api.py exercises the helpers).
def _row_dict(r) -> dict:
    return {"category": getattr(r, "category", None), "verification": getattr(r, "verification", None),
            "score": {"final": getattr(r, "final", 0.0), "passed": getattr(r, "passed", None),
                      "total": getattr(r, "total", None)},
            "published_at": getattr(r, "published_at", None),
            "private": getattr(r, "private", False), "revealed": getattr(r, "revealed", False),
            "tok_per_s": getattr(r, "tok_per_s", None), "latency_s": getattr(r, "latency_s", None),
            "metrics": getattr(r, "metrics", None),
            "env": getattr(r, "env", None)}   # goal-state-env provenance (provider fidelity gating)


# Thin wrappers kept at their historical names/signatures: test_api.py imports these and feeds
# SimpleNamespace rows. Each adapts to dicts and delegates to the shared engine module.
def _agg_metrics(rs) -> dict:
    return scoreboard._agg_metrics([_row_dict(r) for r in rs])


def _calibration(rs) -> dict:
    return scoreboard._calibration([_row_dict(r) for r in rs])


def _self_repair(rs) -> dict:
    return scoreboard._self_repair([_row_dict(r) for r in rs])


def _truncation(rs) -> dict:
    return scoreboard._truncation([_row_dict(r) for r in rs])


def _ctx_efficiency(code_rs) -> dict:
    return scoreboard._ctx_efficiency([_row_dict(r) for r in code_rs])


def _held_out(code_rs, fam: models.ModelFamily | None) -> dict:
    return scoreboard._held_out([_row_dict(r) for r in code_rs],
                                fam.release_date if fam else None,
                                fam.training_cutoff if fam else None)


def _summarize(sub: models.Submission, fam: models.ModelFamily | None = None) -> dict:
    """One submission's ORM results → the full leaderboard axis dict. Pure axis math lives in
    engine.scoreboard (shared with the offline TUI board + `check`); this only adapts the rows +
    supplies the family's contamination dates."""
    return scoreboard.summarize_rows(
        [_row_dict(r) for r in sub.results],
        release_date=fam.release_date if fam else None,
        training_cutoff=fam.training_cutoff if fam else None,
        # public board: agent_score counts only isolating-provider rows — a local-provider run
        # (host shell, no network conditions) must not look like a faithful environment here.
        # The offline TUI board keeps counting the owner's consented local runs.
        agent_isolating_only=True)


def _submitter_handle(db, sub: models.Submission) -> str | None:
    key = db.get(models.Key, sub.key_id)
    if key and key.user_id is not None:
        user = db.get(models.User, key.user_id)
        return user.handle if user else None
    return None


def _submission_reasoning(sub: models.Submission) -> str | None:
    """Reasoning run-condition for a submission — derived from its serve flags + observed CoT tokens
    (a thinking-on vs thinking-off run is a distinct, faceted run, like a quant)."""
    return reasoning_mode(sub.serve_flags, ((r.metrics or {}).get("reasoning_tokens") for r in sub.results))


def _submission_reasoning_budget(sub: models.Submission) -> int | None:
    """The thinking budget the run was SERVED at, from `--reasoning-budget N` in the serve flags:
    0 = off, -1 = full (unlimited), N = capped at N thinking tokens. None if the flag wasn't set.
    Finer than the on/off facet — lets the leaderboard plot accuracy vs thinking budget for a model."""
    m = re.search(r"--reasoning-budget\s+(-?\d+)", sub.serve_flags or "")
    return int(m.group(1)) if m else None


def _run_info(db, sub: models.Submission, art: models.ModelArtifact) -> dict:
    env = sub.env or {}
    return {"artifact": art.artifact, "hf_repo": art.hf_repo,
            "gpu": env.get("gpu"), "cpu": env.get("cpu"),                        # hardware it ran on
            "vram_gb": sub.vram_gb, "ram_gb": env.get("ram_gb"),                 # machine totals
            "vram_used_gb": env.get("vram_used_gb"), "ram_used_gb": env.get("ram_used_gb"),  # model footprint
            "context": sub.context, "engine": sub.engine, "trust_tier": sub.trust_tier,
            "submitted_at": str(sub.submitted_at) if getattr(sub, "submitted_at", None) else None,
            "reasoning": _submission_reasoning(sub),     # run condition: chain-of-thought on/off (or None)
            "reasoning_budget": _submission_reasoning_budget(sub),   # thinking budget served (0/-1/N)
            # negative data: a non-viable config (looped out of every category, passed nothing). Tied to
            # THIS run's (quant, ctx, reasoning), so it shows which configs aren't worth testing.
            "run_status": (sub.raw or {}).get("run_status"),
            "abandoned_categories": (sub.raw or {}).get("abandoned_categories"),
            "submitter": _submitter_handle(db, sub),
            # distinct identities that independently reproduced this exact deterministic vector —
            # the "verified ×N" board column (peakstone reproduce <hash> is how one becomes it)
            "reproductions": _n_reproductions(db, sub),
            "bundle_hash": sub.bundle_hash}


_sort_value = scoreboard.sort_value


@app.get("/leaderboard")
def leaderboard(db: Session = Depends(get_session), suite: str | None = None,
                version: str | None = None, max_vram_gb: float | None = None,
                quant: str | None = None, trust: str | None = None, reasoning: str | None = None,
                reasoning_budget: str | None = None, verdict: str | None = None,
                sort: str = "held_out_score", order: str | None = None, collapse: str = "family"):
    """Faceted: under the active filters, each family collapses to its best-qualifying run (§6a),
    then rows are ranked by `sort`.

    The DEFAULT lens is `held_out_score` (the contamination-filtered code score), scoped to the
    official suite — so the headline ranks models on challenges they provably couldn't have trained
    on. On that default board a model is never dropped for lacking a held-out score: models with
    enough held-out evidence are `ranked`; the rest are `provisional` (listed below, by all-corpus
    `code_score`). Specialised axis boards (`agent_score`/`planner_score`/efficiency) instead drop
    runs that have no value on that axis. `collapse='quant'` keeps the best run per (family, quant).
    Pass `suite=all` to span every suite instead of the official one."""
    if sort not in SORT_ORDER:
        sort = "held_out_score"
    if order not in ("asc", "desc"):
        order = SORT_ORDER[sort]
    # default the board to the official (suite, version) so the headline is apples-to-apples
    if suite is None and version is None and OFFICIAL_SUITE:
        name, _, ver = OFFICIAL_SUITE.partition("@")
        suite, version = name, (ver or None)
    key = ("leaderboard", suite, version, max_vram_gb, quant, trust, reasoning,
           reasoning_budget, verdict, sort, order, collapse)
    return _cached(key, lambda: _build_leaderboard(db, suite, version, max_vram_gb, quant, trust,
                                                   reasoning, reasoning_budget, verdict, sort,
                                                   order, collapse))


def _build_leaderboard(db, suite, version, max_vram_gb, quant, trust, reasoning,
                       reasoning_budget, verdict, sort, order, collapse):
    q = select(models.Submission)
    if suite and suite != "all":
        q = q.where(models.Submission.suite_name == suite)
    if version:
        q = q.where(models.Submission.suite_version == version)
    if max_vram_gb is not None:
        q = q.where(models.Submission.vram_gb <= max_vram_gb)
    if trust:
        q = q.where(models.Submission.trust_tier == trust)

    default_heldout = sort == "held_out_score"
    # each family collapses to its best run for the chosen axis. On a specialised axis board a run
    # with no value there doesn't qualify (a safety-only run isn't a "coder"); on the default
    # held-out board we keep every family, falling back to code_score so provisional models still show.
    best: dict[str, dict] = {}
    for s in db.scalars(q).all():
        art = db.get(models.ModelArtifact, s.artifact_id)
        if quant and art.artifact != quant:
            continue
        if reasoning and (_submission_reasoning(s) or "none") != reasoning:
            continue                          # reasoning facet: thinking on/off is a distinct run
        if reasoning_budget is not None and str(_submission_reasoning_budget(s)) != reasoning_budget:
            continue                          # thinking-budget facet: a served --reasoning-budget value
        rs = (s.raw or {}).get("run_status")
        if verdict == "not_capable" and rs != "not_capable":
            continue                          # only the negative data: non-viable configs
        if verdict == "viable" and rs == "not_capable":
            continue                          # exclude non-viable configs from the board
        fam = db.get(models.ModelFamily, art.family_id)
        summ = _summarize(s, fam)
        row = {"family": fam.name, "release_date": fam.release_date,
               "observed_capabilities": sorted((fam.capabilities or {}).keys()), **summ,
               "run": _run_info(db, s, art)}
        val = _sort_value(row, sort)
        cmp_val = val if val is not None else (row.get("code_score") if default_heldout else None)
        if cmp_val is None:                   # no value on this axis (and not the held-out default)
            continue
        key = (f"{fam.name}\x00{art.artifact}\x00{_submission_reasoning(s) or 'none'}"
               f"\x00{_submission_reasoning_budget(s)}"
               if collapse == "quant" else fam.name)   # uncollapsed view splits thinking on/off AND budget
        cov = row.get("n_total") or 0
        cur = best.get(key)
        if cur is None:                       # keep the most-thorough qualifying run per group:
            better = True                     # prefer the most coverage, tie-break by the sort value
        elif cov != cur["_cov"]:
            better = cov > cur["_cov"]
        else:
            better = cmp_val > cur["_v"] if order == "desc" else cmp_val < cur["_v"]
        if better:
            best[key] = {**row, "_v": cmp_val, "_cov": cov}

    rows = list(best.values())
    if default_heldout:
        # two tiers: models with enough held-out evidence are ranked by held_out_score; the rest are
        # provisional, ranked below by all-corpus code_score (never dropped — the board self-heals).
        for r in rows:
            ho = r.get("held_out") or {}
            # A self-reported run never enters the RANKED tier: its held_out_score rests on the
            # submitter-declared release_date/published_at, so a single free keypair could otherwise
            # forge a #1 (review M2). It still shows as provisional. Operator (runner-verified) and
            # independently-reproduced (community-verified) runs rank.
            trusted = r.get("run", {}).get("trust_tier", "self-reported") != "self-reported"
            r["held_out_status"] = ("ranked" if trusted
                                    and r.get("held_out_score") is not None
                                    and ho.get("n_clean", 0) >= HELD_OUT_MIN_CLEAN
                                    and ho.get("coverage", 0) >= HELD_OUT_MIN_COVERAGE
                                    else "provisional")
        ranked = sorted((r for r in rows if r["held_out_status"] == "ranked"),
                        key=lambda r: r["held_out_score"], reverse=True)
        # provisional = unverified claims, so NEVER ordered by the claimed score (a forged 0.99
        # would top the list — review R6). Recency is neutral: newest submissions first.
        prov = sorted((r for r in rows if r["held_out_status"] == "provisional"),
                      key=lambda r: (r.get("run", {}).get("submitted_at") or ""), reverse=True)
        rows = ranked + prov
    else:
        rows = sorted(rows, key=lambda r: r["_v"], reverse=(order == "desc"))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r.pop("_v", None)
        r.pop("_cov", None)
    return {"filters": {"suite": suite, "version": version, "max_vram_gb": max_vram_gb,
                        "quant": quant, "trust": trust, "reasoning": reasoning,
                        "reasoning_budget": reasoning_budget, "verdict": verdict, "sort": sort,
                        "order": order, "collapse": collapse},
            "thresholds": ({"held_out_min_clean": HELD_OUT_MIN_CLEAN,
                            "held_out_min_coverage": HELD_OUT_MIN_COVERAGE} if default_heldout else {}),
            "count": len(rows), "leaderboard": rows}


@app.get("/runs/{bundle_hash}")
def run_results(bundle_hash: str, db: Session = Depends(get_session)):
    """Per-challenge results for one run (submission) — the breakdown behind a leaderboard row. Lite:
    scores + the error type only, NOT the (potentially large) transcripts; fetch a single challenge's
    transcript on demand via /runs/{hash}/challenge/{id}."""
    sub = db.scalar(select(models.Submission).where(models.Submission.bundle_hash == bundle_hash))
    if not sub:
        raise HTTPException(404, "unknown run")
    results = [{"challenge": r.challenge_id, "category": r.category, "verification": r.verification,
                "final": r.final, "passed": r.passed, "total": r.total, "difficulty": r.difficulty,
                "error": (r.transcript or {}).get("error")}
               for r in sub.results]
    results.sort(key=lambda r: (r["category"] or "", r["challenge"]))
    art = db.get(models.ModelArtifact, sub.artifact_id)      # header context so the run page can title
    fam = db.get(models.ModelFamily, art.family_id) if art else None   # itself + link back to the model
    return {"bundle_hash": bundle_hash, "n": len(results), "results": results,
            "family": fam.name if fam else None, "artifact": art.artifact if art else None,
            "context": sub.context, "trust_tier": sub.trust_tier,
            "suite": f"{sub.suite_name}@{sub.suite_version}"}


def _repro_group(db, sub: models.Submission) -> list[models.Submission]:
    """Every OTHER stored submission with the same deterministic result vector over the same
    artifact + suite — the reproduction group ingest promotes community-verified from."""
    if not sub.repro_sig:
        return []
    return db.scalars(select(models.Submission).where(
        models.Submission.artifact_id == sub.artifact_id,
        models.Submission.suite_name == sub.suite_name,
        models.Submission.suite_version == sub.suite_version,
        models.Submission.repro_sig == sub.repro_sig,
        models.Submission.id != sub.id,
    ).order_by(models.Submission.submitted_at)).all()


def _n_reproductions(db, sub: models.Submission) -> int:
    """Distinct identities (other than the run's own submitter) that reproduced this run's
    deterministic vector — the board's "verified ×N" number. Counted by the SAME rule promotion
    uses (account-bound + past the age bar), so the badge never claims more than the trust tier
    is built on; unbound-key reproductions still show in /runs/{hash}/reproductions."""
    own = ingest._identity_of(db, sub)
    return len({i for i in (ingest._identity_of(db, s) for s in _repro_group(db, sub))
                if i != own and i.startswith("user:") and ingest._seasoned(db, i)})


@app.get("/reproduce/{bundle_hash}")
def reproduce_bundle(bundle_hash: str, db: Session = Depends(get_session)):
    """Everything `peakstone reproduce` needs, in one fetch: the stored bundle VERBATIM — still
    signed and content-addressed, so the client re-verifies the whole trust chain before letting
    it define a run — plus where its reproduction group stands today."""
    sub = db.scalar(select(models.Submission).where(models.Submission.bundle_hash == bundle_hash))
    if not sub or not sub.raw:
        raise HTTPException(404, "unknown run")
    return {"bundle": sub.raw, "trust_tier": sub.trust_tier,
            "reproductions": _n_reproductions(db, sub)}


@app.get("/runs/{bundle_hash}/reproductions")
def run_reproductions(bundle_hash: str, db: Session = Depends(get_session)):
    """The run's reproduction record: who independently re-ran this exact deterministic vector,
    on what hardware, when — the proof artifact behind the trust-tier badge."""
    sub = db.scalar(select(models.Submission).where(models.Submission.bundle_hash == bundle_hash))
    if not sub:
        raise HTTPException(404, "unknown run")
    own = ingest._identity_of(db, sub)
    rows, identities = [], set()
    for s in _repro_group(db, sub):
        ident = ingest._identity_of(db, s)
        if ident != own:
            identities.add(ident)
        env = s.env or {}
        rows.append({"bundle_hash": s.bundle_hash, "submitter": _submitter_handle(db, s),
                     "trust_tier": s.trust_tier,
                     "submitted_at": str(s.submitted_at) if s.submitted_at else None,
                     "gpu": env.get("gpu"), "vram_gb": s.vram_gb,
                     # a run's own submitter re-running it is transparency, not verification
                     "independent": ident != own})
    return {"bundle_hash": bundle_hash, "n": len(rows),
            "distinct_identities": len(identities), "reproductions": rows}


@app.get("/runs/{bundle_hash}/challenge/{challenge_id}")
def run_challenge(bundle_hash: str, challenge_id: str, db: Session = Depends(get_session)):
    """One challenge's full result incl. transcript — fetched when the user opens the solution view."""
    sub = db.scalar(select(models.Submission).where(models.Submission.bundle_hash == bundle_hash))
    if not sub:
        raise HTTPException(404, "unknown run")
    r = next((x for x in sub.results if x.challenge_id == challenge_id), None)
    if not r:
        raise HTTPException(404, "unknown challenge in this run")
    return {"challenge": r.challenge_id, "final": r.final, "passed": r.passed, "total": r.total,
            "category": r.category, "transcript": _capped_transcript(r.transcript)}


def _capped_transcript(tr, cap: int = 200_000):
    """Transcripts are stored unbounded (full attempts logs); SERVE them capped so one multi-MB
    row can't turn a solution view into a multi-MB response/page (review R16). Per-string cap,
    applied one level into the attempts list too — generous enough for any honest read."""
    def _cut(v):
        if isinstance(v, str) and len(v) > cap:
            return v[:cap] + f"\n… [truncated {len(v) - cap} chars]"
        return v
    if not isinstance(tr, dict):
        return _cut(tr)
    out = {}
    for k, v in tr.items():
        if k == "attempts" and isinstance(v, list):
            out[k] = [{ak: _cut(av) for ak, av in a.items()} if isinstance(a, dict) else _cut(a)
                      for a in v]
        else:
            out[k] = _cut(v)
    return out


@app.get("/models/{family}")
def model_page(family: str, db: Session = Depends(get_session)):
    """Every run (no collapsing) for a model family — quants, contexts, hardware, trust tiers."""
    fam = db.scalar(select(models.ModelFamily).where(models.ModelFamily.name == family))
    if not fam:
        raise HTTPException(404, f"unknown family {family!r}")
    art_ids = [a.id for a in fam.artifacts]
    subs = db.scalars(select(models.Submission)
                      .where(models.Submission.artifact_id.in_(art_ids))
                      .order_by(models.Submission.submitted_at.desc())).all()
    runs = []
    for s in subs:
        art = db.get(models.ModelArtifact, s.artifact_id)
        runs.append({**_summarize(s, fam), "run": _run_info(db, s, art),
                     "suite": f"{s.suite_name}@{s.suite_version}"})
    return {"family": fam.name, "vendor": fam.vendor, "release_date": fam.release_date,
            "observed_capabilities": sorted((fam.capabilities or {}).keys()),
            "n_runs": len(runs), "runs": runs}


@app.get("/facets")
def facets(db: Session = Depends(get_session)):
    """Distinct filterable values for the leaderboard UI (quant pills, suite picker, trust filter)."""
    return _cached(("facets",), lambda: _build_facets(db))


def _build_facets(db):
    quants = db.scalars(select(distinct(models.ModelArtifact.artifact))
                        .order_by(models.ModelArtifact.artifact)).all()
    suites = db.execute(select(models.Submission.suite_name, models.Submission.suite_version)
                        .distinct().order_by(models.Submission.suite_name)).all()
    trusts = db.scalars(select(distinct(models.Submission.trust_tier))).all()
    # reasoning + budget are derived per-submission (serve flags + observed CoT), computed here
    subs = db.scalars(select(models.Submission)).all()
    reasonings = sorted({_submission_reasoning(s) for s in subs} - {None})
    budgets = sorted({_submission_reasoning_budget(s) for s in subs} - {None})
    _placeholder = {"(unknown)", "(unregistered)"}
    return {"quants": [q for q in quants if q and q not in _placeholder],
            "suites": [{"name": n, "version": v} for n, v in suites],
            "trust_tiers": sorted(trusts, key=lambda t: ingest.TRUST_ORDER.get(t, 0)),
            "reasoning": reasonings,                      # thinking on/off run-condition facet
            "reasoning_budgets": budgets,                 # served --reasoning-budget values (0/-1/N)
            "sort_axes": [{"key": k, "order": o} for k, o in SORT_ORDER.items()]}


@app.get("/challenges")
def challenges(db: Session = Depends(get_session)):
    """The challenge corpus with aggregate difficulty signal (pass-rate is the empirical tier).
    Both are TRUSTED-RUNS-ONLY: one self-signed forged bundle must not move the public difficulty
    calibration (review R6). Challenges lazily registered by untrusted submissions ('observed')
    are likewise not listed as corpus entries."""
    rows = db.execute(
        select(models.Result.challenge_id,
               func.count(models.Result.id).label("n"),
               func.avg(models.Result.final).label("avg"),
               func.sum(case((models.Result.final >= 0.999, 1), else_=0)).label("solved"))
        .join(models.Submission, models.Result.submission_id == models.Submission.id)
        .where(models.Submission.trust_tier != "self-reported")
        # sealed private rows never aggregate — their author-chosen slug must not pollute (or
        # collide with) a public challenge's stats; revealed rows count under the revealed id.
        .where((models.Result.private.is_(False)) | (models.Result.revealed.is_(True)))
        .group_by(models.Result.challenge_id)).all()
    stats = {r.challenge_id: r for r in rows}
    out = []
    for ch in db.scalars(select(models.Challenge).where(models.Challenge.status != "observed")
                         .order_by(models.Challenge.id)).all():
        s = stats.get(ch.id)
        n = s.n if s else 0
        out.append({"id": ch.id, "title": ch.title, "language": ch.language,
                    "category": ch.category, "verification": ch.verification,
                    "seed_difficulty": ch.seed_difficulty, "status": ch.status,
                    "version": ch.version, "deprecated": ch.deprecated,
                    "n_runs": n, "avg_score": round(s.avg, 3) if s and s.avg is not None else None,
                    "pass_rate": round((s.solved or 0) / n, 3) if n else None})
    return {"count": len(out), "challenges": out}


@app.get("/challenges/{challenge_id}")
def challenge_detail(challenge_id: str, db: Session = Depends(get_session)):
    """Per-challenge mini-leaderboard: each family's best result on this one challenge."""
    ch = db.get(models.Challenge, challenge_id)
    if not ch:
        raise HTTPException(404, f"unknown challenge {challenge_id!r}")
    best: dict[str, dict] = {}
    for r in db.scalars(select(models.Result)
                        .join(models.Submission,
                              models.Result.submission_id == models.Submission.id)
                        # trusted runs only: a forged self-reported bundle must not top a
                        # challenge's mini-leaderboard (review R6)
                        .where(models.Submission.trust_tier != "self-reported",
                               models.Result.challenge_id == challenge_id,
                               (models.Result.private.is_(False))
                               | (models.Result.revealed.is_(True)))).all():
        sub = db.get(models.Submission, r.submission_id)
        art = db.get(models.ModelArtifact, sub.artifact_id)
        fam = db.get(models.ModelFamily, art.family_id)
        cur = best.get(fam.name)
        if cur is None or r.final > cur["score"]:
            best[fam.name] = {"family": fam.name, "score": round(r.final, 3),
                              "passed": r.passed, "total": r.total,
                              "run": _run_info(db, sub, art)}
    rows = sorted(best.values(), key=lambda x: -x["score"])
    return {"id": ch.id, "category": ch.category, "verification": ch.verification,
            "seed_difficulty": ch.seed_difficulty, "status": ch.status,
            "n_families": len(rows), "results": rows}


@app.get("/challenges/{challenge_id}/source")
def challenge_source_endpoint(challenge_id: str):
    """The public challenge source (spec + test files) for the solution viewer. 404 for any challenge
    not in the public corpus — copyright-encumbered/private sets are never in the image, so never served."""
    from peakstone.engine.challenges import challenge_source
    src = challenge_source(challenge_id)
    if src is None:
        raise HTTPException(404, f"no public source for {challenge_id!r}")
    return src


# --- account / identity binding ------------------------------------------------------------------

@app.post("/account/key-challenge")
def account_key_challenge(pubkey: str = Body(..., embed=True), db: Session = Depends(get_session)):
    """Issue a nonce the key must sign to prove ownership (step 1 of binding to an account)."""
    ch = identity.issue_key_challenge(db, pubkey)
    return {"nonce": ch.nonce, "expires_at": str(ch.expires_at)}


@app.get("/auth/{provider}/authorize-url")
def authorize_url(provider: str, redirect_uri: str = Query(...), state: str = Query(""),
                  db: Session = Depends(get_session)):
    """Build the provider's OAuth consent URL (the frontend redirects the browser here)."""
    try:
        prov = identity.get_provider(provider)
    except identity.BindError as e:
        raise HTTPException(503, str(e))
    return {"authorize_url": prov.authorize_url(state, redirect_uri)}


@app.post("/account/bind")
def account_bind(body: dict = Body(...), db: Session = Depends(get_session)):
    """Bind a key to an account: requires both a signed nonce (key proof) and an OAuth code."""
    try:
        fields = {k: body[k] for k in ("provider", "pubkey", "nonce", "signature", "code", "redirect_uri")}
    except KeyError as e:
        raise HTTPException(400, f"missing field {e}")
    if not all(isinstance(v, str) for v in fields.values()):
        raise HTTPException(400, "all bind fields must be strings")
    try:
        return identity.bind(db, **fields)
    except identity.BindError as e:
        msg = str(e)
        raise HTTPException(503 if "not configured" in msg else 400, msg)


@app.get("/account")
def account(pubkey: str = Query(...), db: Session = Depends(get_session)):
    """Who a key belongs to (the bound account + its providers), if any."""
    summary = identity.account_summary(db, pubkey)
    if summary is None:
        raise HTTPException(404, "key not bound to any account")
    return summary


# --- challenge moderation (open corpus → admin-canonized) ----------------------------------------

def _proposal_summary(p: models.ChallengeProposal) -> dict:
    return {"id": p.id, "slug": p.slug, "title": p.title, "language": p.language,
            "category": p.category, "difficulty": p.difficulty, "status": p.status,
            "reference_passes": (p.validation or {}).get("reference_passes"),
            "content_hash": p.content_hash, "created_at": str(p.created_at),
            "review_note": p.review_note}


@app.post("/proposals", status_code=201)
def propose_challenge(proposal: dict = Body(...), db: Session = Depends(get_session)):
    """Submit a signed challenge proposal (built by `python -m engine.propose`) to the queue."""
    try:
        p = proposals.propose(db, proposal)
    except proposals.ProposalError as e:
        msg = str(e)
        raise HTTPException(409 if "already submitted" in msg else 400, msg)
    return _proposal_summary(p)


@app.get("/proposals")
def list_proposals(status: str = "proposed", db: Session = Depends(get_session)):
    """The moderation queue (default: pending). status=all for every proposal."""
    q = select(models.ChallengeProposal).order_by(models.ChallengeProposal.created_at.desc())
    if status != "all":
        q = q.where(models.ChallengeProposal.status == status)
    rows = [_proposal_summary(p) for p in db.scalars(q).all()]
    return {"count": len(rows), "proposals": rows}


@app.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: int, db: Session = Depends(get_session)):
    """Full proposal (spec + files) for review."""
    p = db.get(models.ChallengeProposal, proposal_id)
    if not p:
        raise HTTPException(404, f"unknown proposal {proposal_id}")
    return {**_proposal_summary(p), "spec": p.spec, "files": p.files,
            "scoring": p.scoring, "timeout": p.timeout, "validation": p.validation}


@app.post("/proposals/{proposal_id}/review")
def review_proposal(proposal_id: int, body: dict = Body(...), db: Session = Depends(get_session)):
    """Admin-signed approve/reject. Sign `<decision>:<content_hash>:<unix-ts>` with an admin key
    and pass `ts` in the body — the timestamp keeps a captured signature from being replayed
    later (e.g. an old approve after a reject)."""
    try:
        p = proposals.review(db, proposal_id, pubkey=body.get("pubkey", ""),
                             signature=body.get("signature", ""), decision=body.get("decision", ""),
                             note=body.get("note"), ts=body.get("ts"))
    except proposals.AdminError as e:
        raise HTTPException(403, str(e))
    except proposals.ProposalError as e:
        msg = str(e)
        raise HTTPException(409 if "already" in msg else 400, msg)
    return _proposal_summary(p)


@app.post("/challenges/{challenge_id}/deprecate")
def deprecate_challenge(challenge_id: str, body: dict = Body(...), db: Session = Depends(get_session)):
    """Admin-signed deprecation. Sign the message `deprecate:<challenge_id>` with an admin key."""
    try:
        ch = proposals.deprecate(db, challenge_id, pubkey=body.get("pubkey", ""),
                                signature=body.get("signature", ""), note=body.get("note"))
    except proposals.AdminError as e:
        raise HTTPException(403, str(e))
    except proposals.ProposalError as e:
        raise HTTPException(400, str(e))
    return {"id": ch.id, "status": ch.status, "deprecated": ch.deprecated, "version": ch.version}


@app.post("/reveals", status_code=201)
def reveal(body: dict = Body(...), db: Session = Depends(get_session)):
    """Open a commitment (commit-and-reveal): the revealed content + salt must hash to a commitment
    that sealed previously-submitted private results. Possession of (content, salt) IS the proof —
    the sealed rows' server-stamped submitted_at anchors that the scores predate this reveal.

    Verifies the commitment, materializes the challenge into the corpus (content stored; the
    reference-must-pass validation is the revealer's self-reported local run — the API never
    executes untrusted code, same policy as proposals), and flips every matching result to
    `revealed` with published_at = today (source 'private-reveal') → they join the held-out board;
    models released after today see this challenge as contaminated, as they should."""
    import tomllib as _toml
    from ..engine import private as eng_private

    salt = body.get("salt") or ""
    files = body.get("files")
    if not isinstance(files, dict) or not files or \
            not all(isinstance(k, str) and isinstance(v, str) for k, v in files.items()):
        raise HTTPException(400, "files must be a non-empty {relpath: text} object")
    try:
        com = eng_private.commitment_from_files(files, salt)
    except ValueError:
        raise HTTPException(400, "salt must be hex")

    rows = db.scalars(select(models.Result).where(models.Result.commitment == com,
                                                  models.Result.private.is_(True))).all()
    if not rows:
        raise HTTPException(404, "no committed results reference this content+salt — nothing to open "
                                 "(check the salt, and that the sealed bundle was submitted first)")
    existing = db.scalar(select(models.Reveal).where(models.Reveal.commitment == com))
    if existing:
        raise HTTPException(409, f"already revealed as challenge {existing.challenge_id!r}")

    # structural checks (same bar as a proposal payload)
    try:
        meta = _toml.loads(files.get("meta.toml", ""))
    except _toml.TOMLDecodeError as e:
        raise HTTPException(400, f"meta.toml does not parse: {e}")
    cid = meta.get("id")
    if not cid or not isinstance(cid, str):
        raise HTTPException(400, "meta.toml must declare a string id")
    if "spec.md" not in files or not any(p.startswith("tests/") for p in files):
        raise HTTPException(400, "revealed content must include spec.md and tests/")
    if db.get(models.Challenge, cid):
        raise HTTPException(409, f"challenge id {cid!r} already exists in the public corpus — the "
                                 "committed content can't be renamed; pick globally-unique ids for "
                                 "private challenges")

    # optional attribution: a signature over `reveal:<commitment>` binds the reveal to a key
    author_key = None
    pub, sig = body.get("pubkey"), body.get("signature")
    if pub and sig:
        from peakstone.engine import keys as eng_keys
        if not eng_keys.verify(pub, sig, f"reveal:{com}".encode()):
            raise HTTPException(403, "signature over 'reveal:<commitment>' does not verify")
        author_key = db.scalar(select(models.Key).where(models.Key.pubkey == pub)) \
            or models.Key(pubkey=pub)
        db.add(author_key)
        db.flush()

    today = models._utcnow().date().isoformat()
    ch = models.Challenge(
        id=cid, title=meta.get("title"), language=meta.get("language"),
        category=meta.get("category") or (rows[0].category if rows else None),
        verification=rows[0].verification, seed_difficulty=meta.get("difficulty"),
        content_hash=eng_private.public_content_hash(files), status="published",
        author_key_id=author_key.id if author_key else None)
    db.add(ch)
    db.add(models.Reveal(commitment=com, salt=salt, challenge_id=cid, files=files,
                         validation=body.get("validation"),
                         revealed_by_key_id=author_key.id if author_key else None))
    for r in rows:
        r.revealed = True
        r.challenge_id = cid
        r.published_at = today
        r.published_at_source = "private-reveal"
    db.commit()
    _cache_clear()   # revealed rows start counting — cached boards must not outlive them
    return {"challenge_id": cid, "commitment": com, "n_results_revealed": len(rows),
            "published_at": today}
