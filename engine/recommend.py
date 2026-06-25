"""Auto-generate the report's Recommendations section using the judge model.

Summarizes the benchmark results and asks the served judge model to write recommendations as
HTML paragraphs, written to <bench>/recommendations.html (picked up by engine.report_html).
Falls back to a deterministic summary if the model call fails.

  python -m engine.recommend <bench-dir> --model qwen3-coder
"""
from __future__ import annotations

import argparse
import glob
import json
import tomllib
from collections import defaultdict
from pathlib import Path

from . import paths
from .provider import LLMClient


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0


def _summarize(bench: Path) -> tuple[str, list]:
    rows = json.loads((bench / "combined" / "results.json").read_text())["results"]
    by = defaultdict(list)
    for r in rows:
        by[r["model"]].append(r)
    # judge quality (if a judge pass ran)
    qual = {}
    for d in glob.glob(str(bench / "judged-*")):
        for r in json.loads((Path(d) / "results.json").read_text()).get("results", []):
            if r.get("judge_detail", {}).get("scores"):
                qual.setdefault(r["model"], []).append(r["judge_detail"]["normalized"] * 10)

    models = sorted(by, key=lambda m: -_avg([r["final_score"] for r in by[m]]))
    lines, summary = [], []
    for m in models:
        rs = by[m]
        t = defaultdict(list)
        for r in rs:
            t[r.get("type", "?")].append(r["final_score"])
        tavg = {k: _avg(v) for k, v in t.items()}
        rec = {
            "model": m,
            "overall": round(_avg([r["final_score"] for r in rs]), 3),
            "tok_s": round(_avg([r.get("tok_per_s") for r in rs])),
            "vram_gb": round(max((r.get("vram_mib") or 0) for r in rs) / 1024, 1),
            "by_type": {k: round(v, 2) for k, v in sorted(tavg.items())},
            "judge_quality": round(_avg(qual.get(m, [])), 1) if m in qual else None,
        }
        summary.append(rec)
        lines.append(
            f"{m}: overall={rec['overall']} tok/s={rec['tok_s']} vram={rec['vram_gb']}GB "
            f"quality_judge={rec['judge_quality']} | " +
            " ".join(f"{k}={v}" for k, v in rec["by_type"].items())
        )
    return "\n".join(lines), summary


PROMPT = """\
You are writing the "Recommendations" section of a local coding-LLM benchmark report, run on a
single RTX 4090 (24GB). Below is each model's results: overall score (0-1, from automated tests),
generation speed (tok/s), loaded VRAM (GB, lower is better), a blind LLM-judge code-quality score
(0-10), and per-capability-type averages (agentic, tool-calling, injection = prompt-injection
resistance, refusal = not over-refusing, secure-code, etc.).

IMPORTANT: the judge_quality score is BLIND (grades code without running it) and over-credits, so
weight the objective `overall` test score and the capability types more heavily.

Write practical recommendations as a few short HTML <p> paragraphs (use <b>, <code>, <span
class="good">/<span class="bad"> for emphasis). Cover: best all-round model, best for safe
agentic use (high tool-calling/agentic AND injection resistance), best small/efficient model
(good capability at low VRAM/high tok/s), and what to avoid. Cite specific numbers. Output ONLY
the HTML <p> blocks — no markdown, no code fences, no headings.

RESULTS:
{summary}
"""


def _fallback(summary: list) -> str:
    s = sorted(summary, key=lambda x: -x["overall"])
    top = s[0]
    fastest = max(summary, key=lambda x: x["tok_s"])
    small = min(summary, key=lambda x: x["vram_gb"])
    return (
        f"<p><b>Best overall:</b> <code>{top['model']}</code> "
        f"(score {top['overall']}, {top['tok_s']} tok/s, {top['vram_gb']}GB).</p>"
        f"<p><b>Fastest:</b> <code>{fastest['model']}</code> ({fastest['tok_s']} tok/s).</p>"
        f"<p><b>Smallest footprint:</b> <code>{small['model']}</code> ({small['vram_gb']}GB).</p>"
        f"<p class='sub'>(Deterministic fallback — the judge model could not be reached.)</p>"
    )


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("engine")
    ap.add_argument("--model", default="qwen3-coder")
    ap.add_argument("--out", default=None)
    ap.add_argument("--config", default=str(paths.config_path()))
    args = ap.parse_args(argv)
    bench = Path(args.bench)
    out = Path(args.out) if args.out else bench / "recommendations.html"

    summ_text, summary = _summarize(bench)

    cfg = tomllib.loads(Path(args.config).read_text())
    host = cfg["server"]["host"]
    mt = tomllib.loads(paths.models_toml().read_text())
    port = mt.get(args.model, {}).get("port")

    html = None
    if port:
        client = LLMClient(f"http://{host}:{port}")
        res = client.chat(args.model,
                          [{"role": "system", "content": "You write concise, data-grounded "
                            "benchmark recommendations as raw HTML paragraphs."},
                           {"role": "user", "content": PROMPT.format(summary=summ_text)}],
                          temperature=0.3, max_tokens=1200, timeout=300)
        if not res.error and res.text.strip():
            t = res.text.strip()
            if "```" in t:  # strip any code fences the model added
                import re
                t = re.sub(r"```[a-z]*\n?|```", "", t)
            html = t.strip()

    if not html:
        html = _fallback(summary)
    out.write_text(html)
    print(f"wrote {out} ({'model' if port and html and 'fallback' not in html else 'fallback'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
