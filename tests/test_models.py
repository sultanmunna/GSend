"""Tests for the frozen data models (docs/ARCHITECTURE.md section 4)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from gmail_notifier.models import Account, AccountStatus, Mail


def make_mail(**overrides: object) -> Mail:
    values: dict[str, object] = {
        "account": "user@example.com",
        "id": "msg-1",
        "thread_id": "thread-1",
        "sender_name": "John Smith",
        "sender_email": "john@example.com",
        "subject": "Meeting moved",
        "snippet": "See you at 3pm.",
        "received_at": datetime(2026, 11, 7, 12, 0, tzinfo=UTC),
        "unread": True,
    }
    values.update(overrides)
    return Mail(**values)  # type: ignore[arg-type]


def test_mail_is_frozen():
    mail = make_mail()
    with pytest.raises(FrozenInstanceError):
        mail.id = "msg-2"  # type: ignore[misc]


def test_account_is_frozen():
    account = Account(email="a@example.com", label=None, status=AccountStatus.OK)
    with pytest.raises(FrozenInstanceError):
        account.email = "b@example.com"


def test_account_status_values():
    assert AccountStatus.OK == "ok"
    assert AccountStatus.NEEDS_REAUTH == "needs_reauth"
    assert AccountStatus.ERROR == "error"


def test_mail_fields_and_equality():
    mail = make_mail()
    assert mail == make_mail()
    assert mail.received_at.tzinfo is not None
    assert mail.unread is True


def test_account_label_optional():
    plain = Account(email="a@example.com", label=None, status=AccountStatus.OK)
    labelled = Account(email="a@example.com", label="Work", status=AccountStatus.OK)
    assert plain.label is None
    assert labelled.label == "Work"
