"""Multi-machine env harness: provider + verifier + bundle, proven without a live LLM.

The local provider runs everywhere; the docker test is skipped unless a daemon is reachable.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from peakstone.engine import bundle
from peakstone.engine.env import (LocalProvider, env_result_row, load_env_challenge, run_once, run_reference)
from peakstone.engine.env.docker import DockerComposeProvider

CH_DIR = Path(__file__).resolve().parents[4] / "challenges" / "env" / "01-file-server"


GOSSIP_DIR = Path(__file__).resolve().parents[4] / "challenges" / "env" / "02-gossip-max"


@pytest.fixture(scope="module")
def challenge():
    return load_env_challenge(CH_DIR)


@pytest.fixture(scope="module")
def gossip():
    return load_env_challenge(GOSSIP_DIR)


def test_gossip_convergence_reference_local(gossip):
    # 3 peers, fully connected, must converge on the global max (12) from seeds 5/12/3
    res = run_reference(gossip, LocalProvider())
    assert res["passed"] is True
    assert len(res["checks"]) == 3 and all(c["ok"] for c in res["checks"])


@pytest.mark.skipif(not DockerComposeProvider().available(), reason="docker daemon not available")
def test_gossip_convergence_reference_docker(gossip):
    res = run_reference(gossip, DockerComposeProvider())
    assert res["passed"] is True


def test_local_reference_reaches_goal_state(challenge):
    res = run_reference(challenge, LocalProvider())
    assert res["passed"] is True
    assert res["checks"][0]["ok"] is True
    assert not res["launch_errors"]
    assert res["provenance"]["provider"] == "local"


def test_local_write_file_contains_path_traversal():
    from peakstone.engine.env import EnvSpec, LocalProvider, NodeSpec
    with LocalProvider().provision(EnvSpec("trav", nodes=[NodeSpec("a")])) as env:
        n = env.node("a")
        assert "error" in n.write_file("../escape.txt", "x")       # sibling escape rejected
        assert "error" in n.write_file("../../etc/pwned", "x")     # deeper traversal rejected
        assert n.write_file("sub/ok.txt", "y").get("ok") is True   # normal nested path works


def test_verifier_discriminates_a_broken_client(challenge):
    # a client that writes the wrong bytes must FAIL the goal-state check (the verifier has teeth)
    files = copy.deepcopy(challenge.reference_files())
    files["client"]["client.py"] = "open('result.txt','w').write('WRONG BYTES')\n"
    with LocalProvider().provision(challenge.env) as env:
        res = run_once(env, challenge.env, files, challenge.load_verifier(),
                       fixtures=challenge.fixtures())
    assert res["passed"] is False
    assert res["checks"][0]["ok"] is False


def test_missing_server_program_fails_cleanly(challenge):
    # no server.py -> the server never binds -> launch error -> client can't fetch -> fail (no crash)
    files = copy.deepcopy(challenge.reference_files())
    files["server"] = {}
    with LocalProvider().provision(challenge.env) as env:
        res = run_once(env, challenge.env, files, challenge.load_verifier(),
                       fixtures=challenge.fixtures())
    assert res["passed"] is False


def test_env_result_becomes_a_valid_bundle(challenge):
    res = run_reference(challenge, LocalProvider())
    row = env_result_row(challenge, res, model="reference", turns_to_green=1, turns_used=1)
    b = bundle.produce_bundle(
        {"models": ["reference"], "judge": None, "timestamp": "t",
         "gpu": {"name": "x", "driver_version": "1"}}, [row], sign=False)
    r0 = b["results"][0]
    assert r0["verification"] == "goal-state-env"
    assert r0["score"]["final"] == 1.0
    assert r0["env"]["provider"] == "local" and r0["env"]["checks"]
    bundle._validate(b)  # raises if invalid


class _StubClient:
    """A fake LLM that 'solves' the challenge by writing its reference files then calling verify —
    exercises the agent tool-loop (engine.env.agent) without a served model."""
    def __init__(self, ch):
        self.ch = ch
        self.turn = 0

    def chat_tools(self, model, messages, tools, **kw):
        import json
        self.turn += 1
        if self.turn == 1:
            calls = []
            for node, files in self.ch.reference_files().items():
                for path, content in files.items():
                    calls.append({"id": f"c{len(calls)}", "function": {
                        "name": "write_file",
                        "arguments": json.dumps({"node": node, "path": path, "content": content})}})
            calls.append({"id": "v", "function": {"name": "verify", "arguments": "{}"}})
            return {"message": {"role": "assistant", "tool_calls": calls}}
        return {"message": {"role": "assistant", "content": "done"}}   # no tool calls -> stop


def test_agent_loop_drives_env_to_goal_state(challenge):
    from peakstone.engine.env.agent import run_env_task
    res = run_env_task(_StubClient(challenge), "stub", challenge, LocalProvider())
    assert res["passed"] is True
    assert res["turns_to_green"] == 1
    # the agent result becomes a valid goal-state-env bundle row
    row = env_result_row(challenge, res, model="stub", turns_to_green=res["turns_to_green"],
                         turns_used=res["turns_used"], transcript=res["transcript"])
    assert row["verification"] == "goal-state-env" and row["final_score"] == 1.0


class _ChatStub:
    """Fake chat() client. `reply` is either a fixed string or a callable(messages)->string."""
    def __init__(self, reply):
        self.reply = reply

    def chat(self, model, messages, **kw):
        from peakstone.engine.provider import ChatResult
        text = self.reply(messages) if callable(self.reply) else self.reply
        return ChatResult(text=text, completion_tokens=len(text.split()), latency_s=0.1)


def test_planner_pipeline_plan_then_coder_then_tests():
    # planner emits a (dummy) plan; the fixed coder returns the challenge's reference solution;
    # tests verify -> the plan→code→test pipeline scores as a passing planner run.
    from peakstone.engine.challenges import load_challenges
    from peakstone.engine.env.planner import planner_result_row, run_planner_task
    ch = next(c for c in load_challenges(Path(CH_DIR).parents[2]) if c.id == "py-02-csv-groupby")
    planner = _ChatStub("PLAN: read csv, group by key, sum values, handle empty input.")
    ref = ch.reference_files()
    sol = ref.get(ch.solution_file) or next(iter(ref.values()))
    coder = _ChatStub(f"```python\n{sol}\n```")
    res = run_planner_task(planner, "planner-stub", coder, "coder-stub", ch, {})
    assert res["passed"] is True and res["final_score"] == 1.0
    assert res["plan_chars"] > 0 and res["coder_model"] == "coder-stub"
    row = planner_result_row(ch, res, "planner-stub")
    assert row["category"] == "planner" and row["env"]["coder_model"] == "coder-stub"


@pytest.mark.skipif(not DockerComposeProvider().available(), reason="docker daemon not available")
def test_docker_reference_reaches_goal_state(challenge):
    res = run_reference(challenge, DockerComposeProvider())
    assert res["passed"] is True
    assert res["provenance"]["provider"] == "docker"
    # images are pinned by digest for reproducibility
    assert res["provenance"]["image_digests"]
