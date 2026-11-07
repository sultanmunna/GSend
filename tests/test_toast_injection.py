"""winotify boundary: mail text must not be able to inject XML or PowerShell.

winotify 1.1 builds each toast by str.format into a PowerShell script in which
the toast XML is an *expandable* here-string (@"..."@) whose text fields are
CDATA sections (verified against the installed 1.1.0 source, winotify/
__init__.py TEMPLATE). Unescaped, mail-controlled text could therefore:

- execute commands: ``$(calc)`` and ``$env:...`` are expanded when PowerShell
  parses the here-string;
- break out of ``$Toast.Tag = "{tag}"`` (the title) with a single ``"``;
- terminate the here-string early with ``"@`` at the start of a line (the
  message lines are joined with newlines, so a line can start with anything);
- close a CDATA section with ``]]>`` and inject toast XML such as
  ``<action activationType="protocol" arguments="https://evil.test"/>``.

These tests drive the real WinotifyBackend with a fake process runner
(monkeypatched ``winotify._run_ps``) over the Phase-5 hostile corpus and assert
the generated scripts are inert: the here-string terminates exactly once, no
executable ``$(...)`` survives unescaped, and every hostile string appears only
in its backtick-escaped/CDATA-spliced form. docs/SECURITY.md section 6,
DECISIONS D-18.
"""

from __future__ import annotations

import pytest

winotify = pytest.importorskip("winotify", reason="Windows-only toast library")

from gmail_notifier.gmail_client import parse_message  # noqa: E402
from gmail_notifier.notifier import Notifier, WinotifyBackend  # noqa: E402
from gmail_notifier.settings import Settings  # noqa: E402
from gmail_notifier.state import AppState  # noqa: E402
from gmail_notifier.text_utils import escape_winotify  # noqa: E402

HOSTILE_CORPUS = [
    " ; calc.exe ; ",
    "$(calc)",
    "${calc}",
    "$env:PATH",
    "`calc`",
    "'; Start-Process calc; '",
    '"; Start-Process calc; "',
    '"@ evil line',  # here-string terminator on a joined message line
    "<toast><text>",
    "&amp;&lt;",
    "]]><action activationType=\"protocol\" content=\"Run\" arguments=\"https://evil.test/phish\"/>",
    "]]>",
    "%s",
    "{0}",
    "{{x}}",
    "zero\u200bwidth",
]


def capture_scripts(monkeypatch) -> list[str]:
    """Fake process runner: winotify's generated scripts instead of PowerShell."""
    SCRIPTS.clear()

    def fake_run_ps(*, file: str = "", command: str = "") -> None:
        assert not file
        SCRIPTS.append(command)

    monkeypatch.setattr("winotify._run_ps", fake_run_ps)
    return SCRIPTS


SCRIPTS: list[str] = []


def assert_script_is_inert(script: str) -> None:
    """The invariants that make a generated script unable to execute content."""
    # 1. The here-string must terminate exactly once, on the template's own line.
    assert len([line for line in script.splitlines() if line.strip() == '"@']) == 1, (
        f"here-string terminator tampered: {script!r}"
    )
    # No content may reach a line start as the terminator sequence either.
    assert len([line for line in script.splitlines() if line.startswith('"@')]) == 1, (
        f'"@ reached a line start: {script!r}'
    )
    # 2. Command substitution from content must be backtick-escaped.
    assert not _unescaped_dollar_paren(script), f"unescaped $( in script: {script!r}"


def _unescaped_dollar_paren(script: str) -> bool:
    """True if a `$(` occurs without a preceding backtick (executable)."""
    index = script.find("$(")
    while index != -1:
        if index == 0 or script[index - 1] != "`":
            return True
        index = script.find("$(", index + 1)
    return False


def test_backend_escapes_hostile_title_and_message(monkeypatch):
    capture_scripts(monkeypatch)
    backend = WinotifyBackend()
    for hostile in HOSTILE_CORPUS:
        SCRIPTS.clear()
        backend.show(f"S: {hostile}", f"M1\n{hostile}", None, False)
        assert len(SCRIPTS) == 1
        script = SCRIPTS[0]
        assert_script_is_inert(script)
        # The content made it in, but only in its inert (escaped/spliced) form.
        assert f"S: {escape_winotify(hostile)}" in script, f"unescaped title: {hostile!r}"
        assert f"M1\n{escape_winotify(hostile)}" in script, f"unescaped msg: {hostile!r}"


def test_backend_escapes_hostile_launch(monkeypatch):
    capture_scripts(monkeypatch)
    backend = WinotifyBackend()
    launch = 'https://mail.google.com/mail/?authuser=a@b.test#all/feed"'
    backend.show("t", "m", launch, False)
    assert len(SCRIPTS) == 1
    assert launch not in SCRIPTS[0]  # a raw quote must not reach the launch attribute
    assert escape_winotify(launch) in SCRIPTS[0]


def test_end_to_end_hostile_mail_cannot_inject(monkeypatch):
    """From parse_message to the generated script, the whole path is inert."""
    capture_scripts(monkeypatch)
    api_dict = {
        "id": "16a7c1f2e3d4b5a6",
        "threadId": "16a7c1f2e3d4b5a6",
        "internalDate": "1730000000000",
        "labelIds": ["INBOX", "UNREAD"],
        "snippet": "hi $(calc) ]]><action arguments=\"https://evil.test\"/> %s",
        "payload": {
            "headers": [
                {"name": "From", "value": '"$(calc)" <attacker@evil.test>'},
                {"name": "Subject", "value": "Re: \"]]>\"><script>\"@ `calc`"},
            ]
        },
    }
    mail = parse_message("a@example.com", api_dict)
    notifier = Notifier(Settings(show_preview=True), AppState(), WinotifyBackend())
    notifier.notify_new_mails("a@example.com", [mail])
    assert len(SCRIPTS) == 1
    assert_script_is_inert(SCRIPTS[0])
    # CDATA splice from the subject's ]]> is present; no raw toast-action XML:
    assert "]]]]><![CDATA[>" in SCRIPTS[0]
    assert '<action arguments="https://evil.test"/>' not in SCRIPTS[0]


def test_escape_winotify_is_total():
    """The pure function covers every vector and keeps harmless text intact."""
    assert escape_winotify("") == ""
    assert escape_winotify("plain") == "plain"
    assert escape_winotify("a`b") == "a``b"
    assert escape_winotify("a$b") == "a`$b"
    assert escape_winotify('a"b') == 'a`"b'
    assert escape_winotify("a]]>b") == "a]]]]><![CDATA[>b"
    assert escape_winotify("$(x)") == "`$(x)"
    # '@', '<', '&' and braces are harmless in both contexts and pass through:
    assert escape_winotify("a@b<c&d") == "a@b<c&d"
    assert escape_winotify("{0} {{x}} %s") == "{0} {{x}} %s"
