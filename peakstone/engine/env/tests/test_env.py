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
_ENV = Path(__file__).resolve().parents[4] / "challenges" / "env"
ELECT_DIR = _ENV / "env-03-elect-collect"
KVQ_DIR = _ENV / "env-04-kv-quorum"
PARTITION_DIR = _ENV / "env-05-partition-heal"
LB_DIR = _ENV / "env-06-load-balancer"
PUBSUB_DIR = _ENV / "env-07-pubsub"
TPC_DIR = _ENV / "env-08-two-phase-commit"


@pytest.fixture(scope="module")
def challenge():
    return load_env_challenge(CH_DIR)


@pytest.fixture(scope="module")
def gossip():
    return load_env_challenge(GOSSIP_DIR)


@pytest.fixture(scope="module")
def elect():
    return load_env_challenge(ELECT_DIR)


@pytest.fixture(scope="module")
def kvq():
    return load_env_challenge(KVQ_DIR)


@pytest.fixture(scope="module")
def partition():
    return load_env_challenge(PARTITION_DIR)


@pytest.fixture(scope="module")
def load_balancer():
    return load_env_challenge(LB_DIR)


@pytest.fixture(scope="module")
def pubsub():
    return load_env_challenge(PUBSUB_DIR)


@pytest.fixture(scope="module")
def two_phase_commit():
    return load_env_challenge(TPC_DIR)


def test_gossip_convergence_reference_local(gossip):
    # 3 peers, fully connected, must converge on the global max (12) from seeds 5/12/3
    res = run_reference(gossip, LocalProvider())
    assert res["passed"] is True
    assert len(res["checks"]) == 3 and all(c["ok"] for c in res["checks"])


@pytest.mark.skipif(not DockerComposeProvider().available(), reason="docker daemon not available")
def test_gossip_convergence_reference_docker(gossip):
    res = run_reference(gossip, DockerComposeProvider())
    assert res["passed"] is True


def test_elect_collect_reference_local(elect):
    # 4 peers elect the highest-priority leader (peer1), which sums all values (=100); others write OK
    res = run_reference(elect, LocalProvider())
    assert res["passed"] is True
    assert len(res["checks"]) == 4 and all(c["ok"] for c in res["checks"])


def test_elect_collect_verifier_has_teeth(elect):
    # a peer that always writes "OK" never produces the leader's SUM -> goal-state must FAIL
    files = copy.deepcopy(elect.reference_files())
    for node in files:
        files[node]["peer.py"] = "open('result.txt','w').write('OK')\n"
    with LocalProvider().provision(elect.env) as env:
        res = run_once(env, elect.env, files, elect.load_verifier(), fixtures=elect.fixtures())
    assert res["passed"] is False


def test_kv_quorum_reference_local(kvq):
    # Go quorum store: client reads from the replica that holds neither key -> needs a quorum read
    res = run_reference(kvq, LocalProvider())
    assert res["passed"] is True
    assert res["checks"][0]["ok"] is True


def test_partition_recovery_default_provider_cannot_heal(partition):
    # LocalProvider has no runtime firewall -> heal() must refuse rather than silently "pass"
    import pytest as _pytest
    with LocalProvider().provision(partition.env) as env:
        with _pytest.raises(NotImplementedError):
            env.heal()


@pytest.mark.skipif(not DockerComposeProvider().available(), reason="docker daemon not available")
def test_partition_recovery_reference_docker(partition):
    # peers diverge behind the firewall, then converge after the verifier heals the network
    res = run_reference(partition, DockerComposeProvider())
    assert res["passed"] is True
    assert len(res["checks"]) == 2 and all(c["ok"] for c in res["checks"])


@pytest.mark.skipif(not DockerComposeProvider().available(), reason="docker daemon not available")
def test_partition_recovery_has_teeth(partition):
    # a peer that records only its own element (never gossips) can't reconcile after the heal -> FAIL
    files = copy.deepcopy(partition.reference_files())
    for node in files:
        files[node]["peer.py"] = ("import time\n"
                                  "open('result.txt','w').write(open('element.txt').read().strip())\n"
                                  "time.sleep(120)\n")
    with DockerComposeProvider().provision(partition.env) as env:
        res = run_once(env, partition.env, files, partition.load_verifier(),
                       fixtures=partition.fixtures())
    assert res["passed"] is False


def test_kv_quorum_requires_quorum_read(kvq):
    # cripple GET to a LOCAL-only read: peer2 (no copy) returns empty -> the verifier must FAIL,
    # proving the challenge genuinely requires a quorum read, not just local lookup.
    files = copy.deepcopy(kvq.reference_files())
    local_only = files["peer2"]["peer.go"].replace(
        'for _, n := range names {\n\t\t\tbody := fetch(peers[n] + "/local?key=" + key)',
        'for _, n := range names[:0] {\n\t\t\tbody := fetch(peers[n] + "/local?key=" + key)')
    assert local_only != files["peer2"]["peer.go"]   # the patch applied
    files["peer2"]["peer.go"] = local_only
    with LocalProvider().provision(kvq.env) as env:
        res = run_once(env, kvq.env, files, kvq.load_verifier(), fixtures=kvq.fixtures())
    assert res["passed"] is False


def test_load_balancer_reference_local(load_balancer):
    # router round-robins 9 client requests so each of 3 backends handles exactly 3
    res = run_reference(load_balancer, LocalProvider())
    assert res["passed"] is True
    assert len(res["checks"]) == 3 and all(c["ok"] for c in res["checks"])


def test_load_balancer_imbalance_fails(load_balancer):
    # a router that always hits backend0 -> uneven distribution -> goal-state must FAIL
    files = copy.deepcopy(load_balancer.reference_files())
    files["router"]["router.py"] = files["router"]["router.py"].replace(
        "BACKENDS[_next % len(BACKENDS)]", "BACKENDS[0]")
    with LocalProvider().provision(load_balancer.env) as env:
        res = run_once(env, load_balancer.env, files, load_balancer.load_verifier(),
                       fixtures=load_balancer.fixtures())
    assert res["passed"] is False


def test_pubsub_reference_local(pubsub):
    # broker fans each topic's messages to the right subscriber, in publish order
    res = run_reference(pubsub, LocalProvider())
    assert res["passed"] is True
    assert len(res["checks"]) == 2 and all(c["ok"] for c in res["checks"])


def test_two_phase_commit_reference_local(two_phase_commit):
    # t1 commits on all three participants; t2 aborts on all three (one no-vote forces global abort)
    res = run_reference(two_phase_commit, LocalProvider())
    assert res["passed"] is True
    assert len(res["checks"]) == 3 and all(c["ok"] for c in res["checks"])


def test_two_phase_commit_non_atomic_fails(two_phase_commit):
    # a participant that commits regardless of the decision breaks atomicity on t2 -> must FAIL
    files = copy.deepcopy(two_phase_commit.reference_files())
    files["participant0"]["participant.py"] = files["participant0"]["participant.py"].replace(
        'state[txn] = "aborted"', 'state[txn] = "committed"')
    with LocalProvider().provision(two_phase_commit.env) as env:
        res = run_once(env, two_phase_commit.env, files, two_phase_commit.load_verifier(),
                       fixtures=two_phase_commit.fixtures())
    assert res["passed"] is False


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
