"""Pure URL builders for opening Gmail in the default browser, scoped to an account.

Per DECISIONS D-07, clicking a toast or menu item opens
`https://mail.google.com/mail/?authuser=<email>#all/<threadId>` — no inbox UI of
our own. The email is URL-quoted so addresses with a plus (or spaces) survive;
`@` is kept readable because Gmail accepts both forms.

Only validated parts ever reach the URL (docs/SECURITY.md section 6): the host
is the fixed Gmail base URL, the email must have an address shape, and Gmail
message/thread IDs must be hex strings — anything else raises `ValueError` so
callers can reject the tampered value instead of building a URL from it.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from gsend import config

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+$")
_MESSAGE_ID_RE = re.compile(r"^[0-9a-fA-F]+$")


def _validated_email(email: str) -> str:
    if not isinstance(email, str) or not _EMAIL_RE.match(email):
        raise ValueError(
            f"refusing to build a Gmail URL for this account value ({type(email).__name__})"
        )
    return email


def _validated_message_id(message_id: str) -> str:
    if not isinstance(message_id, str) or not _MESSAGE_ID_RE.match(message_id):
        raise ValueError(
            f"refusing to build a Gmail URL for this message id ({type(message_id).__name__})"
        )
    return message_id


def mail_url(email: str, thread_id: str) -> str:
    """URL for one mail thread of `email`'s account.

    Raises `ValueError` for a non-hex thread id or a malformed email — a URL is
    never built from unvalidated parts.
    """
    _validated_email(email)
    _validated_message_id(thread_id)
    return f"{config.GMAIL_BASE_URL}?authuser={quote(email, safe='@')}#all/{thread_id}"


def inbox_url(email: str) -> str:
    """URL for `email`'s inbox. Raises `ValueError` for a malformed email."""
    _validated_email(email)
    return f"{config.GMAIL_BASE_URL}?authuser={quote(email, safe='@')}#inbox"
