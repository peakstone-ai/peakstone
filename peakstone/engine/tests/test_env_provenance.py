"""R7 — agentic guarantees. The challenge content hash must pin an env challenge's ground truth
(verify.py / env.toml / fixtures), and the public agent_score must count only isolating-provider
rows when asked to."""

from peakstone.engine import scoreboard
from peakstone.engine.bundle import _hash_challenge_dir


def _mk_env_challenge(tmp_path, verify_body="print('v1')"):
    d = tmp_path / "env-99-test"
    d.mkdir(exist_ok=True)
    (d / "meta.toml").write_text('id = "env-99-test"\n')
    (d / "spec.md").write_text("reach the goal state\n")
    (d / "env.toml").write_text("[nodes.a]\nimage = 'python'\n")
    (d / "verify.py").write_text(verify_body)
    (d / "fixtures").mkdir(exist_ok=True)
    (d / "fixtures" / "data.txt").write_text("seed\n")
    return d


def test_env_challenge_hash_pins_the_verifier(tmp_path):
    d = _mk_env_challenge(tmp_path)
    h1 = _hash_challenge_dir(d)
    (d / "verify.py").write_text("print('v2')  # different ground truth")
    assert _hash_challenge_dir(d) != h1          # verify.py can't change without surfacing
    (d / "verify.py").write_text("print('v1')")
    assert _hash_challenge_dir(d) == h1          # deterministic
    (d / "fixtures" / "data.txt").write_text("different seed\n")
    assert _hash_challenge_dir(d) != h1          # fixtures are part of the environment's identity


def test_reference_solution_does_not_change_the_hash(tmp_path):
    d = _mk_env_challenge(tmp_path)
    h1 = _hash_challenge_dir(d)
    (d / "reference").mkdir()
    (d / "reference" / "solve.sh").write_text("echo hi\n")
    assert _hash_challenge_dir(d) == h1          # reference demonstrates, it doesn't define truth


def _agent_row(provider, final=1.0):
    r = {"verification": "goal-state-env", "category": "agentic", "score": {"final": final}}
    if provider is not None:
        r["env"] = {"provider": provider}
    return r


def test_public_agent_score_counts_isolating_providers_only():
    rows = [_agent_row("docker", 1.0), _agent_row("local", 0.0), _agent_row(None, 0.0)]
    public = scoreboard.summarize_rows(rows, agent_isolating_only=True)
    assert public["agent_score"] == 1.0 and public["n_agent"] == 1   # docker row only
    local_board = scoreboard.summarize_rows(rows)                    # the owner's own board
    assert local_board["n_agent"] == 3
