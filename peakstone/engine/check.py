"""`peakstone check` — the CI regression gate: did this checkpoint regress vs a baseline run?

Compares two result BUNDLES (the signed artifact a run already emits) on the same suite and exits
non-zero on regression, so a fine-tuner/quant-maker can gate CI on "did my new checkpoint get worse
on any capability axis?". The comparison is against the user's OWN previous run — valuable with no
leaderboard involved; the bundles it consumes/produces are the same ones `--submit` publishes.

Axes mirror the leaderboard exactly (api._summarize): code / math / long-context / safety /
agentic / planner, split by the same category+verification filters — so a local `check` verdict and
the public board always agree about what moved.

Policy: an axis gates only when BOTH sides have >= --min-n results (small axes are noise) and the
score drops by more than --max-drop (absolute). Per-challenge green<->red flips are reported for
debugging but don't gate (a same-score shuffle isn't a regression). tok/s is shown, never gated
(hardware-specific). Exit codes: 0 ok · 1 regression · 2 not comparable / usage error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# the same axis split the API's _summarize uses — keep in lockstep with api/main.py
SAFETY = {"injection", "refusal", "hallucination", "security", "secure-code"}
GREEN = 0.999   # score.final >= GREEN counts as solved (the board's "solved" threshold)


def _load_bundle(path: str) -> dict:
    """A bundle.json path, or a directory containing one (bundle.json / combined.bundle.json)."""
    p = Path(path)
    if p.is_dir():
        for name in ("bundle.json", "combined.bundle.json"):
            if (p / name).is_file():
                p = p / name
                break
        else:
            raise FileNotFoundError(f"no bundle.json under {path} — run with --bundle to produce one")
    if not p.is_file():
        raise FileNotFoundError(f"no such bundle: {path}")
    b = json.loads(p.read_text())
    if not isinstance(b.get("results"), list) or "suite" not in b:
        raise ValueError(f"{p} is not a result bundle (missing results/suite)")
    return b


def _axis_of(r: dict) -> str:
    """The leaderboard axis this result row belongs to (mirrors api._summarize)."""
    cat = r.get("category") or ""
    if (r.get("verification") or "") == "goal-state-env":
        return "agentic"
    if cat == "planner":
        return "planner"
    if cat == "math":
        return "math"
    if cat == "long-context":
        return "long_ctx"
    if cat in SAFETY:
        return "safety"
    return "code"


def _finals(bundle: dict) -> dict[str, float]:
    """challenge_id -> score.final (last row wins if a bundle ever repeats an id)."""
    return {r["challenge_id"]: float((r.get("score") or {}).get("final", 0.0))
            for r in bundle["results"]}


def _group(bundle: dict, ids: set[str] | None, key) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for r in bundle["results"]:
        if ids is not None and r["challenge_id"] not in ids:
            continue
        out.setdefault(key(r), []).append(float((r.get("score") or {}).get("final", 0.0)))
    return out


def _avg(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 4) if xs else None


def _tok_per_s(bundle: dict) -> float | None:
    xs = sorted(r["tok_per_s"] for r in bundle["results"]
                if isinstance(r.get("tok_per_s"), (int, float)))
    return round(xs[len(xs) // 2], 1) if xs else None   # median — robust to warmup outliers


def _model_line(b: dict) -> str:
    m = b.get("model") or {}
    sha = (m.get("file_sha256") or "")[:12]
    return f"{m.get('family', '?')} {m.get('artifact', '')}".strip() + (f" (sha {sha}…)" if sha else "")


def compare(current: dict, baseline: dict, *, max_drop: float, min_n: int,
            relax: bool = False, gate_categories: bool = False) -> dict:
    """Pure comparison → a verdict dict (rendered by the CLI, or emitted as --json)."""
    cs, bs = current["suite"], baseline["suite"]
    if (cs.get("id"), cs.get("version")) != (bs.get("id"), bs.get("version")):
        return {"comparable": False,
                "reason": f"different suites: {cs.get('id')}@{cs.get('version')} vs "
                          f"{bs.get('id')}@{bs.get('version')} — scores aren't on the same axis"}
    ids: set[str] | None = None
    if cs.get("content_hash") != bs.get("content_hash"):
        if not relax:
            return {"comparable": False,
                    "reason": f"same suite {cs.get('id')}@{cs.get('version')} but different "
                              "content_hash (the challenge set changed between runs). "
                              "Re-baseline, or pass --relax to compare the shared challenges only."}
        # relaxed: intersect by challenge_id, and only where the challenge CONTENT is identical —
        # a same-named challenge with edited tests isn't the same measurement.
        chash_b = {r["challenge_id"]: r.get("challenge_hash") for r in baseline["results"]}
        ids = {r["challenge_id"] for r in current["results"]
               if chash_b.get(r["challenge_id"]) == r.get("challenge_hash")}
        if not ids:
            return {"comparable": False, "reason": "--relax found no shared identical challenges"}

    cur_ax, base_ax = _group(current, ids, _axis_of), _group(baseline, ids, _axis_of)
    cur_cat = _group(current, ids, lambda r: r.get("category") or "other")
    base_cat = _group(baseline, ids, lambda r: r.get("category") or "other")

    def _diff(cur: dict[str, list[float]], base: dict[str, list[float]], gated: bool) -> dict:
        out = {}
        for k in sorted(set(cur) | set(base)):
            c, b = _avg(cur.get(k, [])), _avg(base.get(k, []))
            nc, nb = len(cur.get(k, [])), len(base.get(k, []))
            delta = round(c - b, 4) if (c is not None and b is not None) else None
            gates = gated and nc >= min_n and nb >= min_n and delta is not None
            out[k] = {"baseline": b, "current": c, "delta": delta,
                      "n_baseline": nb, "n_current": nc, "gated": gates,
                      "regressed": bool(gates and delta < -max_drop)}
        return out

    axes = _diff(cur_ax, base_ax, gated=True)
    categories = _diff(cur_cat, base_cat, gated=gate_categories)

    fin_c, fin_b = _finals(current), _finals(baseline)
    shared = (set(fin_c) & set(fin_b)) if ids is None else (ids & set(fin_c) & set(fin_b))
    broke = sorted(i for i in shared if fin_b[i] >= GREEN > fin_c[i])
    fixed = sorted(i for i in shared if fin_c[i] >= GREEN > fin_b[i])

    regressed = sorted([k for k, v in axes.items() if v["regressed"]]
                       + [f"category:{k}" for k, v in categories.items() if v["regressed"]])
    return {
        "comparable": True,
        "suite": {"id": cs.get("id"), "version": cs.get("version"),
                  "relaxed_to_shared": ids is not None,
                  "n_compared": len(shared)},
        "model_current": _model_line(current), "model_baseline": _model_line(baseline),
        "axes": axes, "categories": categories,
        "flips": {"fixed": fixed, "broke": broke},
        "tok_per_s": {"baseline": _tok_per_s(baseline), "current": _tok_per_s(current)},
        "policy": {"max_drop": max_drop, "min_n": min_n},
        "regressed": regressed,
        "ok": not regressed,
    }


def _fmt(v: float | None) -> str:
    return "  —  " if v is None else f"{v:.3f}"


def _render(v: dict) -> str:
    lines = [f"Suite {v['suite']['id']}@{v['suite']['version']}"
             + ("  (relaxed: shared challenges only)" if v["suite"]["relaxed_to_shared"] else "")
             + f"  ·  {v['suite']['n_compared']} shared challenges",
             f"Current:  {v['model_current']}",
             f"Baseline: {v['model_baseline']}", ""]
    rows = [("axis", "baseline", "current", "Δ", "")]
    for table, name in ((v["axes"], None), (v["categories"], "category")):
        for k, a in table.items():
            if name and a["delta"] is None:
                continue   # keep the category table to what's actually comparable
            mark = ("REGRESSED" if a["regressed"]
                    else "" if not a["gated"] and name else
                    "(n<min, not gated)" if not a["gated"] else "ok")
            d = "  —  " if a["delta"] is None else f"{a['delta']:+.3f}"
            label = f"{name}:{k}" if name else k
            rows.append((label, _fmt(a["baseline"]), _fmt(a["current"]), d, mark))
    w = [max(len(r[i]) for r in rows) for i in range(5)]
    for i, r in enumerate(rows):
        lines.append("  " + "  ".join(s.ljust(w[j]) for j, s in enumerate(r)).rstrip())
        if i == 0:
            lines.append("  " + "-" * (sum(w) + 8))
    f = v["flips"]
    if f["fixed"] or f["broke"]:
        lines.append("")
        if f["fixed"]:
            lines.append(f"  fixed ({len(f['fixed'])}): " + ", ".join(f["fixed"][:10])
                         + (" …" if len(f["fixed"]) > 10 else ""))
        if f["broke"]:
            lines.append(f"  broke ({len(f['broke'])}): " + ", ".join(f["broke"][:10])
                         + (" …" if len(f["broke"]) > 10 else ""))
    t = v["tok_per_s"]
    if t["baseline"] and t["current"]:
        lines.append(f"\n  tok/s (median, informational): {t['baseline']} -> {t['current']}")
    lines.append("")
    if v["ok"]:
        lines.append(f"OK — no axis dropped more than {v['policy']['max_drop']:.3f}.")
    else:
        lines.append(f"REGRESSION — beyond {v['policy']['max_drop']:.3f} on: "
                     + ", ".join(v["regressed"]))
    return "\n".join(lines)


def check_main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="peakstone check",
        description="CI regression gate: compare a run's bundle against a baseline bundle and exit "
                    "non-zero if any capability axis regressed. Both runs must be on the same "
                    "(suite, version) — e.g. two `peakstone bench --level standard` runs.")
    ap.add_argument("current", help="the new run: a bundle.json, or a run dir containing one")
    ap.add_argument("--against", required=True, metavar="BASELINE",
                    help="the baseline run: a bundle.json, or a run dir containing one")
    ap.add_argument("--max-drop", type=float, default=0.02,
                    help="absolute score drop per axis that counts as a regression (default 0.02)")
    ap.add_argument("--min-n", type=int, default=5,
                    help="gate an axis only when both runs have >= this many results on it "
                         "(smaller axes are reported, not gated; default 5)")
    ap.add_argument("--gate-categories", action="store_true",
                    help="also gate every per-category score (same --max-drop/--min-n), not just "
                         "the top-level axes")
    ap.add_argument("--relax", action="store_true",
                    help="allow a content_hash mismatch by comparing only the shared, "
                         "content-identical challenges (default: refuse — re-baseline instead)")
    ap.add_argument("--json", action="store_true", help="emit the verdict as JSON")
    args = ap.parse_args(argv)

    try:
        current, baseline = _load_bundle(args.current), _load_bundle(args.against)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"!! {e}", file=sys.stderr)
        return 2

    v = compare(current, baseline, max_drop=args.max_drop, min_n=args.min_n,
                relax=args.relax, gate_categories=args.gate_categories)
    if args.json:
        print(json.dumps(v, indent=2))
    elif not v["comparable"]:
        print(f"!! not comparable: {v['reason']}", file=sys.stderr)
    else:
        print(_render(v))
    if not v["comparable"]:
        return 2
    return 0 if v["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(check_main())
