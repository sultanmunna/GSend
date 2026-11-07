"""Tests for the pure text rules in docs/PRODUCT.md section 6.5."""

from __future__ import annotations

import base64

from gmail_notifier import text_utils


def encoded_word(text: str) -> str:
    """Build a =?UTF-8?B?...?= encoded-word for `text` (mirrors what senders emit)."""
    payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return f"=?UTF-8?B?{payload}?="


# --- decode_header_value ------------------------------------------------------


def test_decode_plain_ascii():
    assert text_utils.decode_header_value("Hello world") == "Hello world"


def test_decode_base64_bangla():
    assert text_utils.decode_header_value(encoded_word("রফিক ইসলাম")) == "রফিক ইসলাম"


def test_decode_quoted_printable():
    assert text_utils.decode_header_value("=?UTF-8?Q?caf=C3=A9?=") == "café"


def test_decode_mixed_encoded_and_plain():
    raw = f"{encoded_word('Meeting')} at 3pm"
    assert text_utils.decode_header_value(raw) == "Meeting at 3pm"


def test_decode_collapses_whitespace():
    assert text_utils.decode_header_value("  a\t\tb\nc  ") == "a b c"
    assert text_utils.decode_header_value("a   b") == "a b"


def test_decode_unknown_charset_does_not_raise():
    # Unknown charset must degrade (lossy UTF-8) instead of raising.
    assert text_utils.decode_header_value("=?x-no-such-charset?B?SGVsbG8=?=") == "Hello"


def test_decode_broken_encoding_does_not_raise():
    assert isinstance(text_utils.decode_header_value("=?UTF-8?B?not!!valid!?="), str)


def test_decode_empty_and_none():
    assert text_utils.decode_header_value("") == ""
    assert text_utils.decode_header_value(None) == ""


# --- parse_sender -------------------------------------------------------------


def test_parse_sender_display_name_and_address():
    assert text_utils.parse_sender('"John Smith" <john@example.com>') == (
        "John Smith",
        "john@example.com",
    )


def test_parse_sender_no_name_falls_back_to_address():
    assert text_utils.parse_sender("<noone@nowhere.org>") == (
        "noone@nowhere.org",
        "noone@nowhere.org",
    )
    assert text_utils.parse_sender("bare@addr.net") == ("bare@addr.net", "bare@addr.net")


def test_parse_sender_quoted_comma():
    assert text_utils.parse_sender('"Doe, Jane" <jane@example.com>') == (
        "Doe, Jane",
        "jane@example.com",
    )


def test_parse_sender_encoded_bangla_name():
    raw = f"{encoded_word('রফিক ইসলাম')} <rafik@example.com>"
    assert text_utils.parse_sender(raw) == ("রফিক ইসলাম", "rafik@example.com")


def test_parse_sender_strips_surrounding_quotes():
    quoted_name = '"Quoted"'
    raw = f"{encoded_word(quoted_name)} <a@example.com>"
    assert text_utils.parse_sender(raw) == ("Quoted", "a@example.com")


def test_parse_sender_empty():
    assert text_utils.parse_sender("") == ("", "")
    assert text_utils.parse_sender(None) == ("", "")


# --- clean_snippet ------------------------------------------------------------


def test_clean_snippet_unescapes_entities():
    assert text_utils.clean_snippet("&#39;it&#39;s &amp; co") == "'it's & co"


def test_clean_snippet_removes_invisible_chars():
    raw = "a\u200bb\u200cc\u200dd\u034fe\u00adf\ufeffg"
    assert text_utils.clean_snippet(raw) == "abcdefg"


def test_clean_snippet_unescapes_then_removes_invisible():
    # &#8203; is the zero-width space entity; unescaping must come first.
    assert text_utils.clean_snippet("a&#8203;b") == "ab"


def test_clean_snippet_collapses_whitespace():
    assert text_utils.clean_snippet("hello\n \t world  ") == "hello world"


def test_clean_snippet_empty():
    assert text_utils.clean_snippet("") == ""
    assert text_utils.clean_snippet(None) == ""


# --- truncate -----------------------------------------------------------------


def test_truncate_within_limit_unchanged():
    assert text_utils.truncate("hello world", 11) == "hello world"
    assert text_utils.truncate("hi", 80) == "hi"


def test_truncate_at_word_boundary():
    assert text_utils.truncate("hello world", 8) == "hello…"
    assert text_utils.truncate("Bangla mail subject here", 12) == "Bangla mail…"


def test_truncate_hard_cut_without_boundary():
    # Single word longer than the limit must still be cut.
    assert text_utils.truncate("abcdefghij", 5) == "abcd…"


def test_truncate_tiny_limits():
    assert text_utils.truncate("abc", 0) == ""
    assert text_utils.truncate("a", 1) == "a"
    assert text_utils.truncate("abcd", 1) == "…"
    assert text_utils.truncate("abcd", 2) == "a…"


def test_truncate_never_exceeds_limit():
    text = "সীমা পরীক্ষা word boundaries matter here 12345 ??????????"
    for limit in range(0, 60):
        assert len(text_utils.truncate(text, limit)) <= limit


# --- Bidi control stripping (SECURITY section 6): no direction spoofing -------


def test_decode_header_value_strips_bidi_overrides_and_isolates():
    raw = "PayPa\u202el Support\u2066 hidden \u2069 \u200e\u200f"
    assert "\u202e" not in text_utils.decode_header_value(raw)
    assert "\u2066" not in text_utils.decode_header_value(raw)
    assert "\u2069" not in text_utils.decode_header_value(raw)
    assert "\u200e" not in text_utils.decode_header_value(raw)
    assert text_utils.decode_header_value(raw) == "PayPal Support hidden"


def test_clean_snippet_strips_bidi_controls():
    text = "click \u202dhere\u202c now"
    assert text_utils.clean_snippet(text) == "click here now"


def test_parse_sender_strips_bidi_in_display_name():
    name, address = text_utils.parse_sender("\u202eevil\u202c <x@evil.test>")
    assert name == "evil"
    assert address == "x@evil.test"
