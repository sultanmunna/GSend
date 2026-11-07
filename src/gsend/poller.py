"""Polling loop, implementing docs/ARCHITECTURE.md section 7 exactly.

One worker thread owns the Gmail clients (built via the injected
`client_factory(email) -> MailSource`, one per account, single-thread use);
this module never imports googleapiclient. Baseline never toasts; a mail
toasts once when it is unseen, unread and newer than the cutoff taken from
Google's internalDate. Transient failures back off exponentially
(min(interval * 2**failures, 300)); ReauthRequired pauses the account,
reports NEEDS_REAUTH and fires on_reauth_needed once per pause. No exception
may escape the loop (docs/ARCHITECTURE.md section 9).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from gsend import errors
from gsend.accounts import AccountStore
from gsend.models import Account, AccountStatus, Mail
from gsend.state import AppState

if TYPE_CHECKING:
    from gsend.gmail_client import MailSource
    from gsend.settings import Settings

logger = logging.getLogger(__name__)

_FETCH_LIMIT = 10  # latest ids requested per poll (ARCHITECTURE section 8)
_FETCH_CAP = 10  # at most 10 new mails fetched per account per poll
_SEEN_LIMIT = 500  # seen_ids bound; oldest dropped first
_BACKOFF_CAP_SECONDS = 300.0


@dataclass
class _AccountPollState:
    """Per-account bookkeeping (ARCHITECTURE section 7)."""

    seen_ids: dict[str, None] = field(default_factory=dict)  # ordered set, bounded
    cache: dict[str, Mail] = field(default_factory=dict)
    baseline_done: bool = False
    cutoff: datetime | None = None
    failures: int = 0
    next_allowed: float = 0.0  # monotonic time of the next permitted attempt
    paused: bool = False  # set on ReauthRequired until reload_accounts()
    problem_reported: bool = False  # a NEEDS_REAUTH/ERROR status is currently set


class Poller:
    """Polls every account, maintains state and emits new-mail events."""

    def __init__(
        self,
        client_factory: Callable[[str], MailSource],
        account_store: AccountStore,
        state: AppState,
        settings: Settings,
        on_new_mails: Callable[[str, list[Mail]], None],
        on_reauth_needed: Callable[[str], None] | None = None,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client_factory = client_factory
        self._account_store = account_store
        self._state = state
        self._settings = settings
        self._on_new_mails = on_new_mails
        self._on_reauth_needed = on_reauth_needed
        self._time_fn = time_fn
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._lock = threading.Lock()
        self._poll_state: dict[str, _AccountPollState] = {}
        self._clients: dict[str, object] = {}

    # -- lifecycle ------------------------------------------------------------

    def run(self) -> None:
        """The polling loop; run in a dedicated thread. Returns promptly after stop()."""
        self.reload_accounts()
        while not self._stop_event.is_set():
            self._wake_event.clear()  # a wake() during the cycle still wins
            self._poll_cycle()
            if self._stop_event.is_set():
                break
            self._wake_event.wait(self._wait_timeout())

    def stop(self) -> None:
        """Request a prompt stop; safe to call from any thread."""
        self._stop_event.set()
        self._wake_event.set()

    def wake(self) -> None:
        """Run a poll cycle immediately (Check now, account added)."""
        self._wake_event.set()

    def update_settings(self, settings: Settings) -> None:
        """Swap the settings snapshot (menu toggles); takes effect next cycle."""
        self._settings = settings

    def rebaseline(self) -> None:
        """Re-baseline every account silently; the next poll resets the cutoff.

        Used after an only_primary change so mails that newly appear in the
        wider listing never toast; arrivals after the toggle still do.
        """
        with self._lock:
            for poll in self._poll_state.values():
                poll.baseline_done = False

    def reload_accounts(self) -> None:
        """Re-read the account store (add/remove at runtime, resume after re-sign-in).

        New accounts start with fresh bookkeeping; removed accounts are dropped
        with their clients; remaining accounts are unpaused, so a successful
        re-sign-in resumes polling.
        """
        with self._lock:
            accounts = self._account_store.list()
            emails = [a.email for a in accounts]
            for email in emails:
                self._poll_state.setdefault(email, _AccountPollState())
                self._poll_state[email].paused = False
            for email in list(self._poll_state):
                if email not in emails:
                    del self._poll_state[email]
                    self._clients.pop(email, None)
            self._state.set_accounts(
                [Account(a.email, a.label, AccountStatus.OK) for a in accounts]
            )
        self.wake()

    # -- polling ----------------------------------------------------------------

    def _poll_cycle(self) -> None:
        with self._lock:
            emails = list(self._poll_state)
        for email in emails:
            if self._stop_event.is_set():
                return
            poll = self._poll_state.get(email)
            if poll is None or poll.paused or self._time_fn() < poll.next_allowed:
                continue
            try:
                self._poll_account(email, poll)
            except errors.ReauthRequired:
                self._handle_reauth(email, poll)
            except errors.TransientError as exc:
                self._handle_transient(email, poll, exc)
            except errors.GmailError as exc:
                self._handle_hard_error(email, poll, exc)
            except Exception as exc:
                # The loop must survive anything (ARCHITECTURE section 9).
                logger.exception("unexpected poll error (%s)", type(exc).__name__)
                self._handle_transient(email, poll, exc)

    def _poll_account(self, email: str, poll: _AccountPollState) -> None:
        client = self._client_for(email)
        ids = client.latest_inbox_ids(limit=_FETCH_LIMIT, only_primary=self._settings.only_primary)
        missing = [i for i in ids if i not in poll.cache]
        fetched_by_id: dict[str, Mail] = {}
        for message_id in missing[:_FETCH_CAP]:
            fetched_by_id[message_id] = client.get_mail(message_id)

        if not poll.baseline_done:
            cached = [poll.cache[i] for i in ids if i in poll.cache]
            known = list(fetched_by_id.values()) + cached
            # Google's time, not the PC clock; `or now` only for an empty inbox.
            poll.cutoff = max((m.received_at for m in known), default=None) or datetime.now(UTC)
            self._remember_seen(poll, ids)
            poll.baseline_done = True
            new: list[Mail] = []  # baseline never toasts
        else:
            new = [
                m
                for m in fetched_by_id.values()
                if m.id not in poll.seen_ids
                and m.unread
                and poll.cutoff is not None
                and m.received_at > poll.cutoff
            ]
            self._remember_seen(poll, missing)

        fresh_cache: dict[str, Mail] = {}
        for message_id in ids:  # prune to the current top 10
            if message_id in fetched_by_id:
                fresh_cache[message_id] = fetched_by_id[message_id]
            elif message_id in poll.cache:
                fresh_cache[message_id] = poll.cache[message_id]
        poll.cache = fresh_cache

        self._state.update_mails(email, [fresh_cache[i] for i in ids if i in fresh_cache])
        if new:  # newest first
            self._on_new_mails(email, new)

        poll.failures = 0  # reset on success
        if poll.problem_reported:
            poll.problem_reported = False
            self._state.set_account_status(email, AccountStatus.OK)

    # -- failure handling -------------------------------------------------------

    def _handle_reauth(self, email: str, poll: _AccountPollState) -> None:
        poll.paused = True
        poll.failures = 0
        if not poll.problem_reported:  # one event per pause episode
            poll.problem_reported = True
            self._state.set_account_status(email, AccountStatus.NEEDS_REAUTH)
            if self._on_reauth_needed is not None:
                self._on_reauth_needed(email)
        logger.info("account paused; reauth needed")

    def _handle_transient(self, email: str, poll: _AccountPollState, exc: Exception) -> None:
        poll.failures += 1
        delay = min(self._interval() * 2**poll.failures, _BACKOFF_CAP_SECONDS)
        poll.next_allowed = self._time_fn() + delay
        logger.warning("poll failed (%s); backing off %.0fs", type(exc).__name__, delay)

    def _handle_hard_error(self, email: str, poll: _AccountPollState, exc: Exception) -> None:
        # e.g. HTTP 403: report once as ERROR, keep retrying quietly.
        if not poll.problem_reported:
            poll.problem_reported = True
            self._state.set_account_status(email, AccountStatus.ERROR)
        self._handle_transient(email, poll, exc)

    # -- helpers ------------------------------------------------------------------

    def _client_for(self, email: str) -> object:
        client = self._clients.get(email)
        if client is None:
            client = self._client_factory(email)
            self._clients[email] = client
        return client

    @staticmethod
    def _remember_seen(poll: _AccountPollState, ids: list[str]) -> None:
        for message_id in ids:
            poll.seen_ids[message_id] = None
        while len(poll.seen_ids) > _SEEN_LIMIT:
            poll.seen_ids.pop(next(iter(poll.seen_ids)))

    def _interval(self) -> int:
        return int(self._settings.poll_interval_seconds)

    def _wait_timeout(self) -> float:
        """Seconds to wait: the soonest backoff deadline, capped at the interval."""
        now = self._time_fn()
        with self._lock:
            upcoming = [p.next_allowed for p in self._poll_state.values() if p.next_allowed > now]
        soonest = min(upcoming, default=now + self._interval())
        return min(max(soonest - now, 0.0), float(self._interval()))
