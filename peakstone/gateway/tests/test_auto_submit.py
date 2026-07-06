"""R14 — the daemon must not publish finished runs to the public board by default.

Auto-submit signs with the box owner's key, and loopback job queueing is auth-exempt, so a queued
job is not consent to publish. Opt-in is PEAKSTONE_AUTO_SUBMIT=1 (wins) or [gateway].auto_submit."""

from peakstone.gateway import app as gw_app


def test_default_is_off(monkeypatch):
    monkeypatch.delenv("PEAKSTONE_AUTO_SUBMIT", raising=False)
    monkeypatch.setattr(gw_app, "load_gateway_config", lambda: {"auto_submit": False})
    assert gw_app._resolve_auto_submit() is None


def test_config_opt_in(monkeypatch):
    monkeypatch.delenv("PEAKSTONE_AUTO_SUBMIT", raising=False)
    monkeypatch.setattr(gw_app, "load_gateway_config", lambda: {"auto_submit": True})
    assert gw_app._resolve_auto_submit() is gw_app._default_submit


def test_env_wins_over_config(monkeypatch):
    monkeypatch.setattr(gw_app, "load_gateway_config", lambda: {"auto_submit": True})
    monkeypatch.setenv("PEAKSTONE_AUTO_SUBMIT", "0")
    assert gw_app._resolve_auto_submit() is None      # explicit off beats config on
    monkeypatch.setenv("PEAKSTONE_AUTO_SUBMIT", "1")
    assert gw_app._resolve_auto_submit() is gw_app._default_submit
