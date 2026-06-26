"""Served-context resolution used to gate long-context challenges per run."""
from __future__ import annotations

from peakstone.engine import runner


def test_served_ctx_env_override(monkeypatch):
    monkeypatch.setenv("PEAKSTONE_CTX", "8192")
    assert runner._served_ctx("any-model") == 8192   # PEAKSTONE_CTX overrides the registry ctx


def test_served_ctx_unknown_model_is_none(monkeypatch):
    monkeypatch.delenv("PEAKSTONE_CTX", raising=False)
    assert runner._served_ctx("definitely-not-a-registered-model") is None
