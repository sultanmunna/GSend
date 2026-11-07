"""Tripwire: the audited winotify version and script template must not drift.

The security pass (docs/SECURITY_REPORT.md SEC-01, DECISIONS D-18) audited
winotify 1.1.0 line-by-line: its toast XML lives in the module-level TEMPLATE,
an *expandable* PowerShell here-string with CDATA fields, and
`text_utils.escape_winotify` is calibrated to exactly that rendering. If the
installed version or the template bytes change, the escaping guarantees and
the injection tests no longer prove what they tested.

This test fails on either drift and says what to do about it. The version pin
is read from pyproject.toml so the tripwire and the dependency stay in sync.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import tomllib
from pathlib import Path

import pytest

winotify = pytest.importorskip("winotify", reason="Windows-only toast library")

# sha256 of winotify 1.1.0's TEMPLATE (winotify/__init__.py), audited 2026-11-07.
_AUDITED_TEMPLATE_SHA256 = "8a8005ab4f2e3c8569565615051ad1e747b5ab3ffcfb92113932bc0f061176ba"
_REAUDIT_MESSAGE = (
    "winotify changed; re-audit text_utils.escape_winotify against the new "
    "template and re-run tests/test_toast_injection.py before updating this tripwire."
)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _pinned_version() -> str:
    """The exact winotify pin from pyproject.toml (the single source of truth)."""
    with open(_REPO_ROOT / "pyproject.toml", "rb") as handle:
        data = tomllib.load(handle)
    for dependency in data["project"]["dependencies"]:
        if dependency.startswith("winotify"):
            return dependency.split("==")[-1].strip()
    raise AssertionError("winotify must be pinned exactly (==) in pyproject.toml")


def test_winotify_version_matches_the_audited_pin():
    pinned = _pinned_version()
    installed = importlib.metadata.version("winotify")
    assert installed == pinned, (
        f"installed winotify {installed} != pinned {pinned}; " + _REAUDIT_MESSAGE
    )


def test_winotify_template_is_unchanged():
    digest = hashlib.sha256(winotify.TEMPLATE.encode("utf-8")).hexdigest()
    assert digest == _AUDITED_TEMPLATE_SHA256, _REAUDIT_MESSAGE


def test_pyproject_pins_winotify_exactly():
    """A range pin (>=) would let a bump bypass the version tripwire."""
    with open(_REPO_ROOT / "pyproject.toml", "rb") as handle:
        data = tomllib.load(handle)
    winotify_deps = [d for d in data["project"]["dependencies"] if d.startswith("winotify")]
    assert winotify_deps == ["winotify==1.1.0"], _REAUDIT_MESSAGE
