"""Pure URL builders for opening Gmail in the default browser, scoped to an account.

Per DECISIONS D-07, clicking a toast or menu item opens
`https://mail.google.com/mail/?authuser=<email>#all/<threadId>` — no inbox UI of
our own. The email is URL-quoted so addresses with a plus (or spaces) survive;
`@` is kept readable because Gmail accepts both forms.
"""

from __future__ import annotations

from urllib.parse import quote

from gmail_notifier import config


def mail_url(email: str, thread_id: str) -> str:
    """URL for one mail thread of `email`'s account."""
    return f"{config.GMAIL_BASE_URL}?authuser={quote(email, safe='@')}#all/{thread_id}"


def inbox_url(email: str) -> str:
    """URL for `email`'s inbox."""
    return f"{config.GMAIL_BASE_URL}?authuser={quote(email, safe='@')}#inbox"
