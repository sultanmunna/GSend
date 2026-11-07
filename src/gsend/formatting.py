"""Pure builders for menu lines, tooltip text and toast content from Mail/Settings.

Implements the exact formats and limits of docs/PRODUCT.md sections 6.2-6.5:
menu line 64, tooltip 127 total (including the newline), toast title 70 and
preview 180. The ellipsis counts as one character; the subject truncates
before the sender; the account appears per the show_account rule. Menu lines
end in a tab plus a right-aligned column ("age · account") — text after "\\t"
renders right-aligned in a Win32 menu (D-16). No I/O.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from gsend import text_utils
from gsend.models import Mail
from gsend.settings import Settings

MENU_LINE_LIMIT = 64  # 80 made the Win32 menu extremely wide (D-16)
_AGE_COLUMN_LIMIT = 24  # cap for the right-aligned tab column
TOOLTIP_LIMIT = 127  # Windows tray tooltip limit, including the newline
TOAST_TITLE_LIMIT = 70
TOAST_PREVIEW_LIMIT = 180

NO_SUBJECT = "(no subject)"
_NO_ACCOUNT_TOOLTIP = "GSend: no account. Right-click to add one."
_SIGN_IN_TOOLTIP = "GSend: sign-in needed. Right-click to fix."
_NO_MAIL_TOOLTIP = "GSend: no recent mail"


@dataclass(frozen=True)
class ToastContent:
    """Ready-to-show toast: a title plus body lines."""

    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class TooltipSnapshot:
    """What the tooltip needs from AppState, resolved by app/tray."""

    account_count: int
    needs_sign_in: bool
    latest: Mail | None
    show_account: str | None  # resolved display string, or None when hidden


def account_display(
    settings: Settings, account_count: int, email: str, label: str | None = None
) -> str | None:
    """The account display string per the show_account rule, or None when hidden.

    auto shows the account only with two or more accounts; a hand-edited label
    wins; without one, the local part of the address keeps lines short
    ('justforkickak' instead of 'justforkickak@gmail.com').
    """
    mode = settings.show_account
    if mode == "never":
        return None
    if mode == "auto" and account_count < 2:
        return None
    local = email.partition("@")[0]
    return label or local or email


def relative_age(received_at: datetime, *, now: datetime | None = None) -> str:
    """Compact Gmail-style age of a mail: 'now', '5m', '3h', '2d'.

    `received_at` is timezone-aware UTC (Mail.received_at); a mail dated in
    the future (clock skew) counts as 'now'.
    """
    now = now or datetime.now(UTC)
    seconds = max((now - received_at).total_seconds(), 0.0)
    minutes = int(seconds // 60)
    if seconds < 60:
        return "now"
    if minutes < 60:
        return f"{minutes}m"
    if minutes < 24 * 60:
        return f"{minutes // 60}h"
    return f"{minutes // (24 * 60)}d"


def menu_line(
    mail: Mail, settings: Settings, show_account: str | None, *, now: datetime | None = None
) -> str:
    """One tray menu line, <= MENU_LINE_LIMIT characters including the tab column.

    Layout: '● /○ sender: subject\\t{age} · {account}' — the filled marker means
    unread, the hollow one read (same width in Segoe UI, so senders align), and
    the age plus optional account sit in the right-aligned Win32 tab column
    (D-16). The subject truncates before the sender, as before.
    """
    marker = "● " if mail.unread else "○ "
    age = relative_age(mail.received_at, now=now)
    right = f"{age} · {show_account}" if show_account else age
    right = text_utils.truncate(right, _AGE_COLUMN_LIMIT)
    left_budget = MENU_LINE_LIMIT - len(marker) - 1 - len(right)  # 1 for the tab
    base = _fitted_sender_subject(mail.sender_name, _subject(mail), left_budget)
    return f"{marker}{base}\t{right}"


def tooltip(snapshot: TooltipSnapshot, settings: Settings) -> str:
    """Hover tooltip <= 127 chars; the subject truncates first, then the sender."""
    if snapshot.account_count == 0:
        return _NO_ACCOUNT_TOOLTIP
    if snapshot.needs_sign_in:
        return _SIGN_IN_TOOLTIP
    mail = snapshot.latest
    if mail is None:
        return _NO_MAIL_TOOLTIP
    suffix = f" · {snapshot.show_account}" if snapshot.show_account else ""
    subject_budget = TOOLTIP_LIMIT - 1 - len(mail.sender_name) - len(suffix)
    fitted_subject = text_utils.truncate(_subject(mail), max(subject_budget, 1))
    sender_budget = TOOLTIP_LIMIT - 1 - len(fitted_subject) - len(suffix)
    fitted_sender = text_utils.truncate(mail.sender_name, max(sender_budget, 1))
    text = f"{fitted_sender}{suffix}\n{fitted_subject}"
    return text if len(text) <= TOOLTIP_LIMIT else text[:TOOLTIP_LIMIT]


def toast_content(mail: Mail, settings: Settings, show_account: str | None) -> ToastContent:
    """Toast per PRODUCT 6.4: subject title, sender line, optional preview."""
    title = text_utils.truncate(_subject(mail), TOAST_TITLE_LIMIT)
    suffix = f" · {show_account}" if show_account else ""
    lines = [f"{mail.sender_name}{suffix}"]
    if settings.show_preview and mail.snippet:
        lines.append(text_utils.truncate(mail.snippet, TOAST_PREVIEW_LIMIT))
    return ToastContent(title=title, lines=tuple(lines))


def summary_toast(mails: Sequence[Mail], account: str | None) -> ToastContent:
    """Burst summary per PRODUCT 6.4: '{n} new mails' / '{s1}, {s2}, {s3} and {k} more'."""
    count = len(mails)
    names = [mail.sender_name for mail in mails[:3]]
    body = ", ".join(names)
    remaining = count - len(names)
    if remaining > 0:
        body = f"{body} and {remaining} more" if body else f"{remaining} more"
    if account:
        body = f"{body} · {account}" if body else account
    return ToastContent(title=f"{count} new mails", lines=(body,) if body else ())


def _subject(mail: Mail) -> str:
    return mail.subject or NO_SUBJECT


def _fitted_sender_subject(sender: str, subject: str, budget: int) -> str:
    """ "sender: subject" within budget.

    The subject truncates first when it overflows; when the sender alone cannot
    fit, the sender truncates instead so a short subject survives.
    """
    separator = ": "
    if len(sender) + len(separator) + len(subject) <= budget:
        return f"{sender}{separator}{subject}"
    subject_room = budget - len(sender) - len(separator)
    if subject_room >= 1:
        return f"{sender}{separator}{text_utils.truncate(subject, subject_room)}"
    sender_room = budget - len(separator) - len(subject)
    if sender_room >= 1:
        return f"{text_utils.truncate(sender, sender_room)}{separator}{subject}"
    fitted_sender = text_utils.truncate(sender, max(budget // 2, 1))
    subject_room = max(budget - len(separator) - len(fitted_sender), 1)
    fitted_subject = text_utils.truncate(subject, subject_room)
    return f"{fitted_sender}{separator}{fitted_subject}"
