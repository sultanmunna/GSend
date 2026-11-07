"""Secret redaction for logs: a last-resort layer under the docs/SECURITY.md section 5 rules.

Call-site discipline keeps mail content and secrets out of log *calls*; this
module makes the two enumerable secret kinds structurally unleakable anyway:
every handler formats through `RedactingFormatter`, which scrubs registered
secret values (refresh tokens and the client secret — known strings at
runtime, registered by `auth.py`) plus OAuth-shaped patterns from messages
and traceback text. Mail content cannot be enumerated this way, so the
section 5 rules still apply to it at call sites.
"""

from __future__ import annotations

import logging
import re

_REDACTED = "[REDACTED]"
_MAX_SECRETS = 64  # cap the registry so long sessions cannot grow it without bound
_MIN_SECRET_LEN = 8  # shorter strings would mangle normal text when replaced

# OAuth-shaped values: client secrets, access tokens, Google refresh tokens
# ("1//…"), and code/token query parameters (SECURITY.md section 5).
_PATTERN = re.compile(
    "|".join(
        (
            r"GOCSPX-[A-Za-z0-9_-]+",
            r"\bya29\.[A-Za-z0-9._-]+",
            r"\b1//[A-Za-z0-9._-]+",
            r"\b(?:access_token|refresh_token|code)=[^&\s]+",
        )
    )
)

# List operations are GIL-atomic; the registry only grows in practice, so a
# concurrent redaction can miss at worst the entry being popped by the cap.
_registered: list[str] = []


def register_secret(value: str | None) -> None:
    """Remember a secret value to redact from every future log record.

    Called by `auth.py` when a refresh token or client secret enters memory.
    Empty and short values are ignored; the registry is capped oldest-first.
    """
    if not value or len(value) < _MIN_SECRET_LEN:
        return
    if value not in _registered:
        if len(_registered) >= _MAX_SECRETS:
            _registered.pop(0)
        _registered.append(value)


def clear_secrets() -> None:
    """Forget all registered secrets (test seam between cases)."""
    _registered.clear()


def redact(text: str) -> str:
    """Return `text` with registered secrets and OAuth-shaped values replaced."""
    if not text:
        return text
    for secret in _registered:
        if secret in text:
            text = text.replace(secret, _REDACTED)
    return _PATTERN.sub(_REDACTED, text)


class RedactingFormatter(logging.Formatter):
    """Standard formatter whose output (message and traceback) is scrubbed."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))
