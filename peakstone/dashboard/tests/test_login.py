"""`peakstone login` orchestration — mocked HTTP + keys, no browser/OAuth/network."""
import urllib.error
import urllib.parse

from peakstone.dashboard import login


def _patch_keys(monkeypatch):
    monkeypatch.setattr(login.eng_keys, "load_or_create_keypair", lambda: (object(), "PUBKEY"))
    monkeypatch.setattr(login.eng_keys, "sign", lambda priv, data: "SIG")


def test_already_linked_is_a_noop(monkeypatch, capsys):
    _patch_keys(monkeypatch)
    monkeypatch.setattr(login, "_get_json",
                        lambda url, **k: {"handle": "alice", "providers": [{"provider": "github"}]})
    assert login.login_main(["--api", "http://x"]) == 0
    assert "Already linked as @alice" in capsys.readouterr().out


def _wire_unbound(monkeypatch, captured, *, capture_result):
    """/account -> 404, authorize-url -> a URL (stashing the state), and record the bind body."""
    state_box = {}

    def fake_get(url, **k):
        if "/account?" in url:
            raise urllib.error.HTTPError(url, 404, "not bound", {}, None)
        if "authorize-url" in url:
            state_box["state"] = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
            return {"authorize_url": "https://github.com/login/oauth/authorize?x=1"}
        raise AssertionError(url)

    def fake_post(url, body, **k):
        if "key-challenge" in url:
            return {"nonce": "NONCE"}
        if "bind" in url:
            captured.update(body)
            return {"handle": "bob"}
        raise AssertionError(url)

    monkeypatch.setattr(login, "_get_json", fake_get)
    monkeypatch.setattr(login, "_post_json", fake_post)
    monkeypatch.setattr(login, "_capture_code_loopback",
                        lambda url, port, **k: capture_result(state_box.get("state")))
    return state_box


def test_full_bind_sends_both_proofs(monkeypatch, capsys):
    _patch_keys(monkeypatch)
    captured = {}
    _wire_unbound(monkeypatch, captured,
                  capture_result=lambda state: {"code": "CODE", "state": state})
    assert login.login_main(["--api", "http://x", "--port", "53682", "--browser"]) == 0
    assert captured["pubkey"] == "PUBKEY" and captured["nonce"] == "NONCE"
    assert captured["signature"] == "SIG" and captured["code"] == "CODE"
    assert captured["redirect_uri"] == "http://127.0.0.1:53682/callback"
    assert "linked as @bob" in capsys.readouterr().out


def test_state_mismatch_aborts(monkeypatch):
    _patch_keys(monkeypatch)
    captured = {}
    _wire_unbound(monkeypatch, captured,
                  capture_result=lambda state: {"code": "CODE", "state": "WRONG"})
    assert login.login_main(["--api", "http://x", "--browser"]) == 1
    assert not captured   # never reached /account/bind


def test_headless_auto_falls_back_to_paste(monkeypatch):
    """Over SSH the loopback can't work, so login auto-uses paste-mode (no --manual needed)."""
    _patch_keys(monkeypatch)
    monkeypatch.setenv("SSH_CONNECTION", "10.0.0.1 22 10.0.0.2 22")   # simulate SSH
    assert login._looks_headless() is True
    captured = {}
    _wire_unbound(monkeypatch, captured,
                  capture_result=lambda s: (_ for _ in ()).throw(AssertionError("loopback used over SSH")))
    monkeypatch.setattr("builtins.input", lambda *a: "PASTED_CODE")
    assert login.login_main(["--api", "http://x"]) == 0   # no --manual, but headless -> paste path
    assert captured["code"] == "PASTED_CODE"


def test_extract_code_accepts_bare_or_url():
    assert login._extract_code("abc123") == "abc123"
    assert login._extract_code("http://127.0.0.1:53682/callback?code=xyz&state=s") == "xyz"
