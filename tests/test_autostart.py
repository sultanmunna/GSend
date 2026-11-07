"""Tests for autostart.py with a fake registry wrapper (no real registry access)."""

from __future__ import annotations

import sys

from gmail_notifier import autostart


class FakeRegistry:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def read(self, name: str) -> str | None:
        return self.values.get(name)

    def write(self, name: str, data: str) -> None:
        self.values[name] = data

    def delete(self, name: str) -> None:
        if name not in self.values:
            raise FileNotFoundError(name)  # mimics winreg on a missing value
        del self.values[name]


def install_fake(monkeypatch) -> FakeRegistry:
    fake = FakeRegistry()
    monkeypatch.setattr(autostart, "_registry_read", fake.read)
    monkeypatch.setattr(autostart, "_registry_write", fake.write)
    monkeypatch.setattr(autostart, "_registry_delete", fake.delete)
    return fake


def test_enable_disable_roundtrip(monkeypatch):
    fake = install_fake(monkeypatch)
    assert autostart.is_enabled() is False
    autostart.enable()
    assert autostart.is_enabled() is True
    assert "gmail_notifier" in fake.values["GmailNotifier"]
    autostart.disable()
    assert autostart.is_enabled() is False


def test_disable_when_absent_is_noop(monkeypatch):
    install_fake(monkeypatch)
    autostart.disable()  # must not raise
    assert autostart.is_enabled() is False


def test_command_from_source_uses_pythonw(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    command = autostart.command()
    assert "pythonw.exe" in command
    assert "-m gmail_notifier" in command


def test_command_when_frozen_is_the_executable(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    command = autostart.command()
    assert command == f'"{sys.executable}"'
    assert "-m gmail_notifier" not in command
