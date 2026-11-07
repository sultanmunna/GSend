"""Tests for settings: defaults, clamping, type validation, corruption recovery, atomic writes.

All tests use explicit paths under tmp_path; the real %APPDATA% is never touched.
"""

from __future__ import annotations

import json

from gmail_notifier import settings as settings_mod
from gmail_notifier.settings import DEFAULTS, Settings, load, save


def test_missing_file_returns_defaults(tmp_path):
    assert load(tmp_path / "settings.json") == DEFAULTS


def test_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    wanted = Settings(poll_interval_seconds=90, show_account="always", only_primary=False)
    save(wanted, path)
    assert load(path) == wanted


def test_clamping(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"poll_interval_seconds": 5, "max_toasts_per_poll": 99}),
        encoding="utf-8",
    )
    settings = load(path)
    assert settings.poll_interval_seconds == 20
    assert settings.max_toasts_per_poll == 10
    path.write_text(json.dumps({"poll_interval_seconds": 1000}), encoding="utf-8")
    assert load(path).poll_interval_seconds == 600


def test_wrong_types_reset_to_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "poll_interval_seconds": "fast",
                "only_primary": "yes",
                "show_account": "sometimes",
            }
        ),
        encoding="utf-8",
    )
    settings = load(path)
    assert settings.poll_interval_seconds == DEFAULTS.poll_interval_seconds
    assert settings.only_primary is True
    assert settings.show_account == "auto"


def test_bool_is_not_accepted_as_int(tmp_path):
    # bool is a subclass of int; it must not pass as a number.
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"poll_interval_seconds": True}), encoding="utf-8")
    assert load(path).poll_interval_seconds == DEFAULTS.poll_interval_seconds


def test_unknown_keys_ignored(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"theme": "dark", "poll_interval_seconds": 30}), encoding="utf-8")
    assert load(path).poll_interval_seconds == 30


def test_corrupt_file_backed_up_and_replaced(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    assert load(path) == DEFAULTS
    bad = path.with_name("settings.json.bad")
    assert bad.exists()
    assert "not json" in bad.read_text(encoding="utf-8")
    assert load(path) == DEFAULTS  # the file was replaced with defaults


def test_non_dict_json_recovered(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert load(path) == DEFAULTS


def test_save_is_atomic_and_creates_missing_dirs(tmp_path):
    path = tmp_path / "nested" / "dir" / "settings.json"
    save(DEFAULTS, path)
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["poll_interval_seconds"] == 45
    assert list(tmp_path.rglob("*.tmp")) == []  # no temp file left behind


def test_oversized_settings_file_is_recovered(tmp_path):
    """A planted multi-MB file must not be read into memory (SECURITY 6)."""
    path = tmp_path / "settings.json"
    path.write_text("x" * (1024 * 1024 + 1), encoding="utf-8")
    settings = settings_mod.load(path)
    assert settings == settings_mod.DEFAULTS
    assert path.read_text(encoding="utf-8") != "x" * (1024 * 1024 + 1)  # defaults written
    assert (tmp_path / "settings.json.bad").exists()
