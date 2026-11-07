"""Memory soak: 50,000 poller cycles with a fake client must leave memory flat.

Robustness check for the idle-budget rule (hard rule 8, ~0% CPU / flat memory
between polls): the poller's bounded collections (seen_ids, per-account cache,
AppState lists, opened set) and the rotating log must not grow with cycles.
tracemalloc measures the Python heap across the soak; a steady-state run
re-polls the same mail, exactly the idle path the app lives in for days.
"""

from __future__ import annotations

import tempfile
import tracemalloc
from datetime import UTC, datetime, timedelta
from pathlib import Path

from gmail_notifier.accounts import AccountStore
from gmail_notifier.models import Mail
from gmail_notifier.poller import Poller
from gmail_notifier.settings import Settings
from gmail_notifier.state import AppState

CYCLES = 50_000
_TOLERANCE_KIB = 512  # generous: measured growth over 3k cycles was < 1 KiB


class SteadyFakeSource:
    """One stable inbox: the same single mail on every poll."""

    def latest_inbox_ids(self, limit: int, only_primary: bool) -> list[str]:
        return ["16a7c1f2e3d4b5a6"]

    def get_mail(self, message_id: str) -> Mail:
        return Mail(
            account="a@example.com",
            id="16a7c1f2e3d4b5a6",
            thread_id="16a7c1f2e3d4b5a6",
            sender_name="Steady Sender",
            sender_email="steady@example.com",
            subject="Steady subject",
            snippet="Steady snippet",
            received_at=datetime.now(UTC) - timedelta(seconds=5),
            unread=True,
        )


def test_poller_memory_is_flat_over_50k_cycles():
    tmp = Path(tempfile.mkdtemp())
    store = AccountStore(tmp / "accounts.json")
    store.add("a@example.com")
    state = AppState()
    toasts = 0

    def on_new_mails(email: str, mails: list[Mail]) -> None:
        nonlocal toasts
        toasts += len(mails)  # count only: the callback must not retain mails

    poller = Poller(
        client_factory=lambda email: SteadyFakeSource(),
        account_store=store,
        state=state,
        settings=Settings(show_preview=False, poll_interval_seconds=20),
        on_new_mails=on_new_mails,
    )
    poller.reload_accounts()
    poller._poll_cycle()  # baseline: caches the mail, never toasts
    poller._poll_cycle()  # first steady cycle: the one toast the mail earns

    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    for _ in range(CYCLES):
        poller._poll_cycle()
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    growth_kib = sum(s.size_diff for s in after.compare_to(before, "lineno")) / 1024
    assert toasts == 1, "steady state must not re-toast the same mail"
    assert growth_kib < _TOLERANCE_KIB, f"poller grew {growth_kib:.1f} KiB over {CYCLES} cycles"
