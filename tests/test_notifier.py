"""Tests for the Notifier mapping logic with a fake toast backend (no real toasts)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from gsend import links
from gsend.models import Account, AccountStatus, Mail
from gsend.notifier import Notifier
from gsend.settings import Settings
from gsend.state import AppState


@dataclass
class FakeBackend:
    calls: list = field(default_factory=list)
    error_on_attempt: int | None = None  # 1-based: raise on this attempt
    attempts: int = 0

    def show(self, title: str, message: str, launch: str | None, sound: bool) -> None:
        self.attempts += 1
        if self.error_on_attempt == self.attempts:
            raise OSError("toast backend down")
        self.calls.append((title, message, launch, sound))


def make_mail(mid: str, *, sender: str = "Jane", unread: bool = True) -> Mail:
    return Mail(
        account="a@example.com",
        id=mid,
        thread_id=f"cafe{mid[1:]}",  # hex, like real Gmail ids (links validation)
        sender_name=sender,
        sender_email="jane@example.com",
        subject=f"Subject {mid}",
        snippet=f"Preview {mid}",
        received_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        unread=unread,
    )


def make_notifier(**settings_kwargs) -> tuple[Notifier, FakeBackend, AppState]:
    state = AppState()
    state.set_accounts(
        [
            Account("a@example.com", None, AccountStatus.OK),
            Account("b@example.com", None, AccountStatus.OK),
        ]
    )
    backend = FakeBackend()
    notifier = Notifier(Settings(**settings_kwargs), state, backend)
    return notifier, backend, state


def test_single_mail_maps_layout_and_launch():
    notifier, backend, _ = make_notifier()
    notifier.notify_new_mails("a@example.com", [make_mail("m1")])
    assert len(backend.calls) == 1
    title, message, launch, sound = backend.calls[0]
    assert title == "Subject m1"
    assert "Jane · a" in message  # auto shows accounts with 2+, as the local part
    assert "Preview m1" in message
    assert launch == links.mail_url("a@example.com", "cafe1")
    assert sound is True


def test_show_preview_and_sound_settings_honored():
    notifier, backend, _ = make_notifier(show_preview=False, notification_sound=False)
    notifier.notify_new_mails("a@example.com", [make_mail("m1")])
    title, message, _launch, sound = backend.calls[0]
    assert message == "Jane · a"  # preview omitted, sender stays
    assert sound is False


def test_burst_produces_one_summary_toast_opening_inbox():
    notifier, backend, _ = make_notifier()  # cap 3
    mails = [make_mail(f"m{i}", sender=f"S{i}") for i in range(1, 6)]
    notifier.notify_new_mails("a@example.com", mails)
    assert len(backend.calls) == 1
    title, message, launch, _sound = backend.calls[0]
    assert title == "5 new mails"
    assert message == "S1, S2, S3 and 2 more · a"
    assert launch == links.inbox_url("a@example.com")


def test_at_cap_still_one_toast_per_mail():
    notifier, backend, _ = make_notifier()  # cap 3
    mails = [make_mail(f"m{i}") for i in range(3)]
    notifier.notify_new_mails("a@example.com", mails)
    assert len(backend.calls) == 3


def test_toast_failure_never_raises_and_rest_still_fire():
    notifier, backend, _ = make_notifier()
    backend.error_on_attempt = 2  # second toast fails
    mails = [make_mail("m1"), make_mail("m2"), make_mail("m3")]
    notifier.notify_new_mails("a@example.com", mails)  # must not raise
    assert backend.attempts == 3
    assert len(backend.calls) == 2  # first and third went out


def test_empty_mail_list_sends_nothing():
    notifier, backend, _ = make_notifier()
    notifier.notify_new_mails("a@example.com", [])
    assert backend.calls == []


def test_reauth_toast_has_no_launch():
    notifier, backend, _ = make_notifier()
    notifier.notify_reauth_needed("a@example.com")
    title, message, launch, sound = backend.calls[0]
    assert "sign-in needed" in title.lower()
    assert "Sign-in needed for a." in message  # short account name via account_display
    assert launch is None
    assert sound is False


def test_account_hidden_with_single_account_auto():
    state = AppState()
    state.set_accounts([Account("a@example.com", None, AccountStatus.OK)])
    backend = FakeBackend()
    notifier = Notifier(Settings(), state, backend)
    notifier.notify_new_mails("a@example.com", [make_mail("m1")])
    title, message, _launch, _sound = backend.calls[0]
    assert message == "Jane\nPreview m1"  # no account suffix


def test_hostile_thread_id_toasts_without_launch_target():
    """A tampered id must not become a URL; the toast still shows (SECURITY 6)."""
    notifier, backend, _ = make_notifier()
    mail = make_mail("m1")
    mail = Mail(
        account=mail.account,
        id=mail.id,
        thread_id="javascript:alert(1)",  # not hex: rejected by links.mail_url
        sender_name=mail.sender_name,
        sender_email=mail.sender_email,
        subject=mail.subject,
        snippet=mail.snippet,
        received_at=mail.received_at,
        unread=mail.unread,
    )
    notifier.notify_new_mails("a@example.com", [mail])
    assert len(backend.calls) == 1
    title, message, launch, _ = backend.calls[0]
    assert title == "Subject m1"
    assert launch is None


def test_summary_toast_for_bad_account_email_has_no_launch():
    notifier, backend, _ = make_notifier()
    mails = [make_mail(f"m{i}") for i in range(1, 6)]
    # the account email in state is fine; simulate a malformed one directly:
    notifier._send_summary("not-an-email", mails)  # type: ignore[arg-type]
    assert len(backend.calls) == 1
    assert backend.calls[0][2] is None
