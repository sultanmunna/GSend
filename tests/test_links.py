"""Tests for the Gmail web URL builders (DECISIONS D-07)."""

from __future__ import annotations

import pytest

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


# --- Tamper resistance (SECURITY section 6): URLs come from validated parts ---

TAMPERED_IDS = [
    "../",
    "javascript:alert(1)",
    "http://evil.test/x",
    "a b",
    "abc$",
    "идентификатор",
    "",
    "16a7c1f2e3d4b5a6;calc",
    "16a7 c1f2",
]


def test_mail_url_rejects_tampered_thread_ids():
    for bad in TAMPERED_IDS:
        with pytest.raises(ValueError):
            links.mail_url("user@gmail.com", bad)


def test_mail_url_accepts_hex_and_numeric_ids():
    for good in ("16a7c1f2e3d4b5a6", "17955180370727458419", "ABCDEF0123456789"):
        url = links.mail_url("user@gmail.com", good)
        assert url.endswith(f"#all/{good}")
        assert url.startswith("https://mail.google.com/mail/")


def test_mail_url_rejects_malformed_emails():
    for bad_email in ("no-address", "a b@c.test", "a@b c", "", None, 5):
        with pytest.raises(ValueError):
            links.mail_url(bad_email, "cafe123")
        with pytest.raises(ValueError):
            links.inbox_url(bad_email)


def test_inbox_url_rejects_path_traversal_email():
    with pytest.raises(ValueError):
        links.inbox_url("../settings?x=1")
