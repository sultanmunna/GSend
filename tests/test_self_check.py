"""Tests for the --self-check CLI: orchestration, exit codes, no value leaks.

The frozen (windowed) console attach cannot run in tests; everything here
exercises the non-frozen path on this machine's real environment, with only
the environment-dependent checks (client config, keyring) faked for
determinism.
"""

from __future__ import annotations

import pytest

from gsend import __main__ as main_module
from gsend.errors import ConfigError

VALID_CONFIG = {
    "installed": {
        "client_id": "test-id.apps.googleusercontent.com",
        "client_secret": "test-secret-must-not-print",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}


@pytest.fixture()
def deterministic_env(fake_keyring, monkeypatch):
    """Client config and keyring faked; everything else runs for real."""
    monkeypatch.setattr("gsend.auth.load_client_config", lambda: VALID_CONFIG)
    return fake_keyring


def test_self_check_all_pass_on_a_healthy_machine(deterministic_env, capsys):
    exit_code = main_module.main(["--self-check"])
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "PASS self-check overall" in output
    for expected in (
        "PASS app version (",
        "PASS settings load",
        "PASS accounts load",
        "PASS client config valid (Google endpoints)",
        "PASS keyring is Windows Credential Manager",
        "PASS gmail service builds from bundled discovery",
        "PASS winotify imports",
        "PASS pystray imports",
        "PASS tray icon images generate",
    ):
        assert expected in output, f"missing check line: {expected}"


def test_self_check_never_prints_config_values(deterministic_env, capsys):
    main_module.main(["--self-check"])
    output = capsys.readouterr().out
    assert "test-secret-must-not-print" not in output
    assert "test-id.apps.googleusercontent.com" not in output


def test_self_check_fails_when_client_config_is_missing(monkeypatch, capsys):
    def raise_missing():
        raise ConfigError("no usable client_config.json found")

    monkeypatch.setattr("gsend.auth.load_client_config", raise_missing)
    exit_code = main_module.main(["--self-check"])
    output = capsys.readouterr().out
    assert exit_code == 1
    assert "FAIL client config valid (Google endpoints)" in output
    assert "FAIL self-check overall" in output


def test_self_check_fails_when_keyring_is_insecure(fake_keyring, monkeypatch, capsys):
    monkeypatch.setattr("gsend.auth.load_client_config", lambda: VALID_CONFIG)

    class PlainFileBackend:
        """Not Windows Credential Manager."""

    monkeypatch.setattr(fake_keyring, "get_keyring", lambda: PlainFileBackend())
    exit_code = main_module.main(["--self-check"])
    output = capsys.readouterr().out
    assert exit_code == 1
    assert "FAIL keyring is Windows Credential Manager" in output


def test_self_check_log_written_only_when_frozen(deterministic_env, capsys, monkeypatch, tmp_path):
    main_module.main(["--self-check"])
    # Non-frozen runs print and do not write the record file.
    # (The frozen path itself is verified in Phase B on the built exe.)
    monkeypatch.setattr(main_module.config, "logs_dir", lambda: tmp_path / "logs")
    assert not (tmp_path / "logs").exists() or not list((tmp_path / "logs").glob("self_check.log"))


def test_self_check_log_contains_names_only(monkeypatch, tmp_path):
    """The frozen-run record file carries check names, never values (B2 seam)."""
    monkeypatch.setattr(main_module.config, "logs_dir", lambda: tmp_path / "logs")
    results = [("app version (0.1.0)", True), ("client config valid (Google endpoints)", False)]
    overall = all(passed for _n, passed in results)
    main_module._write_self_check_log(results, overall)
    text = (tmp_path / "logs" / "self_check.log").read_text(encoding="utf-8")
    assert "PASS app version (0.1.0)" in text
    assert "FAIL client config valid (Google endpoints)" in text
    assert "FAIL self-check overall" in text
