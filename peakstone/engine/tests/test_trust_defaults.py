"""R12 + R13 — consent and loudness defaults.

R12: the auto env-provider pick must NEVER silently fall back to the local provider (it executes
model-generated shell on the host); local is explicit consent only. R13: in --gateway mode the
judge client must ride the gateway, not a per-model port that doesn't exist there."""

from types import SimpleNamespace

from peakstone.engine import env as env_pkg
from peakstone.engine import runner
from peakstone.engine.env.capabilities import Requirements


class FakeProvider:
    def __init__(self, name, avail):
        self.name, self._avail = name, avail

    def available(self):
        return self._avail


def _select(monkeypatch, *, env_provider=None, allow_env=None, avail=()):
    """Run _select_env_provider with a stubbed provider registry (only `avail` are available)."""
    monkeypatch.setattr(env_pkg, "get_provider", lambda n: FakeProvider(n, n in avail))
    if allow_env is None:
        monkeypatch.delenv("PEAKSTONE_ALLOW_LOCAL_ENV", raising=False)
    else:
        monkeypatch.setenv("PEAKSTONE_ALLOW_LOCAL_ENV", allow_env)
    args = SimpleNamespace(env_provider=env_provider)
    ch = SimpleNamespace(env=SimpleNamespace(requirements=Requirements()))
    return runner._select_env_provider(args, ch)


def test_auto_never_picks_local_silently(monkeypatch):
    # local is the only available provider, requirements are empty (local would satisfy them) —
    # the old code ran the challenge on the host here; now it must skip.
    assert _select(monkeypatch, avail=("local",)) is None


def test_auto_prefers_isolating_provider(monkeypatch):
    prov = _select(monkeypatch, avail=("local", "docker"))
    assert prov is not None and prov.name == "docker"


def test_auto_falls_through_to_next_isolating(monkeypatch):
    prov = _select(monkeypatch, avail=("microvm",))   # docker matches first but isn't available
    assert prov is not None and prov.name == "microvm"


def test_explicit_local_is_consent(monkeypatch):
    prov = _select(monkeypatch, env_provider="local", avail=("local",))
    assert prov is not None and prov.name == "local"


def test_env_var_is_consent(monkeypatch):
    prov = _select(monkeypatch, allow_env="1", avail=("local",))
    assert prov is not None and prov.name == "local"
    assert _select(monkeypatch, allow_env="0", avail=("local",)) is None   # "0" is not consent


def test_judge_client_rides_the_gateway():
    args = SimpleNamespace(gateway="http://gw:12434", gateway_key="tok")
    c = runner._judge_client(args, {}, "127.0.0.1", {}, "judge-m")
    assert c is not None and c.base_url == "http://gw:12434" and c.api_key == "tok"


def test_judge_base_url_beats_gateway():
    args = SimpleNamespace(gateway="http://gw:12434", gateway_key=None)
    c = runner._judge_client(args, {"base_url": "http://judge:9000"}, "h", {}, "judge-m")
    assert c.base_url == "http://judge:9000"


def test_judge_client_none_without_port():
    args = SimpleNamespace(gateway=None, gateway_key=None)
    assert runner._judge_client(args, {}, "127.0.0.1", {}, "judge-m") is None
