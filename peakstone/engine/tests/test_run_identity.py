"""R1 — run identity. One budget is resolved once and lands identically in the per-request
calls, the report meta, and the signed bundle's sampling block; the bundle records the real
harness version. Before this, a CLI --max-tokens, the config value, and the meta default could
describe the same run with three different numbers."""

from types import SimpleNamespace

from peakstone.engine import bundle as B
from peakstone.engine import runner
from peakstone.engine.versions import pkg_version

ROWS = [{"model": "m", "challenge": "c1", "language": "py", "difficulty": 1, "category": "code",
         "type": "code", "scoring": "tests", "final_score": 1.0, "passed": 3, "total": 3,
         "response": "x"}]


def _args(max_tokens=None):
    return SimpleNamespace(max_tokens=max_tokens)


def test_cli_override_wins_uniformly():
    run_cfg = {"max_tokens": 6144}
    runner._freeze_budget(_args(8192), run_cfg)
    assert run_cfg["max_tokens"] == 8192                 # CLI beats config…
    assert run_cfg["max_tokens_reasoning"] == 8192       # …and caps reasoning-heavy tasks too


def test_defaults_and_config_cap():
    run_cfg = {}
    runner._freeze_budget(_args(None), run_cfg)
    assert run_cfg["max_tokens"] == runner.DEFAULT_MAX_TOKENS
    assert run_cfg["max_tokens_reasoning"] == runner.REASONING_MAX_TOKENS

    capped = {"max_tokens": 4096}                        # a config value caps everything uniformly
    runner._freeze_budget(_args(None), capped)
    assert capped["max_tokens"] == 4096 and capped["max_tokens_reasoning"] == 4096


def test_freeze_idempotent_and_budget_reads_frozen():
    args, run_cfg = _args(None), {}
    runner._freeze_budget(args, run_cfg)
    frozen = dict(run_cfg)
    runner._freeze_budget(args, run_cfg)                 # a second freeze must not drift
    assert run_cfg == frozen
    assert runner._budget(args, run_cfg) == frozen["max_tokens"]
    assert runner._budget(args, run_cfg, reasoning_heavy=True) == frozen["max_tokens_reasoning"]


def test_bundle_records_resolved_budget_not_disk_config():
    """The signed bundle's sampling block carries the budget the run ACTUALLY used (from meta),
    never a fresh re-read of whatever config.toml says at bundling time."""
    meta = {"timestamp": "t", "models": ["m"], "judge": None, "gpu": None, "mem_used": {},
            "max_tokens": 8192, "max_tokens_reasoning": 8192}
    b = B.produce_bundle(meta, ROWS, sign=False)
    s = b["model"]["sampling"]
    assert s["max_tokens"] == 8192 and s["max_tokens_reasoning"] == 8192


def test_bundle_harness_version_is_real():
    meta = {"timestamp": "t", "models": ["m"], "judge": None, "gpu": None, "mem_used": {}}
    b = B.produce_bundle(meta, ROWS, sign=False)
    assert b["harness"]["version"] == pkg_version()      # not the frozen "0.1.0" literal


def test_suite_hash_pins_selected_set_not_executed_rows():
    """R4: two runs of the same level selection must share a suite content_hash even when gating
    or abandonment shrinks one's executed set — the skipped ids are documented instead."""
    from peakstone.engine import paths
    chash = B.challenge_hashes(paths.challenges_dir())
    ids = sorted(chash)[:3]
    meta = {"timestamp": "t", "models": ["m"], "judge": None, "gpu": None, "mem_used": {},
            "selected_ids": ids, "skip_reasons": {ids[1]: "gated: model lacks 'tools'"}}
    gated = B.produce_bundle(meta, [dict(ROWS[0], challenge=ids[0])], sign=False)
    full = B.produce_bundle(dict(meta, skip_reasons={}),
                            [dict(ROWS[0], challenge=i) for i in ids], sign=False)
    assert gated["suite"]["content_hash"] == full["suite"]["content_hash"]
    assert gated["suite"]["skipped"][ids[1]].startswith("gated")
    assert gated["suite"]["skipped"][ids[2]] == "not-executed"
    assert "skipped" not in full["suite"]
