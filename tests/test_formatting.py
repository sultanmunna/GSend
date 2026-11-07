"""Tests for the pure formatting rules (docs/PRODUCT.md sections 6.2-6.5)."""

from __future__ import annotations

from datetime import UTC, datetime

from gmail_notifier import formatting
from gmail_notifier.formatting import (
    TooltipSnapshot,
    account_display,
    menu_line,
    relative_age,
    summary_toast,
    toast_content,
    tooltip,
)
from gmail_notifier.models import Mail
from gmail_notifier.settings import Settings

# 5 minutes after make_mail's fixed received_at, so ages are deterministic
NOW = datetime(2026, 1, 1, 12, 5, tzinfo=UTC)


def make_mail(
    mid: str = "m1",
    *,
    sender: str = "Jane Doe",
    subject: str = "Hello",
    snippet: str = "Some preview text",
    unread: bool = True,
    account: str = "you@gmail.com",
) -> Mail:
    return Mail(
        account=account,
        id=mid,
        thread_id=f"t-{mid}",
        sender_name=sender,
        sender_email="jane@example.com",
        subject=subject,
        snippet=snippet,
        received_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        unread=unread,
    )


def snapshot(
    *,
    accounts: int = 2,
    needs_sign_in: bool = False,
    latest: Mail | None = None,
    show: str | None = None,
) -> TooltipSnapshot:
    return TooltipSnapshot(
        account_count=accounts,
        needs_sign_in=needs_sign_in,
        latest=latest,
        show_account=show,
    )


# --- account_display -----------------------------------------------------------


def test_account_display_rules():
    one = Settings()
    assert account_display(one, 1, "a@x.com") is None  # auto: hidden with one account
    assert account_display(one, 2, "a@x.com") == "a"  # auto: local part with 2+ accounts
    assert account_display(one, 2, "a@x.com", "Work") == "Work"  # label wins
    always = Settings(show_account="always")
    assert account_display(always, 1, "a@x.com") == "a"
    assert account_display(always, 1, "a@x.com", "Work") == "Work"
    never = Settings(show_account="never")
    assert account_display(never, 5, "a@x.com", "Work") is None


# --- relative_age ----------------------------------------------------------------


def test_relative_age_buckets():
    assert relative_age(datetime(2026, 1, 1, 12, 4, 30, tzinfo=UTC), now=NOW) == "now"
    assert relative_age(datetime(2026, 1, 1, 12, 0, tzinfo=UTC), now=NOW) == "5m"
    assert relative_age(datetime(2026, 1, 1, 9, 0, tzinfo=UTC), now=NOW) == "3h"
    assert relative_age(datetime(2025, 12, 30, 12, 0, tzinfo=UTC), now=NOW) == "2d"


def test_relative_age_future_mail_counts_as_now():
    assert relative_age(datetime(2026, 1, 1, 12, 6, tzinfo=UTC), now=NOW) == "now"


# --- menu_line -------------------------------------------------------------------


def test_menu_line_markers_and_right_column():
    mail = make_mail(unread=True)  # received_at is 5 minutes before NOW
    line = menu_line(mail, Settings(), "a", now=NOW)
    assert line == "● Jane Doe: Hello\t5m · a"
    read = menu_line(make_mail(unread=False), Settings(), None, now=NOW)
    assert read == "○ Jane Doe: Hello\t5m"  # hollow bullet keeps the sender aligned


def test_menu_line_no_subject():
    line = menu_line(make_mail(subject=""), Settings(), None, now=NOW)
    assert line == "● Jane Doe: (no subject)\t5m"


def test_menu_line_truncates_subject_before_sender():
    long_subject = "word " * 30
    line = menu_line(make_mail(sender="Jane", subject=long_subject), Settings(), "a@x.com", now=NOW)
    left, right = line.split("\t")
    assert left.startswith("● Jane: ")  # sender intact
    assert "…" in left
    assert long_subject not in left
    assert right.endswith("a@x.com")  # the account survives in the tab column
    assert len(line) <= formatting.MENU_LINE_LIMIT


def test_menu_line_truncates_long_sender_keeps_short_subject():
    line = menu_line(make_mail(sender="X" * 120, subject="Hi"), Settings(), None, now=NOW)
    assert len(line) <= formatting.MENU_LINE_LIMIT
    assert ": Hi" in line  # short subject intact
    assert "…" in line


def test_menu_line_length_never_exceeds_limit():
    for sender_len in range(0, 100, 7):
        for subject_len in range(0, 100, 7):
            mail = make_mail(sender="S" * sender_len, subject="b" * subject_len)
            line = menu_line(mail, Settings(), "a@x.com", now=NOW)
            assert len(line) <= formatting.MENU_LINE_LIMIT
            assert "\t" in line  # the right column survives every fit


def test_menu_line_truncates_oversized_account_column():
    line = menu_line(make_mail(), Settings(), "x" * 60, now=NOW)
    left, right = line.split("\t")
    assert len(right) <= formatting._AGE_COLUMN_LIMIT
    assert len(line) <= formatting.MENU_LINE_LIMIT
    assert ": Hello" in left  # the subject still fits


# --- tooltip -----------------------------------------------------------------------


def test_tooltip_empty_states():
    assert (
        tooltip(snapshot(accounts=0), Settings())
        == "Gmail Notifier: no account. Right-click to add one."
    )
    assert (
        tooltip(snapshot(accounts=1, needs_sign_in=True), Settings())
        == "Gmail Notifier: sign-in needed. Right-click to fix."
    )
    assert tooltip(snapshot(accounts=1), Settings()) == "Gmail Notifier: no recent mail"


def test_tooltip_two_lines_with_account():
    text = tooltip(snapshot(latest=make_mail(), show="you@gmail.com"), Settings())
    assert text == "Jane Doe · you@gmail.com\nHello"
    assert len(text) <= formatting.TOOLTIP_LIMIT


def test_tooltip_truncates_subject_first():
    long_subject = "chapter " * 40
    text = tooltip(snapshot(latest=make_mail(sender="Jane", subject=long_subject)), Settings())
    first, second = text.split("\n")
    assert first == "Jane"  # sender intact
    assert len(text) <= formatting.TOOLTIP_LIMIT
    assert long_subject not in second
    assert "…" in second


def test_tooltip_truncates_sender_last():
    text = tooltip(snapshot(latest=make_mail(sender="X" * 200, subject="Y" * 200)), Settings())
    assert len(text) <= formatting.TOOLTIP_LIMIT
    first, second = text.split("\n")
    assert "…" in first and "…" in second  # both had to give way


def test_tooltip_length_never_exceeds_limit():
    for sender_len in range(0, 220, 13):
        for subject_len in range(0, 220, 13):
            snap = snapshot(
                latest=make_mail(sender="S" * sender_len, subject="b" * subject_len),
                show="someone@gmail.com",
            )
            assert len(tooltip(snap, Settings())) <= formatting.TOOLTIP_LIMIT


# --- toast_content -------------------------------------------------------------------


def test_toast_content_layout():
    content = toast_content(make_mail(), Settings(), "you@gmail.com")
    assert content.title == "Hello"
    assert content.lines == ("Jane Doe · you@gmail.com", "Some preview text")


def test_toast_title_truncated_to_70():
    content = toast_content(make_mail(subject="z" * 200), Settings(), None)
    assert len(content.title) <= formatting.TOAST_TITLE_LIMIT
    assert content.title.endswith("…")


def test_toast_preview_omitted_when_disabled_or_empty():
    off = Settings(show_preview=False)
    assert toast_content(make_mail(), off, None).lines == ("Jane Doe",)
    empty = toast_content(make_mail(snippet=""), Settings(), None)
    assert empty.lines == ("Jane Doe",)


def test_toast_preview_truncated_to_180():
    content = toast_content(make_mail(snippet="p" * 400), Settings(), None)
    assert len(content.lines[1]) <= formatting.TOAST_PREVIEW_LIMIT


def test_toast_no_subject_fallback():
    assert toast_content(make_mail(subject=""), Settings(), None).title == "(no subject)"


# --- summary_toast -------------------------------------------------------------------


def test_summary_toast_with_more_suffix():
    mails = [make_mail(f"m{i}", sender=f"S{i}") for i in range(1, 6)]
    content = summary_toast(mails, "you@gmail.com")
    assert content.title == "5 new mails"
    assert content.lines == ("S1, S2, S3 and 2 more · you@gmail.com",)


def test_summary_toast_small_burst_and_no_account():
    mails = [make_mail("m1", sender="S1"), make_mail("m2", sender="S2")]
    content = summary_toast(mails, None)
    assert content.title == "2 new mails"
    assert content.lines == ("S1, S2",)
