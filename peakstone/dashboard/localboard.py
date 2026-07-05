"""Offline-first local leaderboard: build a scoreboard from result bundles on disk, merge with the
server board when it's reachable.

The dashboard renders this immediately at startup (no network), then re-renders merged once the API
answers. A local run that was already submitted is recognised (by bundle_hash) and shown once, badged
as published. Pure functions here (scan/summarize/merge) — the Textual wiring lives in app.py.

Row shape matches the server's GET /leaderboard rows (engine.scoreboard.summarize_rows output +
{family, release_date, held_out_status, run}), so local and server rows collapse/sort/render through
one code path. Local rows carry run.local=True, run.path, run.suite, run.submitted.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..engine import paths, scoreboard
from ..engine.bundle import _verification as _bundle_verification

CACHE_VERSION = 2   # bump when summarize_rows output or the row shape changes (invalidates the cache)
_MAX_LOCAL_CONTENT = 100_000

# in-memory cache fronting the on-disk file, so repeated builds in one session cost no I/O
_mem: dict | None = None


# --------------------------------------------------------------------------- scanning

def _bundle_path(d: Path) -> Path | None:
    for name in ("bundle.json", "combined.bundle.json"):   # same order as engine.check
        p = d / name
        if p.is_file():
            return p
    return None


def _run_dirs(root: Path) -> list[Path]:
    """Result dirs at depth ≤ 2 under results/: results/<stamp>/ and results/seed-*/<model>/.
    Bounded (no full walk); tolerant of a missing/unreadable root (pipx, fresh install)."""
    out: list[Path] = []
    try:
        tops = [p for p in root.iterdir() if p.is_dir()]
    except OSError:
        return out
    for top in tops:
        out.append(top)
        try:
            out.extend(p for p in top.iterdir() if p.is_dir())
        except OSError:
            continue
    return out


# --------------------------------------------------------------------------- row builders

def _row_from_bundle(bundle: dict, run_dir: Path) -> dict:
    m = bundle.get("model") or {}
    env = bundle.get("environment") or {}
    suite = bundle.get("suite") or {}
    summ = scoreboard.summarize_rows(bundle.get("results") or [],
                                     release_date=m.get("release_date"),
                                     training_cutoff=m.get("training_cutoff"))
    return {
        "family": m.get("family") or run_dir.name,
        "release_date": m.get("release_date"),
        "held_out_status": "provisional",   # a local run is self-reported → never enters the ranked tier
        **summ,
        "run": {
            "artifact": m.get("artifact"), "hf_repo": m.get("hf_repo"),
            "gpu": env.get("gpu"), "cpu": env.get("cpu"),
            "vram_gb": env.get("vram_gb"), "ram_gb": env.get("ram_gb"),
            "vram_used_gb": env.get("vram_used_gb"), "ram_used_gb": env.get("ram_used_gb"),
            "context": m.get("context"), "engine": (m.get("engine") or {}).get("name"),
            "trust_tier": "local",
            "reasoning": m.get("reasoning"),
            "reasoning_budget": scoreboard.reasoning_budget_from_flags(m.get("serve_flags")),
            "run_status": bundle.get("run_status"),
            "abandoned_categories": bundle.get("abandoned_categories"),
            "submitted_at": bundle.get("submitted_at"), "submitter": None,
            "bundle_hash": bundle.get("bundle_hash"),
            "local": True, "path": str(run_dir),
            "suite": f"{suite.get('id')}@{suite.get('version')}",
        },
    }


def _engine_row_to_dict(r: dict) -> dict:
    """A raw engine results.json row → the bundle-shaped dict scoreboard consumes (best-effort;
    these degraded rows lack published_at/metrics, so no held-out or efficiency axes)."""
    return {"category": r.get("type") or r.get("category"),
            "verification": _bundle_verification(r),
            "score": {"final": r.get("final_score", 0.0),
                      "passed": r.get("passed"), "total": r.get("total")},
            "published_at": None, "private": False, "revealed": False,
            "tok_per_s": r.get("tok_per_s"), "latency_s": r.get("latency_s"),
            "metrics": r.get("metrics")}


def _row_from_results_json(data: dict, run_dir: Path) -> dict | None:
    """Degraded row for a run that has results.json but no bundle (e.g. a --no-bundle smoke run).
    Reduced identity: no quant/sha, no held-out, can't dedupe against the server or be submitted."""
    meta = data.get("meta") or {}
    rows = [_engine_row_to_dict(r) for r in (data.get("results") or [])]
    if not rows:
        return None
    summ = scoreboard.summarize_rows(rows)
    models = meta.get("models") or []
    return {
        "family": (models[0] if models else run_dir.name),
        "release_date": None, "held_out_status": "provisional",
        **summ,
        "run": {
            "artifact": "(no bundle)", "trust_tier": "local", "local": True, "path": str(run_dir),
            "bundle_hash": None, "reasoning": None, "reasoning_budget": None,
            "context": None, "gpu": (meta.get("gpu") or {}).get("name") if isinstance(meta.get("gpu"), dict) else None,
            "run_status": meta.get("run_status"), "submitted_at": None, "submitter": None,
            "suite": f"{meta.get('suite_id')}@{meta.get('suite_version')}"
                     if meta.get("suite_id") else "adhoc",
            "no_bundle": True,
        },
    }


# --------------------------------------------------------------------------- cache

def _cache_path() -> Path:
    return paths.home_dir() / "localboard_cache.json"


def _load_cache() -> dict:
    global _mem
    if _mem is not None:
        return _mem
    try:
        data = json.loads(_cache_path().read_text())
        if isinstance(data, dict) and data.get("version") == CACHE_VERSION:
            _mem = data
            return _mem
    except (OSError, ValueError):
        pass
    _mem = {"version": CACHE_VERSION, "entries": {}}
    return _mem


def _save_cache(cache: dict, live_paths: set[str]) -> None:
    cache["entries"] = {k: v for k, v in cache["entries"].items() if k in live_paths}
    try:
        p = _cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache))
        tmp.replace(p)   # atomic
    except OSError:
        pass   # a read-only home must never break the board


def _summarize_dir(run_dir: Path, cache: dict) -> dict | None:
    """The board row for one result dir, via the (path, mtime, size) cache. None if the dir has
    no parseable run."""
    bpath = _bundle_path(run_dir)
    src = bpath or (run_dir / "results.json")
    if not src.is_file():
        return None
    key = str(src)
    try:
        st = src.stat()
    except OSError:
        return None
    ent = cache["entries"].get(key)
    if ent and ent.get("mtime") == st.st_mtime and ent.get("size") == st.st_size:
        return ent["row"]
    try:
        data = json.loads(src.read_text())
    except (OSError, ValueError):
        return None
    if bpath:
        if not isinstance(data.get("results"), list):
            return None
        row = _row_from_bundle(data, run_dir)
    else:
        row = _row_from_results_json(data, run_dir)
    if row is None:
        return None
    cache["entries"][key] = {"mtime": st.st_mtime, "size": st.st_size, "row": row}
    return row


# --------------------------------------------------------------------------- submission status

def _submitted_hashes() -> set[str]:
    """bundle_hashes the local gateway recorded as submitted (jobs.db). Read-only, best-effort —
    a missing/locked/old db just yields an empty set (status shows as 'unknown', never crashes)."""
    db = paths.repo_root() / "results" / "jobs.db"
    if not db.is_file():
        return set()
    out: set[str] = set()
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=0.5)
        try:
            rows = con.execute("SELECT summary FROM jobs WHERE summary IS NOT NULL").fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return out
    for (s,) in rows:
        try:
            d = json.loads(s)
        except (ValueError, TypeError):
            continue
        if isinstance(d, dict) and d.get("submitted") and d.get("bundle_hash"):
            out.add(d["bundle_hash"])
    return out


# --------------------------------------------------------------------------- builder

def default_suite() -> str:
    """The official suite the local board scopes to by default (current levels.toml standard)."""
    from ..engine.levels import load_levels
    return f"level-standard@{load_levels()[0]}"


def build_local_board(*, root: Path | None = None, all_suites: bool = False) -> tuple[list[dict], bool]:
    """Scan results/ into board rows (uncollapsed — merge_rows collapses local + server together).

    Returns (rows, scoped): `scoped` is True when the rows are the default-suite subset, False when
    we fell back to all suites (either because all_suites was requested OR the suite filter would
    have emptied a non-empty local set — never show an empty offline board when runs exist)."""
    root = root or (paths.repo_root() / "results")
    cache = _load_cache()
    rows: list[dict] = []
    live: set[str] = set()
    for d in _run_dirs(root):
        row = _summarize_dir(d, cache)
        if row is None:
            continue
        rows.append(row)
        bpath = _bundle_path(d)
        live.add(str(bpath or (d / "results.json")))
    _save_cache(cache, live)

    subs = _submitted_hashes()
    for r in rows:
        bh = r["run"].get("bundle_hash")
        r["run"]["submitted"] = (bh in subs) if bh else None

    if all_suites:
        return rows, False
    want = default_suite()
    scoped = [r for r in rows if r["run"].get("suite") == want]
    if not scoped and rows:
        return rows, False           # fall back rather than render an empty board
    return scoped, True


# --------------------------------------------------------------------------- merge / collapse / sort

def _quant_key(row: dict) -> tuple:
    run = row.get("run") or {}
    return (row.get("family"), run.get("artifact"),
            run.get("reasoning") or "none", run.get("reasoning_budget"))


def merge_rows(local: list[dict], server: list[dict], *, sort: str) -> list[dict]:
    """Merge local + server rows into one ranked board. A local run already on the server (same
    bundle_hash) collapses into the server row (marked published); otherwise best-per-quant-config
    wins by coverage. Sorted client-side by the active axis (local rows aren't pre-sorted)."""
    order = scoreboard.SORT_ORDER.get(sort, "desc")

    # 1) dedupe local vs server by bundle_hash — one physical run = one row (the server row wins,
    #    flagged published, so its trust tier / submitter show).
    server_hashes = {r["run"]["bundle_hash"]: r for r in server
                     if (r.get("run") or {}).get("bundle_hash")}
    merged: list[dict] = list(server)
    for r in local:
        bh = (r.get("run") or {}).get("bundle_hash")
        if bh and bh in server_hashes:
            srv = server_hashes[bh]
            srv["run"]["published"] = True
            srv["run"]["local_path"] = r["run"].get("path")
            srv["run"]["submitted"] = True
            continue
        merged.append(r)

    # 2) collapse to best run per (family, artifact, reasoning, budget) — the server's quant key.
    best: dict[tuple, dict] = {}
    for r in merged:
        k = _quant_key(r)
        cur = best.get(k)
        if cur is None:
            best[k] = r
            continue
        rn, cn = (r.get("n_total") or 0), (cur.get("n_total") or 0)
        if rn > cn:
            best[k] = r
        elif rn == cn:
            rv, cv = scoreboard.sort_value(r, sort), scoreboard.sort_value(cur, sort)
            if _better(rv, cv, order):
                best[k] = r
    rows = list(best.values())

    # 3) sort + rank.
    if sort == "held_out_score":
        ranked = [r for r in rows if r.get("held_out_status") == "ranked"]
        prov = [r for r in rows if r.get("held_out_status") != "ranked"]
        ranked.sort(key=lambda r: (r.get("held_out_score") or 0), reverse=True)
        prov.sort(key=lambda r: (r.get("code_score") or 0), reverse=True)
        rows = ranked + prov
    else:
        rows = [r for r in rows if scoreboard.sort_value(r, sort) is not None]
        rows.sort(key=lambda r: scoreboard.sort_value(r, sort), reverse=(order == "desc"))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def _better(a, b, order: str) -> bool:
    if a is None:
        return False
    if b is None:
        return True
    return a > b if order == "desc" else a < b


# --------------------------------------------------------------------------- offline drill-in

def read_run_results(run_dir: str) -> list[dict] | None:
    """Per-challenge results for a local run, in the lite shape the server's /runs/{hash} returns —
    so expanding a local row in the TUI works offline. None if unreadable."""
    d = Path(run_dir)
    bpath = _bundle_path(d)
    if not bpath:
        return None
    try:
        b = json.loads(bpath.read_text())
    except (OSError, ValueError):
        return None
    out = []
    for r in b.get("results") or []:
        out.append({"challenge": r.get("challenge_id"), "category": r.get("category"),
                    "verification": r.get("verification"),
                    "final": (r.get("score") or {}).get("final"),
                    "passed": (r.get("score") or {}).get("passed"),
                    "total": (r.get("score") or {}).get("total"),
                    "error": (r.get("transcript") or {}).get("error")})
    out.sort(key=lambda x: ((x["final"] if x["final"] is not None else 1.0), x["challenge"] or ""))
    return out
