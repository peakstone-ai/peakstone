"""Multi-machine env harness: provider + verifier + bundle, proven without a live LLM.

The local provider runs everywhere; the docker test is skipped unless a daemon is reachable.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from engine import bundle
from engine.env import (LocalProvider, env_result_row, load_env_challenge, run_once, run_reference)
from engine.env.docker import DockerComposeProvider

CH_DIR = Path(__file__).resolve().parents[3] / "challenges" / "env" / "01-file-server"


@pytest.fixture(scope="module")
def challenge():
    return load_env_challenge(CH_DIR)


def test_local_reference_reaches_goal_state(challenge):
    res = run_reference(challenge, LocalProvider())
    assert res["passed"] is True
    assert res["checks"][0]["ok"] is True
    assert not res["launch_errors"]
    assert res["provenance"]["provider"] == "local"


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


@pytest.mark.skipif(not DockerComposeProvider().available(), reason="docker daemon not available")
def test_docker_reference_reaches_goal_state(challenge):
    res = run_reference(challenge, DockerComposeProvider())
    assert res["passed"] is True
    assert res["provenance"]["provider"] == "docker"
    # images are pinned by digest for reproducibility
    assert res["provenance"]["image_digests"]
