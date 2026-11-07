"""Privacy canary: mail content and secrets must never reach any sink.

End-to-end check of docs/SECURITY.md section 2 and hard rules 3/4: the full
pipeline (parse_message -> Poller -> AppState -> Notifier with a fake toast
backend -> tray refresh) runs on fake mails whose sender, subject, snippet and
IDs carry unique canary strings while transient, malformed-API, unexpected and
reauth errors are forced. Afterwards every observable sink is scanned for a
canary match, and there must be zero:

- captured log records (messages, args, tracebacks),
- the real log files under a temporary log directory,
- every file under the test temp dir (settings.json, accounts.json, ...),
- files created in the system temp directory while the pipeline ran,
- str()/repr() of every exception the pipeline raised.

Mail-content canaries are never allowed anywhere: the call-site rules keep them
out of log records, so even the raw captured records must be clean.

Secrets (a fake refresh token and client secret) may exist in RAM and in the
(fake) keyring only; persistent sinks must be clean even for a deliberately bad
logging call, because every real handler formats through the redacting
formatter (D-17).
"""

from __future__ import annotations

import contextlib
import logging
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from google.auth.exceptions import RefreshError

from gsend import app as app_module
from gsend import auth, security_logging
from gsend.accounts import AccountStore
from gsend.app import _App
from gsend.errors import ReauthRequired
from gsend.gmail_client import GmailClient, parse_message
from gsend.logging_setup import setup_logging
from gsend.models import Mail
from gsend.notifier import Notifier
from gsend.settings import Settings
from gsend.state import AppState

SUBJECT_CANARY = "CANARY-SUBJ-7f3a"
SENDER_CANARY = "CANARY-FROM-91bc"
SNIPPET_CANARY = "CANARY-SNIP-c2d4"
ID_CANARY_A = "CANARY-MSGID-9d8c"
ID_CANARY_B = "CANARY-MSGID-b0d3"
THREAD_CANARY = "CANARY-THREAD-4b2a"
MAIL_CANARIES = (
    SUBJECT_CANARY,
    SENDER_CANARY,
    SNIPPET_CANARY,
    ID_CANARY_A,
    ID_CANARY_B,
    THREAD_CANARY,
)
ACCOUNT = "c@example.com"
FAKE_TOKEN = "FAKE-REFRESH-TOKEN-1234567890"
FAKE_SECRET = "FAKE-CLIENT-SECRET-0987654321"
SECRET_CANARIES = (FAKE_TOKEN, FAKE_SECRET)
_UNSET = object()


class FakeToastBackend:
    """Records every toast; never touches winotify."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None, bool]] = []

    def show(self, title: str, message: str, launch: str | None, sound: bool) -> None:
        self.calls.append((title, message, launch, sound))


class CanaryMailSource:
    """Scriptable MailSource serving one canary mail and raisable failures."""

    def __init__(self, mail: Mail) -> None:
        self.mail = mail
        self.list_error: Exception | None = None
        self.get_error: Exception | None = None
        self.list_response: object = _UNSET

    def latest_inbox_ids(self, limit: int, only_primary: bool) -> list[str]:
        if self.list_error is not None:
            raise self.list_error
        if self.list_response is _UNSET:
            return [self.mail.id]
        return self.list_response  # type: ignore[return-value]

    def get_mail(self, message_id: str) -> Mail:
        if self.get_error is not None:
            raise self.get_error
        return self.mail


class ExplodingService:
    """Gmail service fake whose list call raises RefreshError (token revoked)."""

    def users(self):  # noqa: D102 - test fake
        return self

    def messages(self):  # noqa: D102 - test fake
        return self

    def list(self, **_kwargs):  # noqa: D102 - test fake
        return self

    def get(self, **_kwargs):  # noqa: D102 - test fake
        return self

    def execute(self, **_kwargs):  # noqa: D102 - test fake
        raise RefreshError("invalid_grant")


def canary_mail(received: datetime, mail_id: str) -> Mail:
    return Mail(
        account=ACCOUNT,
        id=mail_id,
        thread_id=THREAD_CANARY,
        sender_name=f"{SENDER_CANARY} Sender",
        sender_email="attacker@evil.test",
        subject=f"Re: {SUBJECT_CANARY} urgent",
        snippet=f"hello {SNIPPET_CANARY} world",
        received_at=received,
        unread=True,
    )


@pytest.fixture()
def log_sink(tmp_path: Path):
    """Real log files under tmp_path; removes the handlers again afterwards."""
    log_dir = tmp_path / "logs"
    handlers = setup_logging(console=False, log_dir=log_dir, debug=True)
    yield log_dir
    for handler in handlers:
        logging.getLogger().removeHandler(handler)
        handler.close()


@pytest.fixture(autouse=True)
def _clean_secret_registry():
    security_logging.clear_secrets()
    yield
    security_logging.clear_secrets()


def _caplog_text(caplog: pytest.LogCaptureFixture) -> str:
    """Every record: formatted message, traceback, args reprs, full __dict__."""
    parts: list[str] = []
    for record in caplog.records:
        parts.append(record.getMessage())
        if record.exc_text:
            parts.append(record.exc_text)
        if record.exc_info:
            parts.append("".join(logging.Formatter().formatException(record.exc_info)))
        parts.append(repr(record.args))
        parts.append(str(record.__dict__))
    return "\n".join(parts)


def _tree_texts(root: Path) -> list[str]:
    texts: list[str] = []
    if not root.exists():
        return texts
    for path in sorted(root.rglob("*")):
        if path.is_file():
            texts.append(f"path={path.name}")
            with contextlib.suppress(OSError):
                texts.append(path.read_text(encoding="utf-8", errors="replace"))
    return texts


def _app_temp_files() -> set[str]:
    temp = Path(tempfile.gettempdir())
    # Legacy name included so pre-rename leftovers are still detected.
    return {
        p.name
        for p in temp.glob("*")
        if "gsend" in p.name.lower() or "gmailnotifier" in p.name.lower()
    }


def _assert_no_matches(canaries: tuple[str, ...], texts: list[str], context: str) -> None:
    for text in texts:
        for canary in canaries:
            assert canary not in text, f"{canary} leaked into {context}: {text[:200]!r}"


def test_mail_content_canary_never_reaches_sinks(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, log_sink: Path, monkeypatch
):
    caplog.set_level(logging.DEBUG)
    backend = FakeToastBackend()
    source = CanaryMailSource(canary_mail(datetime.now(UTC) - timedelta(hours=1), ID_CANARY_A))
    store = AccountStore(tmp_path / "accounts.json")
    store.add(ACCOUNT)
    state = AppState()
    notifier = Notifier(
        Settings(show_preview=True, max_toasts_per_poll=10, first_run_done=True),
        state,
        backend,
    )
    application = _App(Settings(first_run_done=True), store, state, notifier=notifier)
    monkeypatch.setattr(app_module, "GmailClient", lambda email, credentials: source)
    monkeypatch.setattr(auth, "credentials_for", lambda email, client_config=None: None)
    temp_before = _app_temp_files()

    application._poller.reload_accounts()  # like run()'s first step, but synchronous

    # Baseline cycle: the canary mail is cached, never toasted.
    application._poller._poll_cycle()
    assert backend.calls == []

    # A newer canary mail arrives: this one must toast.
    source.mail = canary_mail(datetime.now(UTC) - timedelta(seconds=5), ID_CANARY_B)
    application._poller._poll_cycle()
    assert backend.calls, "pipeline sanity: the canary mail should have toasted"
    joined_toast = "\n".join(
        title + message + (launch or "") for title, message, launch, _ in backend.calls
    )
    assert SUBJECT_CANARY in joined_toast  # sanity: the canary really flowed through

    # Forced failures the poller must survive, worst last (reauth pauses the account):
    caught: list[Exception] = []
    source.list_error = OSError("offline")  # transient network error
    application._poller._poll_cycle()
    source.list_error = RuntimeError("unexpected internal shape")  # catch-all path
    application._poller._poll_cycle()
    source.list_error = None
    source.list_response = None  # malformed listing -> TypeError inside the poller
    application._poller._poll_cycle()
    source.list_response = {"surprise": True}  # wrong shape
    application._poller._poll_cycle()
    source.get_error = RuntimeError("get failed with no content")
    source.list_response = [ID_CANARY_B]
    application._poller._poll_cycle()
    source.get_error = None
    source.list_response = _UNSET
    source.list_error = ReauthRequired("token expired or revoked; sign in again")
    application._poller._poll_cycle()

    # Malformed API dicts through the pure parser.
    garbage = [
        {},
        {"payload": None},
        {"payload": {"headers": "not-a-list"}, "snippet": SUBJECT_CANARY},
        {"payload": {"headers": [{"name": 7}, {"value": SENDER_CANARY}]}},
        {"id": ID_CANARY_A, "threadId": None, "internalDate": "not-a-number"},
        {"snippet": [SNIPPET_CANARY], "labelIds": "UNREAD"},
        {"payload": {"headers": [{"name": "From", "value": None}]}},
        {"payload": {"headers": [{"name": "Subject", "value": SUBJECT_CANARY}]}},
    ]
    for api_dict in garbage:
        mail = parse_message(ACCOUNT, api_dict)
        assert isinstance(mail, Mail)

    # Now scan every sink. Zero canary matches is the pass condition.
    _assert_no_matches(MAIL_CANARIES, [_caplog_text(caplog)], "caplog records")
    log_files = sorted(log_sink.glob("*"))
    assert log_files, "sanity: log files were written"
    _assert_no_matches(MAIL_CANARIES, _tree_texts(log_sink), "log files")
    _assert_no_matches(MAIL_CANARIES, _tree_texts(tmp_path), "settings/accounts files")
    new_temp = _app_temp_files() - temp_before
    assert not new_temp, f"app artifacts appeared in the system temp dir: {new_temp}"
    for exc in caught:
        _assert_no_matches(MAIL_CANARIES, [str(exc), repr(exc)], "exception text")


def test_secrets_never_reach_persistent_sinks(
    tmp_path: Path, log_sink: Path, fake_keyring, monkeypatch
):
    client_config = {
        "installed": {
            "client_id": "test-id.apps.googleusercontent.com",
            "client_secret": FAKE_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": ["http://localhost"],
        }
    }
    fake_keyring.set_password("GSend", ACCOUNT, FAKE_TOKEN)

    # Loading credentials registers the secret and reads it from the fake vault.
    creds = auth.credentials_for(ACCOUNT, client_config=client_config)
    assert creds.refresh_token == FAKE_TOKEN
    assert fake_keyring.entries[("GSend", ACCOUNT)] == FAKE_TOKEN  # allowed place

    # The token path through the Gmail client maps RefreshError to ReauthRequired.
    client = GmailClient(ACCOUNT, credentials=None, service=ExplodingService())
    with pytest.raises(ReauthRequired) as exc_info:
        client.latest_inbox_ids(10, only_primary=True)
    _assert_no_matches(SECRET_CANARIES, [str(exc_info.value), repr(exc_info.value)], "exception")
    with pytest.raises(ReauthRequired) as exc_info_mail:
        client.get_mail("any-id")
    _assert_no_matches(
        SECRET_CANARIES, [str(exc_info_mail.value), repr(exc_info_mail.value)], "exception"
    )

    # Deliberate bad call sites: only the redacting formatter stands between a
    # mistake and the log file (D-17). They must come out clean.
    logging.getLogger("canary.bad_call_site").error("dumping creds: %s", creds)
    logging.getLogger("canary.bad_call_site").error("dumping config: %s", client_config)

    # Removal path: read, delete, revoke failure — none of it may leak.
    def _fail_urlopen(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr("gsend.auth.urlopen", _fail_urlopen)
    auth.remove_account(ACCOUNT)
    assert ("GSend", ACCOUNT) not in fake_keyring.entries

    # Persistent sinks: log files and everything under the test temp dir.
    _assert_no_matches(SECRET_CANARIES, _tree_texts(log_sink), "log files")
    _assert_no_matches(SECRET_CANARIES, _tree_texts(tmp_path), "files under test tmp")
    # Positive control: the bad call sites really reached the file, redacted.
    file_text = "\n".join(_tree_texts(log_sink))
    assert "[REDACTED]" in file_text

    # And the last-resort layer itself, directly:
    assert security_logging.redact(f"token={FAKE_TOKEN}") == "token=[REDACTED]"
    assert security_logging.redact(f"secret={FAKE_SECRET}") == "secret=[REDACTED]"
