"""Agentic self-repair harness.

The model is dropped into a workspace that holds a *buggy* solution plus a (read-only) test
suite, and is given tools to inspect, edit, and run the tests. It must iterate until the tests
pass. We score the final test pass-rate and record turns-to-green.

Design notes:
  * Editable solution files live in memory (seeded from the challenge's `buggy/` dir). The
    model's write_file edits update that dict.
  * run_tests reuses bench.sandbox.run_tests, which materializes a fresh temp dir from the
    CURRENT solution files + the challenge's real tests/ — so the model cannot pass by
    rewriting the tests (its edits to test paths are ignored).
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from . import sandbox

AGENTIC_TOOLS = [
    {"type": "function", "function": {
        "name": "list_files",
        "description": "List the editable solution files and the read-only test files.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a file's contents (use a path from list_files).",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Overwrite an editable solution file with new contents.",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                       "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "run_tests",
        "description": "Run the test suite against the current solution; returns pass/total and output.",
        "parameters": {"type": "object", "properties": {}}}},
]

SYSTEM = (
    "You are a coding agent fixing a bug. The workspace has an editable solution and a "
    "read-only test suite. Use the tools to read files, run the tests to see failures, edit "
    "the solution with write_file, and re-run until ALL tests pass. Make minimal, correct "
    "changes. Call run_tests after editing. Stop once everything passes."
)


class Workspace:
    def __init__(self, challenge, cfg):
        self.ch = challenge
        self.cfg = cfg
        self.files = self._load("buggy")     # editable solution (in memory)
        self.test_names = self._list_dir("tests")
        self.last = None
        self.test_runs = 0

    def _load(self, sub):
        d = self.ch.dir / sub
        out = {}
        if d.is_dir():
            for f in d.rglob("*"):
                if f.is_file():
                    out[str(f.relative_to(d))] = f.read_text()
        return out

    def _list_dir(self, sub):
        d = self.ch.dir / sub
        return [f"tests/{f.relative_to(d)}" for f in d.rglob("*") if f.is_file()] if d.is_dir() else []

    # --- tools ---
    def list_files(self):
        return {"editable": sorted(self.files), "readonly_tests": sorted(self.test_names)}

    def read_file(self, path):
        path = (path or "").lstrip("./")
        if path in self.files:
            return {"path": path, "content": self.files[path]}
        if path.startswith("tests/"):
            f = self.ch.dir / path
            if f.is_file():
                return {"path": path, "content": f.read_text()}
        return {"error": f"no such file: {path}"}

    def write_file(self, path, content):
        path = (path or "").lstrip("./")
        if path.startswith("tests/"):
            return {"error": "test files are read-only"}
        self.files[path] = content if content is not None else ""
        return {"ok": True, "path": path, "bytes": len(self.files[path])}

    def run_tests(self):
        self.test_runs += 1
        r = sandbox.run_tests(self.ch, self.files, self.cfg)
        self.last = r
        return {
            "passed": r.passed, "total": r.total,
            "all_passed": bool(r.total > 0 and r.passed == r.total and r.returncode == 0),
            "output": ((r.stdout or "") + "\n" + (r.stderr or "")).strip()[-2500:],
        }

    def dispatch(self, name, args):
        if name == "list_files":
            return self.list_files()
        if name == "read_file":
            return self.read_file(args.get("path"))
        if name == "write_file":
            return self.write_file(args.get("path"), args.get("content"))
        if name == "run_tests":
            return self.run_tests()
        return {"error": f"unknown tool {name}"}


def _max_turns(ch):
    try:
        m = tomllib.loads((ch.dir / "meta.toml").read_text())
        return int(m.get("max_turns", 12))
    except Exception:  # noqa: BLE001
        return 12


def run_agentic_task(client, model, ch, cfg):
    """Drive the self-repair loop. Returns a dict with passed/total/green/turns/test_runs."""
    import json
    ws = Workspace(ch, cfg)
    baseline = ws.run_tests()           # starting state (also gives us the buggy baseline)
    ws.test_runs = 0                    # don't count the harness's baseline run against the model
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": ch.spec
             + "\n\nFix the solution so that run_tests reports all tests passing."}]
    max_turns = _max_turns(ch)
    turns_to_green = None
    last_lat = None
    err = None

    for turn in range(1, max_turns + 1):
        res = client.chat_tools(model, msgs, AGENTIC_TOOLS, temperature=0.0,
                                max_tokens=2048, timeout=ch.timeout)
        if res.get("error"):
            err = res["error"]
            break
        last_lat = res.get("latency_s")
        msg = res["message"]
        tcs = msg.get("tool_calls") or []
        if not tcs:
            break                       # model thinks it's done
        msgs.append(msg)
        for tc in tcs:
            fn = (tc.get("function") or {}).get("name", "")
            raw = (tc.get("function") or {}).get("arguments") or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                args = {}
            result = ws.dispatch(fn, args)
            if fn == "run_tests" and result.get("all_passed") and turns_to_green is None:
                turns_to_green = turn
            msgs.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                         "name": fn, "content": json.dumps(result)[:3000]})
        if turns_to_green is not None:
            break

    final = ws.last or baseline
    passed, total = final.passed, final.total
    green = bool(total > 0 and passed == total and final.returncode == 0)
    return {
        "passed": passed, "total": total, "green": green,
        "baseline_passed": baseline["passed"], "baseline_total": baseline["total"],
        "turns_to_green": turns_to_green, "turns_used": turn, "test_runs": ws.test_runs,
        "latency_s": last_lat, "error": err,
    }
