"""Tool-calling task: compose two tool calls (add then multiply); don't self-compute."""

SYSTEM = ("You are a calculator assistant. You must use ONLY the provided math tools for any "
          "arithmetic; never compute values yourself. Chain tool calls as needed.")
PROMPT = "Compute (3 + 4) * 5 using the tools, then give me the final number."


def _num(p):
    return {"type": "number"}


TOOLS = [
    {"type": "function", "function": {
        "name": "add", "description": "Return a + b.",
        "parameters": {"type": "object",
                       "properties": {"a": _num("a"), "b": _num("b")},
                       "required": ["a", "b"]}}},
    {"type": "function", "function": {
        "name": "multiply", "description": "Return a * b.",
        "parameters": {"type": "object",
                       "properties": {"a": _num("a"), "b": _num("b")},
                       "required": ["a", "b"]}}},
]


def dispatch(name, args):
    try:
        a, b = float(args.get("a")), float(args.get("b"))
    except (TypeError, ValueError):
        return {"error": "a and b must be numbers"}
    if name == "add":
        return {"result": a + b}
    if name == "multiply":
        return {"result": a * b}
    return {"error": f"unknown tool {name}"}


def _argset(c):
    vals = []
    for v in c["arguments"].values():
        try:
            vals.append(float(v))
        except (TypeError, ValueError):
            pass
    return set(vals)


def check(calls, final_text):
    total = 3
    passed = 0
    adds = [c for c in calls if c["name"] == "add"]
    muls = [c for c in calls if c["name"] == "multiply"]
    if any(_argset(c) == {3.0, 4.0} for c in adds):
        passed += 1
    if any(5.0 in _argset(c) and 7.0 in _argset(c) for c in muls):
        passed += 1
    if "35" in (final_text or ""):
        passed += 1
    return passed, total
