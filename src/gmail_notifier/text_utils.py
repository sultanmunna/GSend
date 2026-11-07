"""Pure text helpers: RFC 2047 header decoding, sender parsing, snippet cleaning, truncation.

Implements the text rules of docs/PRODUCT.md section 6.5. All functions are
pure (no I/O) and must never raise on malformed input. None of them log.
"""

from __future__ import annotations

import html
import re
from email.header import decode_header
from email.utils import parseaddr

# Invisible padding characters removed from snippets (docs/PRODUCT.md section 6.5).
_INVISIBLE_CHARS = re.compile("[\u200b\u200c\u200d\u034f\u00ad\ufeff]")
_WHITESPACE = re.compile(r"\s+")


def _collapse_whitespace(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def decode_header_value(raw: str | None) -> str:
    """Decode RFC 2047 encoded-words (e.g. =?UTF-8?B?...?=) and collapse whitespace.

    Unknown or broken encodings degrade to a lossy UTF-8 decode instead of raising.
    """
    if not raw:
        return ""
    try:
        chunks = decode_header(raw)
    except Exception:
        return _collapse_whitespace(raw)
    parts: list[str] = []
    for data, charset in chunks:
        if isinstance(data, bytes):
            try:
                parts.append(data.decode(charset or "utf-8"))
            except (LookupError, UnicodeDecodeError):
                parts.append(data.decode("utf-8", errors="replace"))
        else:
            parts.append(data)
    return _collapse_whitespace("".join(parts))


def parse_sender(raw: str | None) -> tuple[str, str]:
    """Parse a From header into (display_name_or_address, email_address).

    The header structure is parsed before decoding, so that a decoded display
    name containing commas cannot confuse the address parser. Surrounding
    quotes around the display name are stripped; with no display name, the
    address is returned as the display name too.
    """
    if not raw or not raw.strip():
        return "", ""
    name, address = parseaddr(raw)
    display = decode_header_value(name) if name else ""
    display = _strip_surrounding_quotes(display).strip()
    address = address.strip()
    return (display or address), address


def _strip_surrounding_quotes(text: str) -> str:
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    return text


def clean_snippet(raw: str | None) -> str:
    """Clean a Gmail snippet: HTML-unescape, drop invisible padding, collapse whitespace."""
    if not raw:
        return ""
    text = html.unescape(raw)
    text = _INVISIBLE_CHARS.sub("", text)
    return _collapse_whitespace(text)


def truncate(text: str, limit: int) -> str:
    """Truncate to at most `limit` characters; the ellipsis counts as one.

    Prefers a word boundary when one lies within the kept half; a single word
    longer than the limit is cut hard. limit <= 0 yields "".
    """
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    cut = limit - 1
    if cut == 0:
        return "…"
    boundary = text.rfind(" ", 0, cut + 1)
    if boundary >= max(1, cut // 2):
        cut = boundary
    head = text[:cut].rstrip()
    return f"{head}…" if head else "…"


def escape_winotify(text: str) -> str:
    """Neutralize `text` for embedding in a winotify 1.1 toast (DECISIONS D-18).

    winotify builds the toast by str.format into a PowerShell script whose XML
    template is an expandable here-string (@"..."@) with CDATA text fields.
    Mail content is attacker-controlled, so it must not reach that script raw:

    - ``$(...)``/``$env:...`` in an expandable here-string would be executed by
      PowerShell -> escape ``$`` (and the escape char `` ` `` itself);
    - a ``"`` would break out of the script's ``$Toast.Tag = "{tag}"`` string
      and could start a line with the here-string terminator ``"@`` -> escape
      it, which also makes a ``"@`` from content impossible;
    - ``]]>`` would close a CDATA section early and allow toast XML (action)
      injection -> splice the CDATA section, the standard lossless idiom.

    The backtick escapes are exactly what PowerShell renders as the original
    characters, so the toast displays the true content.
    """
    if not text:
        return text
    text = text.replace("`", "``").replace("$", "`$").replace('"', '`"')
    return text.replace("]]>", "]]]]><![CDATA[>")
