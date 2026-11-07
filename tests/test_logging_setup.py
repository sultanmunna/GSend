"""Smoke tests for logging setup: rotating file handler, no duplicate handlers on re-run."""

from __future__ import annotations

import logging

from gmail_notifier import logging_setup


def test_setup_writes_to_file(tmp_path):
    handlers = logging_setup.setup_logging(console=False, log_dir=tmp_path)
    try:
        logging.getLogger("gmail_notifier.test").info("startup smoke")
        log_file = tmp_path / "app.log"
        assert log_file.exists()
        assert "startup smoke" in log_file.read_text(encoding="utf-8")
    finally:
        root = logging.getLogger()
        for handler in handlers:
            root.removeHandler(handler)
            handler.close()


def test_setup_twice_does_not_duplicate_file_handlers(tmp_path):
    root = logging.getLogger()
    first = logging_setup.setup_logging(console=False, log_dir=tmp_path)
    second = logging_setup.setup_logging(console=False, log_dir=tmp_path)
    try:
        # Only our handlers are managed: exactly one file handler, from the last call.
        assert len(second) == 1
        assert all(handler not in root.handlers for handler in first)
        assert second[0] in root.handlers
    finally:
        for handler in [*first, *second]:
            root.removeHandler(handler)
            handler.close()


def test_google_library_loggers_are_silenced(tmp_path):
    handlers = logging_setup.setup_logging(console=False, log_dir=tmp_path)
    try:
        # google_auth_oauthlib logs full OAuth URLs at INFO; they must not pass.
        assert logging.getLogger("google").level == logging.WARNING
        assert logging.getLogger("google_auth_oauthlib").level == logging.WARNING
        assert logging.getLogger("googleapiclient").level == logging.WARNING
    finally:
        root = logging.getLogger()
        for handler in handlers:
            root.removeHandler(handler)
            handler.close()
