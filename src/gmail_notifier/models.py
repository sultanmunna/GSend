"""Frozen data types shared across modules: Mail, Account, AccountStatus.

Pure data only, no I/O. Every field of `Mail` is private (docs/SECURITY.md
section 2): it must never be persisted, logged or written anywhere — RAM only.
`Mail.received_at` is a timezone-aware UTC datetime taken from Gmail's
internalDate, never from the local clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, auto


class AccountStatus(StrEnum):
    """State of one account's connection to Gmail."""

    OK = auto()
    NEEDS_REAUTH = auto()
    ERROR = auto()


@dataclass(frozen=True)
class Mail:
    """One inbox mail. RAM only — never persist, log or copy any field to disk."""

    account: str  # receiving Gmail address
    id: str
    thread_id: str
    sender_name: str  # decoded display name, or the address if no name
    sender_email: str
    subject: str  # decoded, "(no subject)" if empty
    snippet: str  # cleaned preview
    received_at: datetime  # UTC, from Gmail's internalDate
    unread: bool


@dataclass(frozen=True)
class Account:
    """One configured account: email plus optional hand-edited label."""

    email: str
    label: str | None
    status: AccountStatus
