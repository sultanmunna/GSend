"""Tests for auth.py with a fake in-memory keyring and a fake OAuth flow.

No network, no real keyring, no real Google calls. The fake flow records its
arguments so the tests can assert the PKCE/prompt/localhost details that the
hard rules depend on. The sign-in tests drive the real loopback wait in
auth.py over localhost sockets, playing the browser from the test thread.
"""

from __future__ import annotations

import json
import socket
import struct
import threading
import time
from urllib.parse import urlparse

import pytest

from gmail_notifier import auth, security_logging
from gmail_notifier.errors import (
    AuthCancelled,
    ConfigError,
    GmailError,
    KeyringBackendError,
    ReauthRequired,
)

FAKE_CONFIG = {
    "installed": {
        "client_id": "test-id.apps.googleusercontent.com",
        "client_secret": "test-secret",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}


class FakeCredentials:
    def __init__(self, refresh_token: str | None) -> None:
        self.refresh_token = refresh_token


class FakeFlow:
    """Stand-in for InstalledAppFlow; records constructor and sign-in calls."""

    last_from_client_config: dict | None = None
    last_authorization_kwargs: dict | None = None
    last_fetch_kwargs: dict | None = None
    last_redirect_uri: str | None = None
    refresh_token: str | None = "refresh-token-abc"

    @classmethod
    def from_client_config(cls, client_config, scopes, **kwargs):
        cls.last_from_client_config = {"config": client_config, "scopes": scopes, **kwargs}
        return cls()

    def authorization_url(self, **kwargs):
        FakeFlow.last_authorization_kwargs = dict(kwargs)
        FakeFlow.last_redirect_uri = self.redirect_uri
        return f"http://accounts.example.test/auth?redirect_uri={self.redirect_uri}", "state"

    def fetch_token(self, **kwargs):
        FakeFlow.last_fetch_kwargs = dict(kwargs)

    @property
    def credentials(self):
        return FakeCredentials(FakeFlow.refresh_token)


@pytest.fixture()
def fake_flow(monkeypatch: pytest.MonkeyPatch) -> type[FakeFlow]:
    FakeFlow.last_from_client_config = None
    FakeFlow.last_authorization_kwargs = None
    FakeFlow.last_fetch_kwargs = None
    FakeFlow.last_redirect_uri = None
    FakeFlow.refresh_token = "refresh-token-abc"
    monkeypatch.setattr(auth, "InstalledAppFlow", FakeFlow)
    monkeypatch.setattr(auth, "_profile_email", lambda credentials: "user@example.com")
    return FakeFlow


@pytest.fixture()
def browser_sim(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the real browser open; collect the sign-in URLs."""
    opened: list[str] = []
    monkeypatch.setattr(auth.webbrowser, "open", lambda url, **_: opened.append(url) or True)
    return opened


def _start_sign_in(**kwargs) -> tuple[threading.Thread, dict]:
    """Run add_account_interactive on a worker like the app's auth worker."""
    result: dict = {}

    def job() -> None:
        try:
            result["email"] = auth.add_account_interactive(client_config=FAKE_CONFIG, **kwargs)
        except Exception as exc:  # the tests assert on the error type below
            result["error"] = exc

    thread = threading.Thread(target=job, daemon=True)
    thread.start()
    return thread, result


def _wait_for_redirect_uri(timeout_seconds: float = 5.0) -> int:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if FakeFlow.last_redirect_uri:
            return int(urlparse(FakeFlow.last_redirect_uri).port)
        time.sleep(0.01)
    raise AssertionError("sign-in never produced a loopback redirect URI")


def _complete_redirect(port: int) -> None:
    """Play the browser: send the OAuth redirect and read the success page."""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as conn:
        conn.sendall(
            b"GET /?code=abc&scope=email HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        )
        conn.recv(4096)


def _abort_connection(port: int) -> None:
    """Open a connection and reset it, like a browser's aborted first attempt."""
    conn = socket.create_connection(("127.0.0.1", port), timeout=5)
    conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    conn.close()


# --- add_account_interactive --------------------------------------------------


def test_add_account_stores_refresh_token_under_service_key(fake_flow, fake_keyring, browser_sim):
    thread, result = _start_sign_in()
    _complete_redirect(_wait_for_redirect_uri())
    thread.join(timeout=10)
    assert result.get("email") == "user@example.com"
    assert fake_keyring.get_password("GmailNotifier", "user@example.com") == "refresh-token-abc"


def test_add_account_uses_pkce_select_account_and_localhost(fake_flow, browser_sim):
    thread, _ = _start_sign_in()
    port = _wait_for_redirect_uri()
    redirect_uri = FakeFlow.last_redirect_uri
    _complete_redirect(port)
    thread.join(timeout=10)

    call = FakeFlow.last_from_client_config
    assert call is not None
    assert call["scopes"] == ["https://www.googleapis.com/auth/gmail.readonly"]
    assert call["autogenerate_code_verifier"] is True  # PKCE
    assert FakeFlow.last_authorization_kwargs == {"prompt": "select_account consent"}
    parsed = urlparse(redirect_uri)
    assert (parsed.scheme, parsed.hostname) == ("http", "localhost")
    assert parsed.port not in (None, 0)  # random free port


def test_sign_in_timeout_raises_authcancelled_and_stores_nothing(
    fake_flow, fake_keyring, browser_sim
):
    thread, result = _start_sign_in(timeout_seconds=1)  # nothing ever connects
    thread.join(timeout=15)
    assert isinstance(result.get("error"), AuthCancelled)
    assert fake_keyring.entries == {}


def test_sign_in_survives_reset_connection(fake_flow, fake_keyring, browser_sim):
    # The 1.5.0 bug: an aborted browser connection ended the wait, the server
    # closed, and the browser's real redirect was refused.
    thread, result = _start_sign_in(timeout_seconds=15)
    port = _wait_for_redirect_uri()
    _abort_connection(port)
    _complete_redirect(port)
    thread.join(timeout=10)
    assert result.get("email") == "user@example.com"
    assert "error" not in result
    fetch = FakeFlow.last_fetch_kwargs
    assert fetch is not None
    assert fetch["authorization_response"].startswith("https://localhost")
    assert fake_keyring.get_password("GmailNotifier", "user@example.com") == "refresh-token-abc"


def test_add_account_without_refresh_token_raises_and_stores_nothing(
    fake_flow, fake_keyring, browser_sim
):
    FakeFlow.refresh_token = None
    thread, result = _start_sign_in()
    _complete_redirect(_wait_for_redirect_uri())
    thread.join(timeout=10)
    assert isinstance(result.get("error"), GmailError)
    assert fake_keyring.entries == {}


def test_add_account_uses_default_client_config_loader(
    monkeypatch, fake_flow, fake_keyring, browser_sim
):
    monkeypatch.setattr(auth, "load_client_config", lambda: FAKE_CONFIG)
    thread, result = _start_sign_in()
    _complete_redirect(_wait_for_redirect_uri())
    thread.join(timeout=10)
    assert result.get("email") == "user@example.com"


# --- credentials_for / has_token ----------------------------------------------


def test_credentials_for_builds_from_stored_token(fake_keyring):
    fake_keyring.set_password("GmailNotifier", "user@example.com", "stored-token")
    creds = auth.credentials_for("user@example.com", client_config=FAKE_CONFIG)
    assert creds.refresh_token == "stored-token"
    assert creds.token_uri == "https://oauth2.googleapis.com/token"
    assert creds.client_id == "test-id.apps.googleusercontent.com"
    assert creds.client_secret == "test-secret"
    assert creds.scopes == ["https://www.googleapis.com/auth/gmail.readonly"]


def test_credentials_for_missing_token_raises_reauth(fake_keyring):
    with pytest.raises(ReauthRequired):
        auth.credentials_for("ghost@example.com", client_config=FAKE_CONFIG)


def test_credentials_for_malformed_config_raises_config_error(fake_keyring):
    fake_keyring.set_password("GmailNotifier", "user@example.com", "stored-token")
    with pytest.raises(ConfigError):
        auth.credentials_for("user@example.com", client_config={"installed": {}})


def test_add_account_refuses_insecure_keyring_backend(fake_keyring, monkeypatch):
    class PlainFileBackend:
        """A keyring backend that is not Windows Credential Manager."""

    monkeypatch.setattr(fake_keyring, "get_keyring", lambda: PlainFileBackend())
    with pytest.raises(KeyringBackendError):
        auth.add_account_interactive(client_config=FAKE_CONFIG)


def test_credentials_for_refuses_insecure_keyring_backend(fake_keyring, monkeypatch):
    fake_keyring.set_password("GmailNotifier", "user@example.com", "stored-token")

    class PlainFileBackend:
        """A keyring backend that is not Windows Credential Manager."""

    monkeypatch.setattr(fake_keyring, "get_keyring", lambda: PlainFileBackend())
    with pytest.raises(KeyringBackendError):
        auth.credentials_for("user@example.com", client_config=FAKE_CONFIG)


def test_keyring_guard_accepts_chain_containing_vault(fake_keyring):
    class ChainBackend:
        def __init__(self, vault: object) -> None:
            self.backends = [vault]

    assert auth._keyring_is_secure(ChainBackend(fake_keyring.get_keyring())) is True


def test_keyring_guard_rejects_unknown_backend():
    assert auth._keyring_is_secure(object()) is False


def test_secrets_become_registered_on_sign_in_and_load(fake_flow, fake_keyring, monkeypatch):
    # Skip the browser dance; the sign-in result is what registration follows.
    monkeypatch.setattr(
        auth, "_run_local_sign_in", lambda flow, timeout: FakeCredentials("refresh-token-abc")
    )
    security_logging.clear_secrets()
    try:
        auth.add_account_interactive(client_config=FAKE_CONFIG)
        assert "test-secret" in security_logging._registered  # client secret
        assert "refresh-token-abc" in security_logging._registered  # new refresh token
        auth.credentials_for("user@example.com", client_config=FAKE_CONFIG)
    finally:
        security_logging.clear_secrets()


def test_has_token(fake_keyring):
    assert auth.has_token("user@example.com") is False
    fake_keyring.set_password("GmailNotifier", "user@example.com", "t")
    assert auth.has_token("user@example.com") is True


# --- remove_account -----------------------------------------------------------


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self):
        return b"{}"


def test_remove_account_deletes_token_and_revokes(fake_keyring, monkeypatch):
    fake_keyring.set_password("GmailNotifier", "user@example.com", "stored-token")
    calls: dict[str, str] = {}

    def fake_urlopen(request, timeout=None):
        calls["url"] = request.full_url
        calls["body"] = request.data.decode("ascii")
        return FakeResponse()

    monkeypatch.setattr(auth, "urlopen", fake_urlopen)
    auth.remove_account("user@example.com")
    assert fake_keyring.get_password("GmailNotifier", "user@example.com") is None
    assert calls["url"] == "https://oauth2.googleapis.com/revoke"
    assert "stored-token" in calls["body"]


def test_remove_account_revoke_failure_is_ignored(fake_keyring, monkeypatch):
    fake_keyring.set_password("GmailNotifier", "user@example.com", "stored-token")

    def failing_urlopen(request, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr(auth, "urlopen", failing_urlopen)
    auth.remove_account("user@example.com")  # must not raise
    assert fake_keyring.get_password("GmailNotifier", "user@example.com") is None


def test_remove_account_without_token_is_idempotent(fake_keyring, monkeypatch):
    def unexpected_urlopen(request, timeout=None):
        raise AssertionError("revoke must not be attempted without a token")

    monkeypatch.setattr(auth, "urlopen", unexpected_urlopen)
    auth.remove_account("ghost@example.com")  # no token: no revoke, no raise


# --- load_client_config -------------------------------------------------------


def test_load_client_config_env_path(tmp_path, monkeypatch):
    config_file = tmp_path / "client_config.json"
    config_file.write_text(json.dumps(FAKE_CONFIG), encoding="utf-8")
    monkeypatch.setenv("GMAIL_NOTIFIER_CLIENT_CONFIG", str(config_file))
    assert auth.load_client_config() == FAKE_CONFIG


def test_load_client_config_cwd_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("GMAIL_NOTIFIER_CLIENT_CONFIG", raising=False)
    config_file = tmp_path / "client_config.json"
    config_file.write_text(json.dumps(FAKE_CONFIG), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert auth.load_client_config() == FAKE_CONFIG


def test_load_client_config_missing_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("GMAIL_NOTIFIER_CLIENT_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)  # no client_config.json anywhere reachable
    with pytest.raises(ConfigError):
        auth.load_client_config()


def test_load_client_config_wrong_shape_raises(tmp_path, monkeypatch):
    config_file = tmp_path / "client_config.json"
    config_file.write_text('{"web": {}}', encoding="utf-8")  # not an "installed" client
    monkeypatch.setenv("GMAIL_NOTIFIER_CLIENT_CONFIG", str(config_file))
    monkeypatch.chdir(tmp_path)  # keep the real ./client_config.json out of reach
    with pytest.raises(ConfigError):
        auth.load_client_config()


def test_normalize_profile_email_lowercases_and_strips():
    assert auth._normalize_profile_email("  User@Example.COM \n") == "user@example.com"


def test_normalize_profile_email_refuses_unusable_values():
    for bad in (None, 7, "", "not-an-address", "a b@c.test", "a@b c", "@x.test", "a@"):
        with pytest.raises(GmailError):
            auth._normalize_profile_email(bad)


def test_add_account_stores_token_under_normalized_email(fake_flow, fake_keyring, monkeypatch):
    """Gmail may report different casing between sign-ins; the keyring key is
    case-sensitive, so the stored email must be normalized (SECURITY section 4)."""
    monkeypatch.setattr(
        auth, "_run_local_sign_in", lambda flow, timeout: FakeCredentials("refresh-token-abc")
    )
    monkeypatch.setattr(
        auth,
        "_profile_email",
        lambda credentials: auth._normalize_profile_email("  MixedCase@Gmail.COM "),
    )
    email = auth.add_account_interactive(client_config=FAKE_CONFIG)
    assert email == "mixedcase@gmail.com"
    assert fake_keyring.get_password("GmailNotifier", "mixedcase@gmail.com") is not None


# --- OAuth endpoint validation (SECURITY section 3): only Google hosts --------


def test_credentials_for_refuses_tampered_token_uri(fake_keyring):
    fake_keyring.set_password("GmailNotifier", "user@example.com", "stored-token")
    tampered = {"installed": dict(FAKE_CONFIG["installed"], token_uri="https://evil.test/token")}
    with pytest.raises(ConfigError):
        auth.credentials_for("user@example.com", client_config=tampered)


def test_credentials_for_uses_only_the_google_token_endpoint(fake_keyring):
    """Even with a valid config, the credential is pinned to the Google endpoint."""
    fake_keyring.set_password("GmailNotifier", "user@example.com", "stored-token")
    creds = auth.credentials_for("user@example.com", client_config=FAKE_CONFIG)
    assert creds.token_uri == "https://oauth2.googleapis.com/token"


def test_add_account_refuses_tampered_auth_uri(fake_flow, fake_keyring):
    tampered = {
        "installed": dict(FAKE_CONFIG["installed"], auth_uri="https://evil.test/consent")
    }
    with pytest.raises(ConfigError):
        auth.add_account_interactive(client_config=tampered)


def test_add_account_accepts_v2_auth_uri_variant(fake_flow, fake_keyring, monkeypatch):
    monkeypatch.setattr(
        auth, "_run_local_sign_in", lambda flow, timeout: FakeCredentials("refresh-token-abc")
    )
    cfg = {
        "installed": dict(
            FAKE_CONFIG["installed"],
            auth_uri="https://accounts.google.com/o/oauth2/v2/auth",
        )
    }
    email = auth.add_account_interactive(client_config=cfg)
    assert email == "user@example.com"
