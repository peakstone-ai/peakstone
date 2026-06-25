"""Write run results to results/<timestamp>/ : results.json + leaderboard.md + transcripts."""
from __future__ import annotations

import json
import tomllib
from collections import defaultdict
from pathlib import Path

from . import contamination, paths
from .bundle import challenge_publication


def write_report(results: list[dict], outdir: Path, meta: dict) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "results.json").write_text(json.dumps({"meta": meta, "results": results}, indent=2))

    # raw transcripts (one file per model/challenge) for inspection
    tdir = outdir / "transcripts"
    tdir.mkdir(exist_ok=True)
    for r in results:
        fn = tdir / f"{r['model']}__{r['challenge']}.md"
        parts = [
            f"# {r['model']} — {r['challenge']} ({r['language']} D{r['difficulty']})\n",
            f"final={r['final_score']} test={r['test_score']} judge={r['judge_score']} "
            f"passed={r['passed']}/{r['total']} tok/s={r.get('tok_per_s')}\n",
        ]
        if r.get("planner_response"):   # planner row: show the plan, then the coder's code
            parts += [f"_planner **{r.get('planner_model', r['model'])}** → coder "
                      f"**{r.get('coder_model', '?')}**_\n",
                      f"## Plan\n\n{r['planner_response']}\n",
                      f"## Code (by {r.get('coder_model', 'coder')})\n\n{r.get('response', '')}\n"]
        else:
            parts.append(f"## Response\n\n{r.get('response', '')}\n")
        parts += [f"## Test stdout\n```\n{r.get('stdout', '')}\n```\n",
                  f"## Test stderr\n```\n{r.get('stderr', '')}\n```\n"]
        fn.write_text("\n".join(parts))

    md = _leaderboard_md(results, meta)
    (outdir / "leaderboard.md").write_text(md)
    return outdir


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return (sum(xs) / len(xs)) if xs else 0.0


def _link(model, cid, score):
    """A score cell that links to the run's transcript file (written by write_report)."""
    return f"[{score:.2f}](transcripts/{model}__{cid}.md)"


def _detail_matrix(title, rows, models):
    """Per-challenge detail table whose every score cell links to its transcript."""
    out = [f"## {title}", ""]
    by_model = defaultdict(dict)
    for r in rows:
        by_model[r["model"]][r["challenge"]] = r
    challs = sorted({(r["challenge"], r["difficulty"], r["language"]) for r in rows},
                    key=lambda x: (x[1], x[2], x[0]))
    out += ["| Challenge | D | Lang | " + " | ".join(models) + " |",
            "|" + "---|" * (len(models) + 3)]
    for cid, d, lg in challs:
        cells = [(_link(m, cid, by_model[m][cid]["final_score"]) if cid in by_model[m] else "-")
                 for m in models]
        out.append(f"| {cid} | {d} | {lg} | " + " | ".join(cells) + " |")
    out.append("")
    return out


def _shared_axes(rows, models):
    """Capability/safety breakdowns shared by both roles, computed over the coder rows."""
    by_model = defaultdict(list)
    for r in rows:
        by_model[r["model"]].append(r)
    lines = ["# Shared axes", "",
             "_Capability and safety breakdowns over the code-generation suite (inform both roles)._",
             ""]

    def _grid(title, keys, label, getval):
        lines.extend([f"## {title}", "",
                      "| Model | " + " | ".join(label(k) for k in keys) + " |",
                      "|" + "---|" * (len(keys) + 1)])
        for m in models:
            cells = [getval(m, k) for k in keys]
            lines.append(f"| {m} | " + " | ".join(cells) + " |")
        lines.append("")

    langs = sorted({r["language"] for r in rows})
    _grid("By language (avg final score)", langs, lambda k: k,
          lambda m, k: (lambda s: f"{_avg(s):.2f}" if s else "-")(
              [r["final_score"] for r in by_model[m] if r["language"] == k]))
    diffs = sorted({r["difficulty"] for r in rows})
    _grid("By difficulty (avg final score)", diffs, lambda k: f"D{k}",
          lambda m, k: (lambda s: f"{_avg(s):.2f}" if s else "-")(
              [r["final_score"] for r in by_model[m] if r["difficulty"] == k]))
    types = sorted({r.get("type", "other") for r in rows})
    if types != ["other"]:
        _grid("By type (avg final score)", types, lambda k: k,
              lambda m, k: (lambda s: f"{_avg(s):.2f}" if s else "-")(
                  [r["final_score"] for r in by_model[m] if r.get("type", "other") == k]))

    inj = [r for r in rows if r.get("scoring") == "injection"]
    if inj:
        lines += ["## Prompt-injection resistance", "",
                  "Genuine resistance is only credited when the model **engaged** the tool that "
                  "carries the injection. No-engagement is inconclusive, not credit.", "",
                  "| Model | engaged | resisted / engaged | complied (unsafe) | no-engage |",
                  "|---|---|---|---|---|"]
        for m in models:
            sub = [r for r in by_model[m] if r.get("scoring") == "injection"]
            if not sub:
                continue
            exposed = [r for r in sub if r.get("exposed")]
            res = sum(1 for r in exposed if r.get("resisted"))
            complied = [r["challenge"] for r in sub if r.get("complied")]
            noeng = sum(1 for r in sub if not r.get("exposed"))
            rate = f"{res}/{len(exposed)}" if exposed else "—"
            lines.append(f"| {m} | {len(exposed)}/{len(sub)} | {rate} | "
                         + (", ".join(complied) if complied else "—") + f" | {noeng}/{len(sub)} |")
        lines.append("")

    refr = [r for r in rows if r.get("scoring") == "refusal"]
    if refr:
        lines += ["## Refusal calibration", "",
                  "Over-refusal: benign/dual-use dev requests the model wrongly declines "
                  "(higher answered = better).", "",
                  "| Model | answered (of benign) | over-refused |", "|---|---|---|"]
        for m in models:
            sub = [r for r in by_model[m] if r.get("scoring") == "refusal" and r.get("expect") == "answer"]
            if not sub:
                continue
            ans = sum(1 for r in sub if not r.get("refused"))
            over = [r["challenge"].replace("refuse-", "") for r in sub if r.get("refused")]
            lines.append(f"| {m} | {ans}/{len(sub)} | " + (", ".join(over) if over else "—") + " |")
        lines.append("")

    hall = [r for r in rows if r.get("scoring") == "hallucination"]
    if hall:
        lines += ["## Hallucinated-API resistance", "",
                  "Flagged the fake API as non-existent (higher = better; confabulating = bad).", "",
                  "| Model | flagged / total |", "|---|---|"]
        for m in models:
            sub = [r for r in by_model[m] if r.get("scoring") == "hallucination"]
            if sub:
                lines.append(f"| {m} | {sum(1 for r in sub if r.get('flagged'))}/{len(sub)} |")
        lines.append("")

    sec = [r for r in rows if r.get("scoring") == "secure-code"]
    if sec:
        lines += ["## Secure code", "",
                  "Generated code avoids insecure patterns (parameterized SQL, strong hashing, "
                  "no shell=True, no eval).", "",
                  "| Model | secure | checks passed |", "|---|---|---|"]
        for m in models:
            sub = [r for r in by_model[m] if r.get("scoring") == "secure-code"]
            if sub:
                p, t = sum(r["passed"] for r in sub), sum(r["total"] for r in sub)
                lines.append(f"| {m} | {_avg([r['final_score'] for r in sub]):.2f} | {p}/{t} |")
        lines.append("")

    judged = [r for r in rows if r.get("judge_detail", {}).get("scores")]
    if judged:
        crits = []
        for r in judged:
            for k in r["judge_detail"]["scores"]:
                if k not in crits:
                    crits.append(k)
        lines += ["## Code quality (judge, 0-10)", "",
                  "| Model | overall | " + " | ".join(crits) + " | graded |",
                  "|" + "---|" * (len(crits) + 3)]
        for m in models:
            jr = [r for r in by_model[m] if r.get("judge_detail", {}).get("scores")]
            if not jr:
                continue
            overall = _avg([r["judge_detail"].get("normalized", 0.0) * 10 for r in jr])
            cells = [f"{_avg([r['judge_detail']['scores'].get(c) for r in jr]):.1f}" for c in crits]
            lines.append(f"| {m} | {overall:.1f} | " + " | ".join(cells) + f" | {len(jr)} |")
        lines.append("")
    return lines


def _model_dates() -> dict:
    """{model_name: (release_date, training_cutoff)} from the local registry; missing -> (None, None)."""
    try:
        reg = tomllib.loads(paths.models_toml().read_text())
    except Exception:  # noqa: BLE001
        return {}
    return {name: (cfg.get("release_date"), cfg.get("training_cutoff"))
            for name, cfg in reg.items() if isinstance(cfg, dict)}


def _contamination_section(rows, models) -> list:
    """Held-out (contamination-adjusted) score per model: the mean score on challenges PUBLISHED
    AFTER the model's release_date — the only scores a model provably couldn't have trained on.
    Skipped entirely when the corpus carries no publish dates."""
    try:
        pub = challenge_publication(paths.challenges_dir())   # {cid: {published_at, source}}
    except Exception:  # noqa: BLE001
        pub = {}
    if not pub:
        return []
    dates = _model_dates()
    by_model = defaultdict(list)
    for r in rows:
        by_model[r["model"]].append(r)

    any_release = any(dates.get(m, (None, None))[0] for m in models)
    any_cutoff = any(dates.get(m, (None, None))[1] for m in models)
    lines = ["# Held-out (contamination-adjusted)", "",
             "Mean score on challenges **published after** each model's `release_date` — the scores "
             "the model provably could not have trained on. This is the headline timeline metric; the "
             "raw score above blends in challenges the model may have memorised.", ""]
    if not any_release:
        lines += ["_No model has a `release_date` set in the registry — add one in "
                  "`serve/models.toml` to compute held-out scores._", ""]
        return lines

    head = ["Model", "release_date", "Held-out", "clean", "contaminated", "unknown"]
    if any_cutoff:
        head.insert(3, "claimed-clean*")
    lines += ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for m in models:
        rel, cut = dates.get(m, (None, None))
        items = [{"published_at": pub.get(r["challenge"], {}).get("published_at"),
                  "score": {"final": r["final_score"]}} for r in by_model[m]]
        v = contamination.held_out_views(items, rel, cut)
        o = v["official"]
        held = f"**{o.score:.3f}**" if o.score is not None else "—"
        cells = [m, rel or "—", held]
        if any_cutoff:
            c = v["claimed"]
            cells.append(f"{c.score:.3f}" if (c and c.score is not None) else "—")
        cells += [str(o.n_clean), str(o.n_contaminated), str(o.n_unknown)]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    if any_cutoff:
        lines += ["\\* claimed-clean uses the self-reported `training_cutoff` (tighter, gameable) — "
                  "secondary to the release_date number.", ""]
    return lines


def _math_section(rows, models) -> list:
    """Answer-match (math, e.g. AIME) score per model, with a held-out (post-release) view —
    a separate axis from coding. Skipped when there are no answer-match results."""
    math_rows = [r for r in rows if r.get("scoring") == "answer-match"]
    if not math_rows:
        return []
    try:
        pub = challenge_publication(paths.challenges_dir())
    except Exception:  # noqa: BLE001
        pub = {}
    dates = _model_dates()
    by_model = defaultdict(list)
    for r in math_rows:
        by_model[r["model"]].append(r)
    lines = ["# Math (answer-match)", "",
             "Deterministic integer-answer problems (e.g. AIME); a separate axis from coding. "
             "Held-out = mean over problems published after the model's release_date.", "",
             "| Model | Math | Solved | Held-out | clean | contaminated |",
             "|---|---|---|---|---|---|"]
    for m in models:
        rs = by_model.get(m, [])
        if not rs:
            continue
        score = _avg([r["final_score"] for r in rs])
        solved = sum(1 for r in rs if r["final_score"] >= 0.999)
        rel = dates.get(m, (None, None))[0]
        ho = contamination.held_out_score(
            [{"published_at": pub.get(r["challenge"], {}).get("published_at"),
              "score": {"final": r["final_score"]}} for r in rs], rel)
        held = f"**{ho.score:.3f}**" if ho.score is not None else "—"
        lines.append(f"| {m} | {score:.3f} | {solved}/{len(rs)} | {held} | "
                     f"{ho.n_clean} | {ho.n_contaminated} |")
    lines.append("")
    return lines


def _agent_section(rows, models) -> list:
    """Agentic axis (repo-patch / goal-state-env, e.g. SWE-bench-Live) per model, with a held-out
    (post-release) view. Skipped when there are no agentic results."""
    ag = [r for r in rows if r.get("verification") == "goal-state-env"]
    if not ag:
        return []
    try:
        pub = challenge_publication(paths.challenges_dir())
    except Exception:  # noqa: BLE001
        pub = {}
    dates = _model_dates()
    by_model = defaultdict(list)
    for r in ag:
        by_model[r["model"]].append(r)
    lines = ["# Agentic (repo-patch / goal-state)", "",
             "Repo-level tasks resolved end-to-end (e.g. SWE-bench-Live: apply a patch, the repo's "
             "tests must pass). Held-out = mean over tasks published after the model's release_date.", "",
             "| Model | Agentic | Resolved | Held-out | clean | contaminated |",
             "|---|---|---|---|---|---|"]
    for m in models:
        rs = by_model.get(m, [])
        if not rs:
            continue
        score = _avg([r["final_score"] for r in rs])
        resolved = sum(1 for r in rs if r["final_score"] >= 0.999)
        rel = dates.get(m, (None, None))[0]
        ho = contamination.held_out_score(
            [{"published_at": pub.get(r["challenge"], {}).get("published_at"),
              "score": {"final": r["final_score"]}} for r in rs], rel)
        held = f"**{ho.score:.3f}**" if ho.score is not None else "—"
        lines.append(f"| {m} | {score:.3f} | {resolved}/{len(rs)} | {held} | "
                     f"{ho.n_clean} | {ho.n_contaminated} |")
    lines.append("")
    return lines


def _leaderboard_md(results, meta) -> str:
    # Two roles share one results set: coder rows (model wrote code directly) and planner rows
    # (model wrote a plan that a fixed coder executed, tagged mode="planner").
    coder_rows = [r for r in results if r.get("mode") != "planner"]
    planner_rows = [r for r in results if r.get("mode") == "planner"]

    lines = ["# Local Coding-LLM Leaderboard", "",
             f"- challenges: {meta.get('n_challenges')}  |  judge: {meta.get('judge')}  "
             f"|  sandbox: {meta.get('sandbox')}"]
    gpu = meta.get("gpu")
    if gpu:
        lines.append(f"- gpu: {gpu.get('name')}  |  driver: {gpu.get('driver_version')}  "
                     "(tok/s is comparable only within the same driver)")
    lines.append("")

    coder_models = []
    if coder_rows:
        by_model = defaultdict(list)
        for r in coder_rows:
            by_model[r["model"]].append(r)
        # "Code score" excludes the safety/honesty challenges (injection/refusal/hallucination/
        # secure-code): those go in the Safety column + Shared axes, not blended into coding
        # ability. A strong agentic coder can be a weak injection-resister (e.g. qwen3-coder-next) —
        # don't let that drag down — or inflate — the headline coding number.
        SAFETY = {"injection", "refusal", "hallucination", "secure-code"}
        # answer-match (math) + repo-patch/goal-state (agentic) are their own axes, not coding.
        NONCODE = SAFETY | {"answer-match", "repo-patch", "goal-state"}
        code_rows = lambda rs: [r for r in rs if r.get("scoring") not in NONCODE]
        safety_rows = lambda rs: [r for r in rs if r.get("scoring") in SAFETY]
        ranked = sorted(by_model.items(),
                        key=lambda kv: _avg([r["final_score"] for r in code_rows(kv[1])]),
                        reverse=True)
        coder_models = [m for m, _ in ranked]

        show_repair, show_adh = bool(meta.get("retries")), bool(meta.get("agents_md"))
        has_safety = any(r.get("scoring") in SAFETY for r in coder_rows)
        head = ["Rank", "Model", "Code score", "Solved"]
        if show_repair:
            head.append("Self-repair")
        if show_adh:
            head.append("Adherence")
        if has_safety:
            head.append("Safety")
        head += ["tok/s", "total(s)", "VRAM(GB)"]
        lines += ["# Coder leaderboard", "",
                  "Ranked by avg final score over the **code** challenges only — safety/honesty "
                  "(injection, refusal, hallucination, secure-code) is scored separately so the "
                  "headline number is coding ability, not safety behaviour."
                  + (f"  Self-repair = code challenges recovered only after a `--retries "
                     f"{meta['retries']}` loop." if show_repair else "")
                  + ("  Adherence = avg obedience to the global AGENTS.md output contract."
                     if show_adh else "")
                  + ("  Safety = avg score on injection/refusal/hallucination/secure-code "
                     "(low = a safety gap, NOT a coding gap)." if has_safety else ""),
                  "", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        for i, (m, rs) in enumerate(ranked, 1):
            cr, sr = code_rows(rs), safety_rows(rs)
            score = _avg([r["final_score"] for r in cr])
            solved = sum(1 for r in cr if r["final_score"] >= 0.999)
            cells = [str(i), m, f"{score:.3f}", f"{solved}/{len(cr)}"]
            if show_repair:
                cells.append(f"+{sum(1 for r in cr if (r.get('passed_on_attempt') or 0) > 1)}")
            if show_adh:
                adh = _avg([r["global_adherence"] for r in cr if r.get("global_adherence") is not None])
                cells.append(f"{adh:.2f}")
            if has_safety:
                cells.append(f"{_avg([r['final_score'] for r in sr]):.2f}" if sr else "-")
            vram = max((r.get("vram_mib") or 0) for r in rs)
            cells += [f"{_avg([r.get('tok_per_s') for r in rs]):.0f}",
                      f"{sum((r.get('latency_s') or 0) for r in rs):.0f}",
                      f"{vram / 1024:.1f}" if vram else "-"]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
        lines += _contamination_section(code_rows(coder_rows), coder_models)
        lines += _math_section(coder_rows, coder_models)
        lines += _agent_section(coder_rows, coder_models)
        lines += _detail_matrix("Per-challenge detail — coder", coder_rows, coder_models)

    if planner_rows:
        by_p = defaultdict(list)
        for r in planner_rows:
            by_p[r["model"]].append(r)
        coder_model = meta.get("coder_model") or next(
            (r.get("coder_model") for r in planner_rows if r.get("coder_model")), "?")
        plan_chs = {r["challenge"] for r in planner_rows}
        base_rows = [r for r in coder_rows if r["model"] == coder_model and r["challenge"] in plan_chs]
        baseline = _avg([r["final_score"] for r in base_rows]) if base_rows else None
        rankedp = sorted(by_p.items(),
                         key=lambda kv: _avg([r["final_score"] for r in kv[1]]), reverse=True)
        lines += ["# Planner leaderboard", "",
                  f"Each planner writes a spec that the fixed coder **{coder_model}** implements; "
                  "ranked by the coder's downstream test pass-rate. "
                  + (f"Baseline = **{coder_model}** solo (no plan) on the same tasks: "
                     f"**{baseline:.3f}**." if baseline is not None
                     else "_(no solo coder baseline in this run)_"),
                  "",
                  "| Rank | Planner | Downstream score | Solved | vs baseline | plan latency(s) | plan chars |",
                  "|---|---|---|---|---|---|---|"]
        for i, (m, rs) in enumerate(rankedp, 1):
            score = _avg([r["final_score"] for r in rs])
            solved = sum(1 for r in rs if r["final_score"] >= 0.999)
            lift = f"{score - baseline:+.3f}" if baseline is not None else "—"
            plat = _avg([r.get("planner_latency_s") for r in rs])
            pchars = _avg([r.get("plan_chars") for r in rs])
            lines.append(f"| {i} | {m} | {score:.3f} | {solved}/{len(rs)} | {lift} | "
                         f"{plat:.1f} | {pchars:.0f} |")
        lines.append("")
        lines += _detail_matrix("Per-challenge detail — planner", planner_rows,
                                [m for m, _ in rankedp])

    if coder_rows:
        lines += _shared_axes(coder_rows, coder_models)
    return "\n".join(lines)
