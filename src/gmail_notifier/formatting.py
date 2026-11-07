"""Pure builders for menu lines, tooltip text and toast content from Mail/Settings.

Implements the exact formats and limits of docs/PRODUCT.md sections 6.2-6.5:
menu line 80, tooltip 127 total (including the newline), toast title 70 and
preview 180. The ellipsis counts as one character; the subject truncates
before the sender; the account appears per the show_account rule. No I/O.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from gmail_notifier import text_utils
from gmail_notifier.models import Mail
from gmail_notifier.settings import Settings

MENU_LINE_LIMIT = 80
TOOLTIP_LIMIT = 127  # Windows tray tooltip limit, including the newline
TOAST_TITLE_LIMIT = 70
TOAST_PREVIEW_LIMIT = 180

NO_SUBJECT = "(no subject)"
_NO_ACCOUNT_TOOLTIP = "Gmail Notifier: no account. Right-click to add one."
_SIGN_IN_TOOLTIP = "Gmail Notifier: sign-in needed. Right-click to fix."
_NO_MAIL_TOOLTIP = "Gmail Notifier: no recent mail"


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
    wins over the email address.
    """
    mode = settings.show_account
    if mode == "never":
        return None
    if mode == "auto" and account_count < 2:
        return None
    return label or email


def menu_line(mail: Mail, settings: Settings, show_account: str | None) -> str:
    """One tray menu line: marker + 'sender: subject' + optional account, <= 80."""
    marker = "● " if mail.unread else "  "
    suffix = f" · {show_account}" if show_account else ""
    budget = MENU_LINE_LIMIT - len(marker) - len(suffix)
    base = _fitted_sender_subject(mail.sender_name, _subject(mail), budget)
    return text_utils.truncate(f"{marker}{base}{suffix}", MENU_LINE_LIMIT)


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
