"""Thread-safe in-memory store: accounts, latest mails, change subscriptions.

Mail data lives in RAM only (hard rule 3). Callbacks registered via subscribe()
run after each actual change, outside the lock, on the changing thread
(docs/ARCHITECTURE.md section 10); updates that change nothing stay silent so
idle poll cycles never re-render the UI. `mark_opened` is the local
acknowledgement that clears a mail's unread flag in the display only.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import replace

from gmail_notifier.models import Account, AccountStatus, Mail

_MAX_OPENED = 500  # bounded like the poller's seen_ids so memory stays flat


class AppState:
    """Thread-safe store read by the tray and written by the poller."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._accounts: dict[str, Account] = {}
        self._mails: dict[str, list[Mail]] = {}
        self._opened: dict[str, None] = {}  # ordered set of acknowledged mail ids
        self._subscribers: list[Callable[[], None]] = []

    # -- writes ---------------------------------------------------------------

    def set_accounts(self, accounts: Iterable[Account]) -> None:
        """Replace the account set; statuses of known accounts are preserved."""
        fresh = {a.email: a for a in accounts}
        with self._lock:
            merged: dict[str, Account] = {}
            for email, account in fresh.items():
                known = self._accounts.get(email)
                status = known.status if known is not None else account.status
                merged[email] = Account(account.email, account.label, status)
            changed = merged != self._accounts
            self._accounts = merged
            for email in list(self._mails):
                if email not in merged:
                    del self._mails[email]  # removed accounts lose their mails
        if changed:
            self._notify()

    def update_mails(self, email: str, mails: list[Mail]) -> None:
        """Replace one account's mail list (newest first); silent when unchanged."""
        with self._lock:
            if email not in self._accounts:
                return  # ignore mails for accounts we no longer track
            changed = self._mails.get(email) != mails
            if changed:
                self._mails[email] = list(mails)
        if changed:
            self._notify()

    def set_account_status(self, email: str, status: AccountStatus) -> None:
        with self._lock:
            account = self._accounts.get(email)
            if account is None or account.status == status:
                return
            self._accounts[email] = Account(account.email, account.label, status)
        self._notify()

    def mark_opened(self, mail_id: str) -> None:
        """Locally acknowledge a mail; it displays as read until the app restarts."""
        with self._lock:
            if mail_id in self._opened:
                return
            self._opened[mail_id] = None
            while len(self._opened) > _MAX_OPENED:
                self._opened.pop(next(iter(self._opened)))
        self._notify()

    def subscribe(self, callback: Callable[[], None]) -> None:
        """Register a change callback; it fires on later changes, outside the lock."""
        with self._lock:
            self._subscribers.append(callback)

    def accounts(self) -> list[Account]:
        """Current accounts with their statuses (insertion order)."""
        with self._lock:
            return list(self._accounts.values())

    # -- reads ----------------------------------------------------------------

    def latest(self, n: int = 3) -> list[Mail]:
        """Latest n mails merged across accounts, newest first, display-ready."""
        with self._lock:
            every = [mail for mails in self._mails.values() for mail in mails]
            top = sorted(every, key=lambda m: m.received_at, reverse=True)[:n]
            return [
                replace(mail, unread=False) if mail.id in self._opened else mail for mail in top
            ]

    def has_unread(self) -> bool:
        with self._lock:
            return any(
                mail.unread and mail.id not in self._opened
                for mails in self._mails.values()
                for mail in mails
            )

    def worst_status(self) -> AccountStatus:
        """The status that should drive the icon: NEEDS_REAUTH over ERROR over OK."""
        with self._lock:
            statuses = [account.status for account in self._accounts.values()]
        if any(s is AccountStatus.NEEDS_REAUTH for s in statuses):
            return AccountStatus.NEEDS_REAUTH
        if any(s is AccountStatus.ERROR for s in statuses):
            return AccountStatus.ERROR
        return AccountStatus.OK

    # -- internal ---------------------------------------------------------------

    def _notify(self) -> None:
        for callback in tuple(self._subscribers):
            callback()
