"""Tests for the thread-safe AppState (docs/ARCHITECTURE.md section 10)."""

from __future__ import annotations

from datetime import UTC, datetime

from gmail_notifier.models import Account, AccountStatus, Mail
from gmail_notifier.state import _MAX_OPENED, AppState


def make_mail(mid: str, *, received: datetime, unread: bool = True, account: str = "a@x.com"):
    return Mail(
        account=account,
        id=mid,
        thread_id=f"t-{mid}",
        sender_name="Sender",
        sender_email="s@x.com",
        subject=f"Subject {mid}",
        snippet="snippet",
        received_at=received,
        unread=unread,
    )


def test_latest_merges_accounts_sorted_desc():
    state = AppState()
    state.set_accounts(
        [
            Account("a@x.com", None, AccountStatus.OK),
            Account("b@x.com", None, AccountStatus.OK),
        ]
    )
    state.update_mails(
        "a@x.com",
        [
            make_mail("a2", received=datetime(2026, 1, 1, 12, 0, tzinfo=UTC)),
            make_mail("a1", received=datetime(2026, 1, 1, 10, 0, tzinfo=UTC)),
        ],
    )
    state.update_mails(
        "b@x.com",
        [make_mail("b1", received=datetime(2026, 1, 1, 11, 0, tzinfo=UTC), account="b@x.com")],
    )
    assert [m.id for m in state.latest(3)] == ["a2", "b1", "a1"]


def test_latest_n_limits():
    state = AppState()
    state.set_accounts([Account("a@x.com", None, AccountStatus.OK)])
    mails = [make_mail(f"m{i}", received=datetime(2026, 1, 1, 12, i, tzinfo=UTC)) for i in range(5)]
    state.update_mails("a@x.com", mails)
    assert len(state.latest(3)) == 3
    assert [m.id for m in state.latest(3)] == ["m4", "m3", "m2"]


def test_mark_opened_clears_unread_in_display():
    state = AppState()
    state.set_accounts([Account("a@x.com", None, AccountStatus.OK)])
    mail = make_mail("m1", received=datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
    state.update_mails("a@x.com", [mail])
    assert state.has_unread() is True
    state.mark_opened("m1")
    shown = state.latest(1)[0]
    assert shown.unread is False  # display copy only
    assert state.has_unread() is False


def test_update_mails_keeps_unread_until_opened():
    state = AppState()
    state.set_accounts([Account("a@x.com", None, AccountStatus.OK)])
    state.update_mails("a@x.com", [make_mail("m1", received=datetime(2026, 1, 1, tzinfo=UTC))])
    state.mark_opened("m1")
    state.update_mails("a@x.com", [make_mail("m1", received=datetime(2026, 1, 1, tzinfo=UTC))])
    assert state.has_unread() is False  # acknowledgement survives poll updates


def test_set_accounts_preserves_status_and_drops_removed():
    state = AppState()
    state.set_accounts(
        [
            Account("a@x.com", None, AccountStatus.OK),
            Account("b@x.com", None, AccountStatus.OK),
        ]
    )
    state.set_account_status("a@x.com", AccountStatus.NEEDS_REAUTH)
    state.set_accounts([Account("a@x.com", None, AccountStatus.OK)])
    assert state.worst_status() is AccountStatus.NEEDS_REAUTH  # status preserved


def test_worst_status_priority():
    state = AppState()
    state.set_accounts([Account("a@x.com", None, AccountStatus.OK)])
    assert state.worst_status() is AccountStatus.OK
    state.set_account_status("a@x.com", AccountStatus.ERROR)
    assert state.worst_status() is AccountStatus.ERROR
    state.set_accounts(
        [
            Account("a@x.com", None, AccountStatus.OK),
            Account("b@x.com", None, AccountStatus.OK),
        ]
    )
    state.set_account_status("b@x.com", AccountStatus.NEEDS_REAUTH)
    assert state.worst_status() is AccountStatus.NEEDS_REAUTH  # beats ERROR


def test_update_mails_ignores_unknown_account():
    state = AppState()
    state.update_mails("ghost@x.com", [make_mail("m1", received=datetime(2026, 1, 1, tzinfo=UTC))])
    assert state.latest(3) == []
    assert state.has_unread() is False


def test_removed_account_loses_mails():
    state = AppState()
    state.set_accounts([Account("a@x.com", None, AccountStatus.OK)])
    state.update_mails("a@x.com", [make_mail("m1", received=datetime(2026, 1, 1, tzinfo=UTC))])
    state.set_accounts([])
    assert state.latest(3) == []


def test_accounts_accessor():
    state = AppState()
    assert state.accounts() == []
    state.set_accounts([Account("a@x.com", "Work", AccountStatus.OK)])
    accounts = state.accounts()
    assert len(accounts) == 1
    assert accounts[0].email == "a@x.com"
    assert accounts[0].label == "Work"


def test_subscribe_fires_on_change_only():
    state = AppState()
    calls: list[str] = []
    state.subscribe(lambda: calls.append("cb"))
    state.set_accounts([Account("a@x.com", None, AccountStatus.OK)])
    mails = [make_mail("m1", received=datetime(2026, 1, 1, tzinfo=UTC))]
    state.update_mails("a@x.com", mails)
    state.update_mails("a@x.com", list(mails))  # identical content: no change
    state.mark_opened("m1")
    state.mark_opened("m1")  # duplicate: no change
    assert len(calls) == 3


def test_callback_runs_outside_lock():
    state = AppState()
    acquired: list[bool] = []

    def on_change() -> None:
        got = state._lock.acquire(blocking=False)
        acquired.append(got)
        if got:
            state._lock.release()

    state.subscribe(on_change)
    state.set_accounts([Account("a@x.com", None, AccountStatus.OK)])
    assert acquired == [True]  # the lock was free while the callback ran


def test_opened_set_is_bounded():
    state = AppState()
    for i in range(_MAX_OPENED + 100):
        state.mark_opened(f"m{i}")
    assert len(state._opened) == _MAX_OPENED
    assert "m0" not in state._opened  # oldest dropped first
