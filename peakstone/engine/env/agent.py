"""First-class agent run mode for goal-state-env challenges.

The model operates a small network of machines through tools — write a file on a node, run a command
on a node, read logs, and `verify` (which seeds + launches the current solution and runs the
challenge's deterministic verifier). It iterates write → run → verify → fix until the goal state is
reached or it runs out of turns. Mirrors engine.agentic but over the multi-node EnvironmentProvider.

This is the live-LLM driver; the environment/verifier stack underneath is the same code the
reference driver (engine.env.run_reference) exercises without a model.
"""
from __future__ import annotations

import json

from .harness import run_once

ENV_TOOLS = [
    {"type": "function", "function": {
        "name": "list_nodes",
        "description": "List the nodes, the file each must provide, and peer/port env vars.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Create/overwrite a file on a node's working directory.",
        "parameters": {"type": "object", "properties": {
            "node": {"type": "string"}, "path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["node", "path", "content"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a file from a node (e.g. an input fixture or a log).",
        "parameters": {"type": "object", "properties": {
            "node": {"type": "string"}, "path": {"type": "string"}}, "required": ["node", "path"]}}},
    {"type": "function", "function": {
        "name": "run",
        "description": "Run a shell command on a node (for debugging). PORT/PEER_* env vars are set.",
        "parameters": {"type": "object", "properties": {
            "node": {"type": "string"}, "cmd": {"type": "string"}}, "required": ["node", "cmd"]}}},
    {"type": "function", "function": {
        "name": "verify",
        "description": "Launch the current solution across all nodes and run the goal-state verifier.",
        "parameters": {"type": "object", "properties": {}}}},
]

SYSTEM = (
    "You are an agent operating a small network of isolated machines (no internet). Each node has its "
    "own working directory. Write the required program on each node with write_file, then call verify "
    "to launch everything and run the goal-state checks. Read the failing checks and logs, fix the "
    "files, and verify again until every check passes. Node programs discover the topology via "
    "environment variables (PORT for a node's own port; PEER_<NAME>_HOST / PEER_<NAME>_PORT for peers)."
)


def _node_brief(spec):
    out = []
    for n in spec.nodes:
        bits = [f"node '{n.name}'"]
        if n.start:
            bits.append(f"launched as `{n.start}`")
        if n.ports:
            bits.append(f"listens on $PORT")
        if n.needs:
            bits.append(f"connects to {', '.join(n.needs)}")
        out.append(" — ".join(bits))
    return "\n".join(out)


def run_env_task(client, model, challenge, provider) -> dict:
    """Drive the agent loop. Returns passed/checks/turns + a transcript, plus env provenance."""
    spec = challenge.env
    fixtures = challenge.fixtures()
    verify_fn = challenge.load_verifier()
    files: dict[str, dict[str, str]] = {n.name: {} for n in spec.nodes}
    transcript: list[str] = []

    def do_verify():
        return run_once(provider_env, spec, files, verify_fn, fixtures=fixtures)

    with provider.provision(spec) as provider_env:
        # seed fixtures so the agent can inspect inputs
        for ns in spec.nodes:
            for path, content in fixtures.get(ns.name, {}).items():
                provider_env.node(ns.name).write_file(path, content)

        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": challenge.spec + "\n\nNodes:\n" + _node_brief(spec)}]
        turns_to_green = turns_used = None
        last_result = {"passed": False, "checks": []}

        for turn in range(1, challenge.max_turns + 1):
            turns_used = turn
            res = client.chat_tools(model, msgs, ENV_TOOLS, temperature=0.0,
                                    max_tokens=4096, timeout=spec.timeout + 10)
            if res.get("error"):
                transcript.append(f"[turn {turn}] model error: {res['error']}")
                break
            msg = res["message"]
            tcs = msg.get("tool_calls") or []
            if not tcs:
                break
            msgs.append(msg)
            for tc in tcs:
                fn = (tc.get("function") or {}).get("name", "")
                raw = (tc.get("function") or {}).get("arguments") or "{}"
                try:
                    args = json.loads(raw) if isinstance(raw, str) else raw
                except json.JSONDecodeError:
                    args = {}
                result = _dispatch(provider_env, spec, files, do_verify, fn, args)
                if fn == "verify":
                    last_result = result.get("_full", last_result)
                    if last_result.get("passed") and turns_to_green is None:
                        turns_to_green = turn
                transcript.append(f"[turn {turn}] {fn}({_short(args)}) -> {_short(result)}")
                msgs.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                             "name": fn, "content": json.dumps(_strip(result))[:3000]})
            if turns_to_green is not None:
                break

        # authoritative final scoring on the agent's files
        final = do_verify()
        final["provenance"] = provider_env.provenance()
        return {"passed": final["passed"], "checks": final["checks"],
                "turns_to_green": turns_to_green, "turns_used": turns_used,
                "transcript": "\n".join(transcript), "provenance": final["provenance"]}


def _dispatch(env, spec, files, do_verify, fn, args):
    if fn == "list_nodes":
        return {"nodes": [{"name": n.name, "provides": n.start, "ports": n.ports, "needs": n.needs}
                          for n in spec.nodes]}
    if fn == "write_file":
        node, path, content = args.get("node"), args.get("path"), args.get("content", "")
        if node not in files:
            return {"error": f"no node {node!r}"}
        files[node][path] = content
        env.node(node).write_file(path, content)
        return {"ok": True, "node": node, "path": path}
    if fn == "read_file":
        if args.get("node") not in {n.name for n in spec.nodes}:
            return {"error": f"no node {args.get('node')!r}"}
        return env.node(args["node"]).read_file(args.get("path", ""))
    if fn == "run":
        if args.get("node") not in {n.name for n in spec.nodes}:
            return {"error": f"no node {args.get('node')!r}"}
        r = env.node(args["node"]).run(args.get("cmd", ""), timeout=spec.timeout)
        return {"rc": r.rc, "output": ((r.stdout or "") + (r.stderr or ""))[-1500:]}
    if fn == "verify":
        full = do_verify()
        return {"passed": full["passed"], "checks": full["checks"],
                "launch_errors": full["launch_errors"], "_full": full}
    return {"error": f"unknown tool {fn}"}


def _strip(result):
    return {k: v for k, v in result.items() if k != "_full"} if isinstance(result, dict) else result


def _short(obj):
    s = json.dumps(_strip(obj)) if isinstance(obj, dict) else str(obj)
    return s[:200]
