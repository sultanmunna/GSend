"""Tests for the Gmail web URL builders (DECISIONS D-07)."""

from __future__ import annotations

from gmail_notifier import links


def test_mail_url_quotes_plus_in_email():
    assert links.mail_url("someone+filter@gmail.com", "cafe123") == (
        "https://mail.google.com/mail/?authuser=someone%2Bfilter@gmail.com#all/cafe123"
    )


def test_mail_url_plain_email():
    assert links.mail_url("user@gmail.com", "abc123") == (
        "https://mail.google.com/mail/?authuser=user@gmail.com#all/abc123"
    )


def test_inbox_url():
    assert links.inbox_url("user@gmail.com") == (
        "https://mail.google.com/mail/?authuser=user@gmail.com#inbox"
    )
