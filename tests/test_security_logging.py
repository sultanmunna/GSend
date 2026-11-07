"""Tests for the log redaction layer (docs/SECURITY.md section 5, D-17)."""

from __future__ import annotations

import logging
import sys

import pytest

from gmail_notifier import security_logging


@pytest.fixture(autouse=True)
def clean_registry():
    security_logging.clear_secrets()
    yield
    security_logging.clear_secrets()


def make_formatter() -> security_logging.RedactingFormatter:
    return security_logging.RedactingFormatter("%(levelname)s %(message)s")


def make_record(msg: str, *args: object, exc_info: object = None) -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=exc_info,
    )


def test_registered_secret_is_redacted_from_message():
    security_logging.register_secret("super-secret-value-42")
    out = make_formatter().format(make_record("token %s leaked", "super-secret-value-42"))
    assert "super-secret-value-42" not in out
    assert "[REDACTED]" in out


def test_registered_secret_is_redacted_from_traceback():
    security_logging.register_secret("super-secret-value-42")
    try:
        raise ValueError("connect failed with token super-secret-value-42 end")
    except ValueError:
        # LogRecord wants the real (type, value, traceback) tuple, as the
        # logging module builds it for a logger call with exc_info=True.
        out = make_formatter().format(make_record("request failed", exc_info=sys.exc_info()))
    assert "super-secret-value-42" not in out  # the value is gone...
    assert "[REDACTED]" in out
    assert "ValueError" in out  # ...but the error class stays visible


def test_oauth_patterns_are_redacted_without_registration():
    for text in (
        "secret GOCSPX-abc123XYZ-d_e found",
        "Bearer ya29.c.b0AbCdEf-_01 accepted",
        "stored 1//0gXyZ-_123 ok",
        "redirect http://x/?code=4%2F0AX4abc&scope=email",
        "reply access_token=ya29.short body",
    ):
        assert "[REDACTED]" in security_logging.redact(text), text


def test_plain_text_is_untouched():
    text = "poll ok: 3 mails for account#1 in 1.2s"
    assert security_logging.redact(text) == text


def test_register_secret_ignores_short_and_empty():
    security_logging.register_secret("")
    security_logging.register_secret(None)
    security_logging.register_secret("abc")
    assert security_logging._registered == []


def test_registry_is_capped_oldest_first():
    for i in range(security_logging._MAX_SECRETS + 10):
        security_logging.register_secret(f"long-secret-value-{i:04d}")
    assert len(security_logging._registered) == security_logging._MAX_SECRETS
    assert security_logging._registered[0] == "long-secret-value-0010"  # oldest dropped


def test_redact_empty_string():
    assert security_logging.redact("") == ""
