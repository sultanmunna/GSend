"""Tests for the Poller: every rule from docs/ARCHITECTURE.md section 7 and the
poller row of docs/TESTING.md, driven by a FakeMailSource and a virtual clock.

Single-threaded tests call the poller's cycle directly; two tests exercise the
real thread for prompt stop() and immediate wake().
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from gmail_notifier.accounts import AccountStore
from gmail_notifier.errors import GmailError, ReauthRequired, TransientError
from gmail_notifier.models import AccountStatus, Mail
from gmail_notifier.poller import _SEEN_LIMIT, Poller, _AccountPollState
from gmail_notifier.settings import Settings
from gmail_notifier.state import AppState

ACCOUNT = "a@example.com"


class FakeMailSource:
    """Scriptable MailSource: canned ids/mails and a raisable error."""

    def __init__(self):
        self.ids: list[str] = []
        self.mails: dict[str, Mail] = {}
        self.list_error: Exception | None = None
        self.list_calls = 0
        self.get_calls = 0
        self.last_limit: int | None = None

    def latest_inbox_ids(self, limit: int, only_primary: bool) -> list[str]:
        self.list_calls += 1
        self.last_limit = limit
        if self.list_error is not None:
            raise self.list_error
        return self.ids[:limit]

    def get_mail(self, message_id: str) -> Mail:
        self.get_calls += 1
        return self.mails[message_id]


def make_mail(mid: str, *, received: datetime, unread: bool = True, account: str = ACCOUNT):
    return Mail(
        account=account,
        id=mid,
        thread_id=f"t-{mid}",
        sender_name="Sender",
        sender_email="s@example.com",
        subject=f"Subject {mid}",
        snippet="snippet",
        received_at=received,
        unread=unread,
    )


def build_poller(
    tmp_path: Path,
    *,
    interval: int = 45,
    accounts: tuple[str, ...] = (ACCOUNT,),
) -> SimpleNamespace:
    store = AccountStore(tmp_path / "accounts.json")
    for email in accounts:
        store.add(email)
    state = AppState()
    sources: dict[str, FakeMailSource] = {}
    factory_emails: list[str] = []

    def factory(email: str) -> FakeMailSource:
        if email not in sources:  # memoized: one client per account, like the poller expects
            sources[email] = FakeMailSource()
            factory_emails.append(email)
        return sources[email]

    clock = [1000.0]
    new_events: list[tuple[str, list[Mail]]] = []
    reauth_events: list[str] = []
    poller = Poller(
        client_factory=factory,
        account_store=store,
        state=state,
        settings=Settings(poll_interval_seconds=interval),
        on_new_mails=lambda email, mails: new_events.append((email, list(mails))),
        on_reauth_needed=reauth_events.append,
        time_fn=lambda: clock[0],
    )
    poller.reload_accounts()  # populate per-account bookkeeping (no polling yet)
    for email in accounts:  # eager fakes so tests can configure them pre-cycle
        sources.setdefault(email, FakeMailSource())
    return SimpleNamespace(
        poller=poller,
        store=store,
        state=state,
        sources=sources,
        factory_emails=factory_emails,
        clock=clock,
        new_events=new_events,
        reauth_events=reauth_events,
        interval=interval,
    )


def load(h, email: str, mails: list[Mail]) -> None:
    """Point the fake source at the given top-of-inbox list (newest first)."""
    source = h.sources.setdefault(email, FakeMailSource())
    source.ids = [m.id for m in mails]
    source.mails = {m.id: m for m in mails}


# --- baseline -----------------------------------------------------------------


def test_baseline_is_silent_but_state_is_populated(tmp_path):
    h = build_poller(tmp_path)
    base = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    load(
        h,
        ACCOUNT,
        [
            make_mail("m1", received=base + timedelta(minutes=1)),
            make_mail("m2", received=base),
            make_mail("m3", received=base - timedelta(minutes=1)),
        ],
    )
    h.poller._poll_cycle()
    assert h.new_events == []  # baseline never toasts
    assert [m.id for m in h.state.latest(3)] == ["m1", "m2", "m3"]


def test_new_unread_mail_emits_exactly_once(tmp_path):
    h = build_poller(tmp_path)
    base = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    load(h, ACCOUNT, [make_mail("m1", received=base)])
    h.poller._poll_cycle()
    load(
        h,
        ACCOUNT,
        [make_mail("m0", received=base + timedelta(minutes=5)), *h.sources[ACCOUNT].mails.values()],
    )
    h.poller._poll_cycle()
    assert len(h.new_events) == 1
    email, mails = h.new_events[0]
    assert email == ACCOUNT
    assert [m.id for m in mails] == ["m0"]  # newest first
    h.poller._poll_cycle()  # same inbox: no duplicate
    assert len(h.new_events) == 1


def test_read_mail_is_not_emitted(tmp_path):
    h = build_poller(tmp_path)
    base = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    load(h, ACCOUNT, [make_mail("m1", received=base)])
    h.poller._poll_cycle()
    load(h, ACCOUNT, [make_mail("m0", received=base + timedelta(minutes=5), unread=False)])
    h.poller._poll_cycle()
    assert h.new_events == []  # read mail never toasts
    assert [m.id for m in h.state.latest(1)] == ["m0"]  # but it is shown


def test_old_mail_reentering_top10_is_not_emitted(tmp_path):
    h = build_poller(tmp_path)
    base = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    load(
        h,
        ACCOUNT,
        [
            make_mail("m1", received=base),
            make_mail("m2", received=base - timedelta(minutes=1)),
        ],
    )
    h.poller._poll_cycle()
    # m1 is deleted upstream; old m0 (before the cutoff) re-enters the top 10.
    load(
        h,
        ACCOUNT,
        [
            make_mail("m0", received=base - timedelta(hours=2)),
            make_mail("m2", received=base - timedelta(minutes=1)),
        ],
    )
    h.poller._poll_cycle()
    assert h.new_events == []  # unseen but older than the cutoff: no toast
    assert [m.id for m in h.state.latest(2)] == ["m2", "m0"]  # sorted by received_at


def test_clock_skew_uses_received_at_only(tmp_path):
    # The cutoff comes from Google's internalDate (2030), the PC clock says 2026:
    # detection must ignore the wall clock entirely.
    h = build_poller(tmp_path)
    future = datetime(2030, 1, 1, 0, 0, tzinfo=UTC)
    load(h, ACCOUNT, [make_mail("m1", received=future)])
    h.poller._poll_cycle()
    load(
        h,
        ACCOUNT,
        [make_mail("m0", received=future + timedelta(minutes=5)), make_mail("m1", received=future)],
    )
    h.poller._poll_cycle()
    assert [m.id for m in h.new_events[0][1]] == ["m0"]


# --- burst and bounds -----------------------------------------------------------


def test_burst_toasts_the_top10_window_once(tmp_path):
    # Gmail returns at most 10 ids per listing, so a 12-mail burst shows 10 in
    # the window; those toast once, the rest are below the window (D-04/D-09).
    h = build_poller(tmp_path)
    old = datetime(2000, 1, 1, tzinfo=UTC)
    load(h, ACCOUNT, [make_mail("m_old", received=old)])
    h.poller._poll_cycle()  # baseline: cutoff = 2000-01-01

    burst = [
        make_mail(f"new{i:02d}", received=old + timedelta(minutes=i)) for i in range(1, 13)
    ]  # new01..new12
    window = [m.id for m in reversed(burst)][:10]  # what Gmail lists: new12..new03
    source = h.sources[ACCOUNT]
    source.ids = window
    source.mails = {m.id: m for m in burst}

    h.poller._poll_cycle()
    assert source.last_limit == 10  # the poller asks for exactly the section-8 limit
    assert len(h.new_events) == 1
    email, mails = h.new_events[0]
    assert email == ACCOUNT
    assert [m.id for m in mails] == [f"new{i:02d}" for i in range(12, 2, -1)]  # newest first
    assert source.get_calls == 11  # 1 baseline fetch + 10 burst fetches

    h.poller._poll_cycle()  # same listing: no duplicates
    assert len(h.new_events) == 1
    shown = {m.id for m in h.state.latest(20)}
    assert {"new03", "new12"} <= shown  # the window reached the menu


def test_seen_ids_are_bounded_oldest_dropped():
    poll = _AccountPollState()
    Poller._remember_seen(poll, [f"m{i}" for i in range(_SEEN_LIMIT + 5)])
    assert len(poll.seen_ids) == _SEEN_LIMIT
    assert "m0" not in poll.seen_ids
    assert f"m{_SEEN_LIMIT + 4}" in poll.seen_ids


# --- backoff --------------------------------------------------------------------


def test_backoff_growth_cap_and_reset(tmp_path):
    h = build_poller(tmp_path, interval=100)
    source = h.sources[ACCOUNT]
    source.list_error = TransientError("offline")
    h.poller._poll_cycle()
    assert source.list_calls == 1
    poll = h.poller._poll_state[ACCOUNT]
    assert poll.failures == 1
    assert poll.next_allowed == 1200.0  # 1000 + 100 * 2**1

    h.poller._poll_cycle()  # still backed off: no API call
    assert source.list_calls == 1

    h.clock[0] = 1199.9
    h.poller._poll_cycle()
    assert source.list_calls == 1

    h.clock[0] = 1200.0
    h.poller._poll_cycle()  # fails again: 100 * 2**2 = 400 -> capped at 300
    assert poll.failures == 2
    assert poll.next_allowed == 1500.0

    source.list_error = None  # network is back
    h.clock[0] = 1500.0  # past the backoff deadline
    h.poller._poll_cycle()
    assert poll.failures == 0  # reset on success

    source.list_error = TransientError("offline again")
    h.clock[0] = 1501.0
    h.poller._poll_cycle()
    assert poll.failures == 1  # a fresh failure starts from 2*interval again
    assert poll.next_allowed == 1701.0


def test_wait_timeout_is_interval_or_backoff_deadline(tmp_path):
    h = build_poller(tmp_path, interval=45)
    assert h.poller._wait_timeout() == 45.0  # no accounts with pending backoff

    h.poller._poll_cycle()  # baseline
    h.sources[ACCOUNT].list_error = TransientError("down")
    h.poller._poll_cycle()  # next_allowed = 1090
    h.clock[0] = 1090.0 - 89.0
    assert h.poller._wait_timeout() == 45.0  # remaining backoff capped at interval
    h.clock[0] = 1090.0 - 1.0
    assert h.poller._wait_timeout() == 1.0


# --- reauth and hard errors -------------------------------------------------------


def test_reauth_pauses_once_and_resumes_after_reload(tmp_path):
    h = build_poller(tmp_path)
    source = h.sources[ACCOUNT]
    source.list_error = ReauthRequired("invalid_grant")

    h.poller._poll_cycle()
    assert h.reauth_events == [ACCOUNT]  # exactly one event per expiry
    assert h.state.worst_status() is AccountStatus.NEEDS_REAUTH
    assert source.list_calls == 1

    h.poller._poll_cycle()  # paused: no further attempts
    assert source.list_calls == 1

    # Reload (e.g. the user added another account) retries the account but must
    # not re-toast for the same expiry.
    h.poller.reload_accounts()
    h.poller._poll_cycle()
    assert source.list_calls == 2
    assert h.reauth_events == [ACCOUNT]
    assert h.state.worst_status() is AccountStatus.NEEDS_REAUTH

    source.list_error = None  # the user signed in again
    h.poller.reload_accounts()
    h.poller._poll_cycle()
    assert h.state.worst_status() is AccountStatus.OK  # status recovers


def test_hard_error_reports_once_without_raising(tmp_path):
    h = build_poller(tmp_path)
    h.sources[ACCOUNT].list_error = GmailError("Gmail API error (HTTP 403)")
    h.poller._poll_cycle()
    assert h.state.worst_status() is AccountStatus.ERROR
    assert h.reauth_events == []
    h.clock[0] += 10**6  # long past the backoff: fails again
    h.poller._poll_cycle()  # still standing, still ERROR, no reauth event
    assert h.state.worst_status() is AccountStatus.ERROR


def test_unexpected_exception_does_not_escape(tmp_path):
    h = build_poller(tmp_path)
    h.sources[ACCOUNT].list_error = RuntimeError("boom")
    h.poller._poll_cycle()  # must not raise
    assert h.poller._poll_state[ACCOUNT].failures == 1  # treated like a transient failure


# --- account lifecycle -------------------------------------------------------------


def test_client_is_built_once_per_account(tmp_path):
    h = build_poller(tmp_path)
    load(h, ACCOUNT, [make_mail("m1", received=datetime(2026, 1, 1, tzinfo=UTC))])
    h.poller._poll_cycle()
    h.poller._poll_cycle()
    assert h.poller._clients == {ACCOUNT: h.sources[ACCOUNT]}  # cached and reused


def test_new_account_is_picked_up_by_reload(tmp_path):
    h = build_poller(tmp_path, accounts=(ACCOUNT,))
    load(h, ACCOUNT, [make_mail("m1", received=datetime(2026, 1, 1, tzinfo=UTC))])
    h.poller._poll_cycle()

    other = "b@example.com"
    h.store.add(other)
    h.poller.reload_accounts()
    load(
        h, other, [make_mail("b1", received=datetime(2026, 1, 1, 1, 0, tzinfo=UTC), account=other)]
    )
    h.poller._poll_cycle()
    assert h.sources[other].list_calls == 1  # baselined silently
    assert h.new_events == []


def test_account_removed_mid_loop_stops_being_polled(tmp_path):
    h = build_poller(tmp_path, accounts=(ACCOUNT, "b@example.com"))
    base = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    load(h, ACCOUNT, [make_mail("a1", received=base)])
    load(h, "b@example.com", [make_mail("b1", received=base, account="b@example.com")])
    h.poller._poll_cycle()  # both baselined
    assert set(h.sources) == {ACCOUNT, "b@example.com"}

    h.store.remove(ACCOUNT)
    h.poller.reload_accounts()
    calls_before = h.sources[ACCOUNT].list_calls
    h.poller._poll_cycle()
    assert h.sources[ACCOUNT].list_calls == calls_before  # no longer polled
    remaining = {m.account for m in h.state.latest(10)}
    assert remaining == {"b@example.com"}  # its mails left the state too


# --- real-thread behaviour ------------------------------------------------------------


def wait_for_baseline(h, timeout: float = 5.0) -> bool:
    source = h.sources[ACCOUNT]
    for _ in range(int(timeout / 0.05)):
        if source.list_calls >= 1:
            return True
        time.sleep(0.05)
    return False


def test_stop_is_prompt(tmp_path):
    h = build_poller(tmp_path, interval=600)
    thread = threading.Thread(target=h.poller.run, name="poller", daemon=True)
    thread.start()
    assert wait_for_baseline(h)
    began = time.monotonic()
    h.poller.stop()
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert time.monotonic() - began < 1.5  # did not wait out the 600 s interval


def test_wake_triggers_immediate_poll(tmp_path):
    h = build_poller(tmp_path, interval=600)
    recent = datetime.now(UTC) - timedelta(hours=1)
    load(h, ACCOUNT, [make_mail("m_old", received=recent)])
    arrived = threading.Event()
    h.poller._on_new_mails = lambda email, mails: arrived.set()  # type: ignore[assignment]

    thread = threading.Thread(target=h.poller.run, name="poller", daemon=True)
    thread.start()
    assert wait_for_baseline(h)

    load(
        h,
        ACCOUNT,
        [make_mail("m_new", received=datetime.now(UTC)), make_mail("m_old", received=recent)],
    )
    began = time.monotonic()
    h.poller.wake()
    assert arrived.wait(5.0)  # far sooner than the 600 s interval
    assert time.monotonic() - began < 5.0
    h.poller.stop()
    thread.join(timeout=2.0)


def test_rebaseline_rearms_silently(tmp_path):
    h = build_poller(tmp_path)
    base = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    load(h, ACCOUNT, [make_mail("m1", received=base)])
    h.poller._poll_cycle()  # baseline: cutoff = 12:00

    # A mail that arrived after the baseline but before an only_primary toggle.
    load(
        h,
        ACCOUNT,
        [make_mail("m2", received=base + timedelta(minutes=5)), make_mail("m1", received=base)],
    )
    h.poller.rebaseline()
    h.poller._poll_cycle()
    assert h.new_events == []  # the re-baseline swallows it without a toast
    assert h.poller._poll_state[ACCOUNT].baseline_done is True  # re-armed

    load(
        h,
        ACCOUNT,
        [
            make_mail("m3", received=base + timedelta(minutes=10)),
            make_mail("m2", received=base + timedelta(minutes=5)),
            make_mail("m1", received=base),
        ],
    )
    h.poller._poll_cycle()
    assert [m.id for m in h.new_events[0][1]] == ["m3"]  # later arrivals still toast
