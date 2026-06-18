"""LLM-as-judge rubric scoring via a local (OpenAI-compatible) model.

Used for `scoring = judge|both` challenges, where pass/fail tests alone don't capture
design quality. The judge returns 0-10 scores per criterion as JSON. Offline by default
(points at one of the served models); can target Claude by changing config [judge].
"""
from __future__ import annotations

import json
import re

from .provider import LLMClient

_SYSTEM = (
    "You are a strict senior code reviewer grading a solution to a programming task. "
    "Score each criterion from 0 to 10 (10 = excellent). Be objective and concise. "
    "Respond with ONLY a JSON object, no markdown fences."
)

_TEMPLATE = """\
# Task specification
{spec}

# Candidate solution
```
{solution}
```

# Automated test outcome
{test_summary}

Grade the solution on these criteria: {criteria}.
Return JSON exactly like:
{{"scores": {{{score_keys}}}, "rationale": "<=2 sentences"}}
"""


def judge_solution(
    client: LLMClient, model: str, challenge, solution_text: str, test_summary: str,
    timeout: int = 300,
) -> dict:
    criteria = challenge.judge_criteria
    score_keys = ", ".join(f'"{c}": <0-10>' for c in criteria)
    prompt = _TEMPLATE.format(
        spec=challenge.spec, solution=solution_text, test_summary=test_summary,
        criteria=", ".join(criteria), score_keys=score_keys,
    )
    res = client.chat(
        model,
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
        temperature=0.0, max_tokens=800, timeout=timeout,
    )
    if res.error:
        return {"error": res.error, "scores": {}, "normalized": 0.0}
    obj = _parse_json(res.text)
    if not obj or "scores" not in obj:
        return {"error": "unparseable judge output", "raw": res.text[:400], "scores": {}, "normalized": 0.0}
    scores = {k: _clamp(obj["scores"].get(k)) for k in criteria}
    vals = [v for v in scores.values() if v is not None]
    norm = (sum(vals) / (10 * len(vals))) if vals else 0.0
    return {"scores": scores, "rationale": obj.get("rationale", ""), "normalized": round(norm, 3)}


def _parse_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def _clamp(v):
    try:
        return max(0.0, min(10.0, float(v)))
    except (TypeError, ValueError):
        return None
