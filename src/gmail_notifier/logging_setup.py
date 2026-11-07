"""Rotating file logging under %LOCALAPPDATA%\\GmailNotifier\\logs; console only in dev.

Logging rules (docs/SECURITY.md section 5): events, counts, durations and error
classes only — never mail content, tokens or client secrets. This module only
configures handlers; every call site must obey the content rules.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from gmail_notifier import config

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 512 * 1024
_BACKUP_COUNT = 3

# Handlers added by the last setup_logging() call, so a re-run can replace them.
_added_handlers: list[logging.Handler] = []


def setup_logging(
    *,
    console: bool | None = None,
    log_dir: Path | None = None,
    debug: bool = False,
) -> list[logging.Handler]:
    """Configure root logging and return the handlers added (for tests and cleanup).

    `console=None` means: attach a console handler only when not running as a
    frozen (PyInstaller) build, i.e. only in development. The rotating file
    handler is always attempted; if the log folder cannot be created, file
    logging is skipped instead of crashing the app.
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    for old in _added_handlers:
        root.removeHandler(old)
        old.close()
    _added_handlers.clear()
    _silence_google_loggers()

    formatter = logging.Formatter(_LOG_FORMAT, _LOG_DATE_FORMAT)

    if console is None:
        console = not getattr(sys, "frozen", False)
    if console:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)
        _added_handlers.append(stream_handler)

    directory = log_dir if log_dir is not None else config.logs_dir()
    try:
        config.ensure_dir(directory)
        file_handler = RotatingFileHandler(
            directory / config.LOG_FILE_NAME,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
        _added_handlers.append(file_handler)
    except OSError:
        logging.getLogger(__name__).warning(
            "file logging unavailable; continuing without a log file"
        )
    return list(_added_handlers)


def _silence_google_loggers() -> None:
    """Keep google* library chatter out of the logs.

    google_auth_oauthlib logs the full authorization URL (state, PKCE challenge,
    client_id) at INFO; docs/SECURITY.md section 5 forbids URLs in logs. These
    namespaces stay at WARNING so only real problems surface.
    """
    for name in ("google", "googleapiclient", "google_auth_oauthlib", "httplib2", "keyring"):
        logging.getLogger(name).setLevel(logging.WARNING)
