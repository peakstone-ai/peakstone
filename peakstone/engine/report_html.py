"""Generate a standalone HTML report from a benchmark run + its judge passes.

  python -m engine.report_html results/bench-XXXX [--out report.html]

Reads <bench>/combined/results.json (the model x challenge run) plus any
<bench>/judged-<judge>-*/results.json passes, and emits a single self-contained HTML file.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from collections import defaultdict
from pathlib import Path


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0


def _load(p):
    return json.load(open(p))["results"]


def _heat(v):  # 0..1 -> red..green
    r = int(220 * (1 - v)) + 20
    g = int(180 * v) + 40
    return f"background:rgb({r},{g},60);color:#fff;"


def _bar(v, vmax=1.0):
    pct = max(2, int(100 * v / vmax))
    return (f'<div class="bar"><div class="fill" style="width:{pct}%"></div>'
            f'<span>{v:.3f}</span></div>')


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("bench")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    bench = Path(args.bench)
    all_rows = _load(bench / "combined" / "results.json")
    _cmeta = json.load(open(bench / "combined" / "results.json")).get("meta", {})
    gpu = _cmeta.get("gpu") or {}
    # The HTML view covers the CODER role; planner rows (mode="planner") are reported in the
    # markdown Planner leaderboard. Keep only coder rows so the tables below stay coherent.
    planner_rows = [r for r in all_rows if r.get("mode") == "planner"]
    rows = [r for r in all_rows if r.get("mode") != "planner"]

    judges = {}
    for d in sorted(glob.glob(str(bench / "judged-*"))):
        name = Path(d).name.split("judged-", 1)[1].rsplit("-", 2)[0]
        f = Path(d) / "results.json"
        if f.exists():
            judges[name] = {(r["model"], r["challenge"]): r for r in _load(f)
                            if r.get("judge_detail", {}).get("scores")}

    by_model = defaultdict(list)
    for r in rows:
        by_model[r["model"]].append(r)
    models = sorted(by_model, key=lambda m: -_avg([r["final_score"] for r in by_model[m]]))
    types = sorted({r.get("type", "other") for r in rows})

    H = []
    H.append("""<!doctype html><html><head><meta charset="utf-8">
<title>Local Coding-LLM Benchmark — RTX 4090</title>
<style>
:root{--bg:#0f1117;--card:#181b24;--ink:#e6e8ee;--mut:#9aa3b2;--line:#2a2f3a;--acc:#5b9cff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;padding:0 0 60px}
.wrap{max-width:1080px;margin:0 auto;padding:0 20px}
header{background:linear-gradient(120deg,#1a2235,#11151f);padding:38px 0;border-bottom:1px solid var(--line)}
h1{margin:0 0 6px;font-size:28px}h2{margin:34px 0 12px;font-size:21px;border-bottom:1px solid var(--line);padding-bottom:6px}
h3{margin:22px 0 8px;font-size:16px;color:var(--mut)}
.sub{color:var(--mut)}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:14px}
th,td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
td.num{text-align:right;font-variant-numeric:tabular-nums}
tr:hover td{background:#1d212c}
.bar{position:relative;background:#222734;border-radius:4px;height:20px;min-width:120px}
.bar .fill{position:absolute;left:0;top:0;bottom:0;background:linear-gradient(90deg,#3b6,#6cf);border-radius:4px}
.bar span{position:relative;padding-left:6px;font-variant-numeric:tabular-nums;font-size:12px;line-height:20px}
.heat{text-align:center;font-variant-numeric:tabular-nums;border-radius:3px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 20px;margin:14px 0}
.pill{display:inline-block;padding:1px 8px;border-radius:20px;font-size:12px;background:#243049;color:#9cf;margin-right:5px}
.bad{color:#ff7b7b;font-weight:600}.good{color:#76e0a3;font-weight:600}
.rank1 td:first-child{border-left:3px solid gold}
code{background:#222734;padding:1px 5px;border-radius:4px;font-size:13px}
.foot{color:var(--mut);font-size:13px;margin-top:30px;border-top:1px solid var(--line);padding-top:14px}
ul{margin:6px 0}li{margin:3px 0}
</style></head><body>""")

    H.append('<header><div class="wrap"><h1>Local Coding-LLM Benchmark</h1>'
             '<div class="sub">10 models &middot; 48 challenges &middot; 6 capability axes &middot; '
             + (f"{gpu['name']} &middot; driver {gpu['driver_version']} &middot; "
                if gpu else "single RTX 4090 (24&nbsp;GB) &middot; ")
             + 'llama.cpp</div></div></header><div class="wrap">')

    # intro
    H.append('<div class="card"><b>What this is.</b> Every model is served locally via '
             '<code>llama-server</code> and scored on automated tests (code correctness), library '
             'usage, tool-calling, self-repair (retries), and prompt-injection resistance. Code '
             'quality is additionally graded by two judges: the local <code>qwen3-coder</code> '
             '(blind) and <code>claude</code> (grounded in the real test outcomes).</div>')

    # overall
    H.append("<h2>Coder ranking</h2><table><tr><th>#</th><th>Model</th><th>Code score</th>"
             "<th class='num'>Solved</th><th class='num'>tok/s</th><th class='num'>VRAM</th></tr>")
    for i, m in enumerate(models, 1):
        rs = by_model[m]
        sc = _avg([r["final_score"] for r in rs])
        solved = sum(1 for r in rs if r["final_score"] >= 0.999)
        tps = _avg([r.get("tok_per_s") for r in rs])
        vram = max((r.get("vram_mib") or 0) for r in rs)
        cls = ' class="rank1"' if i == 1 else ""
        H.append(f"<tr{cls}><td class='num'>{i}</td><td><b>{m}</b></td><td>{_bar(sc)}</td>"
                 f"<td class='num'>{solved}/{len(rs)}</td><td class='num'>{tps:.0f}</td>"
                 f"<td class='num'>{vram/1024:.1f} GB</td></tr>")
    H.append("</table>")

    # planner ranking (plan -> fixed coder -> tests), when present
    if planner_rows:
        pbm = defaultdict(list)
        for r in planner_rows:
            pbm[r["model"]].append(r)
        coder_model = _cmeta.get("coder_model") or next(
            (r.get("coder_model") for r in planner_rows if r.get("coder_model")), "?")
        plan_chs = {r["challenge"] for r in planner_rows}
        base = [r for r in rows if r["model"] == coder_model and r["challenge"] in plan_chs]
        baseline = _avg([r["final_score"] for r in base]) if base else None
        H.append(f"<h2>Planner ranking</h2><div class='sub'>Each planner writes a spec that the "
                 f"fixed coder <code>{coder_model}</code> implements; ranked by downstream test "
                 f"pass-rate"
                 + (f" (solo baseline {baseline:.3f})" if baseline is not None else "") + ".</div>")
        H.append("<table><tr><th>#</th><th>Planner</th><th>Downstream</th>"
                 "<th class='num'>Solved</th><th class='num'>vs base</th>"
                 "<th class='num'>plan s</th></tr>")
        for i, (m, rs) in enumerate(sorted(pbm.items(),
                                    key=lambda kv: -_avg([r["final_score"] for r in kv[1]])), 1):
            sc = _avg([r["final_score"] for r in rs])
            solved = sum(1 for r in rs if r["final_score"] >= 0.999)
            lift = f"{sc - baseline:+.3f}" if baseline is not None else "—"
            plat = _avg([r.get("planner_latency_s") for r in rs])
            cls = ' class="rank1"' if i == 1 else ""
            H.append(f"<tr{cls}><td class='num'>{i}</td><td><b>{m}</b></td><td>{_bar(sc)}</td>"
                     f"<td class='num'>{solved}/{len(rs)}</td><td class='num'>{lift}</td>"
                     f"<td class='num'>{plat:.1f}</td></tr>")
        H.append("</table>")

    # by type heatmap
    H.append("<h2>Capability by type</h2><table><tr><th>Model</th>"
             + "".join(f"<th>{t}</th>" for t in types)
             + "<th>s/answer</th><th>VRAM&nbsp;GB</th></tr>")
    for m in models:
        H.append(f"<tr><td><b>{m}</b></td>")
        for t in types:
            sub = [r["final_score"] for r in by_model[m] if r.get("type") == t]
            if sub:
                v = _avg(sub)
                H.append(f"<td class='heat' style='{_heat(v)}'>{v:.2f}</td>")
            else:
                H.append("<td class='heat'>-</td>")
        tps = _avg([r.get("tok_per_s") for r in by_model[m]])
        ctoks = [r.get("completion_tokens") for r in by_model[m] if (r.get("completion_tokens") or 0) > 0]
        tsol = _avg(ctoks)
        secs = f"{tsol / tps:.1f}" if (tps and tsol) else "-"
        vram = max((r.get("vram_mib") or 0) for r in by_model[m])
        vram_s = f"{vram/1024:.1f}" if vram else "-"
        H.append(f"<td class='num'>{secs}</td><td class='num'>{vram_s}</td></tr>")
    H.append("</table><div class='sub'>Red = weak, green = strong. <b>s/answer</b> = average "
             "seconds to produce one answer = (tokens per solution) &divide; (tok/s) = 1/speed "
             "&mdash; captures both slow generation and verbosity, so a fast-but-rambling model "
             "looks slow; <b>lower is better</b>. <b>VRAM&nbsp;GB</b> = loaded footprint (lower "
             "better, 24&nbsp;GB available). RTX 4090.</div>")

    # by programming language (code challenges only) + per-model strength/weakness
    code_langs = ["python", "javascript", "typescript", "go", "rust"]
    langs_present = [lg for lg in code_langs if any(r.get("language") == lg for r in rows)]
    if langs_present:
        H.append("<h2>Performance by language</h2>"
                 "<table><tr><th>Model</th>" + "".join(f"<th>{lg}</th>" for lg in langs_present)
                 + "<th>excels at</th><th>weak at</th></tr>")
        for m in models:
            cells, scores = [], {}
            for lg in langs_present:
                sub = [r["final_score"] for r in by_model[m] if r.get("language") == lg]
                if sub:
                    v = _avg(sub)
                    scores[lg] = v
                    cells.append(f"<td class='heat' style='{_heat(v)}'>{v:.2f}</td>")
                else:
                    cells.append("<td class='heat'>-</td>")
            if scores:
                best = max(scores, key=scores.get)
                worst = min(scores, key=scores.get)
                best_s = f"<span class='good'>{best} ({scores[best]:.2f})</span>"
                # only call out a weakness if it's actually weak / clearly below the best
                worst_s = (f"<span class='bad'>{worst} ({scores[worst]:.2f})</span>"
                           if scores[worst] < 0.9 and scores[worst] < scores[best] - 0.05
                           else "<span class='sub'>none notable</span>")
            else:
                best_s = worst_s = "—"
            H.append(f"<tr><td><b>{m}</b></td>" + "".join(cells)
                     + f"<td>{best_s}</td><td>{worst_s}</td></tr>")
        H.append("</table><div class='sub'>Programming languages only (tool/agentic/text "
                 "challenges excluded). 'excels / weak' = each model's highest- and "
                 "lowest-scoring language (weakness shown only when notably below its best).</div>")

    # injection
    H.append("<h2>Prompt-injection resistance</h2>"
             "<div class='sub'>Resistance is only credited when the model actually engaged the "
             "tool carrying the injection. No-engagement = inconclusive (the Qwen2.5-Coder family "
             "can't tool-call, so they're not credited as 'safe').</div>"
             "<table><tr><th>Model</th><th>Engaged</th><th>Resisted / engaged</th>"
             "<th>Complied (unsafe)</th><th>No-engage</th></tr>")
    for m in models:
        sub = [r for r in by_model[m] if r.get("scoring") == "injection"]
        if not sub:
            continue
        exp = [r for r in sub if r.get("exposed")]
        res = sum(1 for r in exp if r.get("resisted"))
        comp = [r["challenge"].replace("inject-", "") for r in sub if r.get("complied")]
        noeng = sum(1 for r in sub if not r.get("exposed"))
        rate = f"{res}/{len(exp)}" if exp else "—"
        cc = f"<span class='bad'>{', '.join(comp)}</span>" if comp else "—"
        H.append(f"<tr><td><b>{m}</b></td><td>{len(exp)}/{len(sub)}</td><td>{rate}</td>"
                 f"<td>{cc}</td><td>{noeng}/{len(sub)}</td></tr>")
    H.append("</table>")

    # agentic
    H.append("<h2>Agentic self-repair</h2><table><tr><th>Model</th><th>Solved (green)</th>"
             "<th class='num'>avg turns&rarr;green</th><th class='num'>avg test-runs</th></tr>")
    for m in models:
        sub = [r for r in by_model[m] if r.get("scoring") == "agentic"]
        if not sub:
            continue
        greens = [r for r in sub if r.get("green")]
        ttg = _avg([r.get("turns_to_green") for r in greens]) if greens else 0
        runs = _avg([r.get("test_runs") for r in sub])
        H.append(f"<tr><td><b>{m}</b></td><td>{len(greens)}/{len(sub)}</td>"
                 f"<td class='num'>{ttg:.1f}</td><td class='num'>{runs:.1f}</td></tr>")
    H.append("</table>")

    # refusal (over-refusal)
    if any(r.get("scoring") == "refusal" for r in rows):
        H.append("<h2>Refusal calibration (over-refusal)</h2><div class='sub'>Benign/dual-use dev "
                 "requests the model wrongly declines — higher answered = better.</div>"
                 "<table><tr><th>Model</th><th>Answered (of benign)</th><th>Over-refused</th></tr>")
        for m in models:
            sub = [r for r in by_model[m] if r.get("scoring") == "refusal" and r.get("expect") == "answer"]
            if not sub:
                continue
            ans = sum(1 for r in sub if not r.get("refused"))
            over = [r["challenge"].replace("refuse-", "") for r in sub if r.get("refused")]
            cc = f"<span class='bad'>{', '.join(over)}</span>" if over else "—"
            H.append(f"<tr><td><b>{m}</b></td><td>{ans}/{len(sub)}</td><td>{cc}</td></tr>")
        H.append("</table>")

    # hallucinated-API resistance
    if any(r.get("scoring") == "hallucination" for r in rows):
        H.append("<h2>Hallucinated-API resistance</h2><div class='sub'>Asked to use a fake API — "
                 "did it flag it as non-existent (good) or confabulate usage (bad)?</div>"
                 "<table><tr><th>Model</th><th>Flagged fake / total</th></tr>")
        for m in models:
            sub = [r for r in by_model[m] if r.get("scoring") == "hallucination"]
            if not sub:
                continue
            fl = sum(1 for r in sub if r.get("flagged"))
            cls = "good" if fl == len(sub) else ("bad" if fl == 0 else "")
            H.append(f"<tr><td><b>{m}</b></td><td class='{cls}'>{fl}/{len(sub)}</td></tr>")
        H.append("</table>")

    # secure code
    if any(r.get("scoring") == "secure-code" for r in rows):
        H.append("<h2>Secure code</h2><div class='sub'>Generated code avoids insecure patterns "
                 "(parameterized SQL, strong hashing, no shell=True, no eval).</div>"
                 "<table><tr><th>Model</th><th>Secure</th><th>Checks passed</th></tr>")
        for m in models:
            sub = [r for r in by_model[m] if r.get("scoring") == "secure-code"]
            if not sub:
                continue
            p = sum(r["passed"] for r in sub)
            t = sum(r["total"] for r in sub)
            H.append(f"<tr><td><b>{m}</b></td><td>{_avg([r['final_score'] for r in sub]):.2f}</td>"
                     f"<td>{p}/{t}</td></tr>")
        H.append("</table>")

    # instruction adherence
    if any(r.get("scoring") == "adherence" for r in rows):
        H.append("<h2>Instruction adherence (agent.md)</h2><div class='sub'>Fraction of "
                 "deterministic AGENTS.md rules obeyed, independent of correctness.</div>"
                 "<table><tr><th>Model</th><th>Adherence</th><th>Rules obeyed</th></tr>")
        for m in models:
            sub = [r for r in by_model[m] if r.get("scoring") == "adherence"]
            if not sub:
                continue
            ob = sum(r["passed"] for r in sub)
            tt = sum(r["total"] for r in sub)
            H.append(f"<tr><td><b>{m}</b></td><td>{_avg([r['final_score'] for r in sub]):.2f}</td>"
                     f"<td>{ob}/{tt}</td></tr>")
        H.append("</table>")

    # quality judges
    if judges:
        H.append("<h2>Code quality — two judges</h2>"
                 "<div class='sub'>qwen3-coder grades blind; claude grades the same code with the "
                 "real test results in hand. They agree on genuinely-good code and diverge on "
                 "broken-but-plausible code — the gap is the blind judge's over-credit.</div>")
        for jname, jmap in judges.items():
            H.append(f"<h3>Judge: {jname}</h3><table><tr><th>Model</th><th>Overall</th>"
                     "<th>Correctness</th><th>Readability</th><th>Efficiency</th>"
                     "<th class='num'>graded</th></tr>")
            for m in models:
                vals = [v for (mm, _), v in jmap.items() if mm == m]
                rs = [r for (mm, _), r in jmap.items() if mm == m]
                if not rs:
                    continue
                ov = _avg([r["judge_detail"]["normalized"] * 10 for r in rs])
                cr = _avg([r["judge_detail"]["scores"].get("correctness") for r in rs])
                rd = _avg([r["judge_detail"]["scores"].get("readability") for r in rs])
                ef = _avg([r["judge_detail"]["scores"].get("efficiency") for r in rs])
                H.append(f"<tr><td><b>{m}</b></td><td class='num'>{ov:.1f}</td>"
                         f"<td class='num'>{cr:.1f}</td><td class='num'>{rd:.1f}</td>"
                         f"<td class='num'>{ef:.1f}</td><td class='num'>{len(rs)}</td></tr>")
            H.append("</table>")

    # recommendations — auto-generated by the judge model (bench/recommend.py writes this file)
    rec = bench / "recommendations.html"
    H.append("<h2>Recommendations <span class='sub'>(auto-generated by the judge model from "
             "the benchmark results)</span></h2>")
    if rec.exists():
        H.append('<div class="card">' + rec.read_text() + "</div>")
    else:
        H.append('<div class="card sub">Pending — generated by <code>engine.recommend</code> '
                 "after the judge pass (the final step of <code>serve/run_all.sh</code>).</div>")

    # per-model detail: every test's score + run time
    H.append("<h2>Per-model detail</h2><div class='sub'>Every challenge: score, pass count, and "
             "run time (the model call's wall-clock latency).</div>")
    for m in models:
        rs = sorted(by_model[m], key=lambda r: (r.get("type", ""), r.get("difficulty", 0),
                                                r.get("challenge", "")))
        if not rs:
            continue
        tot = sum((r.get("latency_s") or 0) for r in rs)
        H.append(f"<h3>{m} <span class='sub'>— {len(rs)} tests · avg score "
                 f"{_avg([r['final_score'] for r in rs]):.3f} · total run time {tot:.0f}s</span></h3>")
        H.append("<table><tr><th>Challenge</th><th>Type</th><th>Lang</th><th>D</th>"
                 "<th>Score</th><th>Passed</th><th class='num'>Run time (s)</th></tr>")
        for r in rs:
            sc = r.get("final_score", 0.0)
            lat = r.get("latency_s")
            lat_s = f"{lat:.1f}" if lat is not None else "-"
            cid = r.get("challenge", "")
            link = f"combined/transcripts/{m}__{cid}.md"   # report.html lives at the bench root
            H.append(f"<tr><td><a href='{link}'>{cid}</a></td><td>{r.get('type','')}</td>"
                     f"<td>{r.get('language','')}</td><td>{r.get('difficulty','')}</td>"
                     f"<td class='heat' style='{_heat(sc)}'>{sc:.2f}</td>"
                     f"<td>{r.get('passed','-')}/{r.get('total','-')}</td>"
                     f"<td class='num'>{lat_s}</td></tr>")
        H.append("</table>")

    H.append('<div class="foot">Generated from <code>%s</code>. Capability axes: code correctness '
             '&middot; library fluency &middot; code quality (LLM judge) &middot; tool-calling '
             '&middot; self-repair (retries) &middot; prompt-injection resistance. Models run at '
             'their recommended sampling settings (some temperature&gt;0), so expect minor '
             'run-to-run variance.</div>' % str(bench))
    H.append("</div></body></html>")

    out = Path(args.out) if args.out else bench / "report.html"
    out.write_text("\n".join(H))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
