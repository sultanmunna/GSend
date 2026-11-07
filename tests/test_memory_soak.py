"""Memory soak: 50,000 poller cycles with a fake client must leave memory flat.

Robustness check for the idle-budget rule (hard rule 8, ~0% CPU / flat memory
between polls): the poller's bounded collections (seen_ids, per-account cache,
AppState lists, opened set) must not grow with cycles. tracemalloc measures the
Python heap across the soak. The run is steady state — one mail re-polled —
which is exactly the idle path the app lives in for days; the baseline absorbs
it (never toasts), and a second mail introduced at the midpoint proves the
new-mail path still fires after 25,000 cycles.
"""

from __future__ import annotations

import tempfile
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path

from gmail_notifier.accounts import AccountStore
from gmail_notifier.models import Mail
from gmail_notifier.poller import Poller
from gmail_notifier.settings import Settings
from gmail_notifier.state import AppState

CYCLES = 50_000
_TOLERANCE_KIB = 512  # generous: measured growth over 3k cycles was < 1 KiB

_MAIL_A = Mail(
    account="a@example.com",
    id="16a7c1f2e3d4b5a6",
    thread_id="16a7c1f2e3d4b5a6",
    sender_name="Steady Sender",
    sender_email="steady@example.com",
    subject="Steady subject",
    snippet="Steady snippet",
    received_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    unread=True,
)
_MAIL_B = Mail(
    account="a@example.com",
    id="18b8d2e4f5a6c7d8",
    thread_id="18b8d2e4f5a6c7d8",
    sender_name="Later Sender",
    sender_email="later@example.com",
    subject="Later subject",
    snippet="Later snippet",
    received_at=datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
    unread=True,
)


class SoakFakeSource:
    """Serves mail A until switched, then mail B (one mid-soak arrival)."""

    def __init__(self) -> None:
        self.mail = _MAIL_A

    def latest_inbox_ids(self, limit: int, only_primary: bool) -> list[str]:
        return [self.mail.id]

    def get_mail(self, message_id: str) -> Mail:
        return self.mail


def test_poller_memory_is_flat_over_50k_cycles():
    tmp = Path(tempfile.mkdtemp())
    store = AccountStore(tmp / "accounts.json")
    store.add("a@example.com")
    state = AppState()
    toasts = 0

    def on_new_mails(email: str, mails: list[Mail]) -> None:
        nonlocal toasts
        toasts += len(mails)  # count only: the callback must not retain mails

    source = SoakFakeSource()
    poller = Poller(
        client_factory=lambda email: source,
        account_store=store,
        state=state,
        settings=Settings(show_preview=False, poll_interval_seconds=20),
        on_new_mails=on_new_mails,
    )
    poller.reload_accounts()
    poller._poll_cycle()  # baseline: caches mail A, never toasts

    assert toasts == 0, "the baseline must stay silent"

    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    midpoint = CYCLES // 2
    for cycle in range(CYCLES):
        if cycle == midpoint:
            source.mail = _MAIL_B  # one new arrival mid-soak
        poller._poll_cycle()
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    growth_kib = sum(s.size_diff for s in after.compare_to(before, "lineno")) / 1024
    assert toasts == 1, "exactly the mid-soak arrival must toast, nothing else"
    assert growth_kib < _TOLERANCE_KIB, f"poller grew {growth_kib:.1f} KiB over {CYCLES} cycles"
