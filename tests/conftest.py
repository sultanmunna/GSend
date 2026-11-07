"""Shared test fakes: an in-memory keyring backend for auth tests (no real Credential Manager)."""

from __future__ import annotations

import pytest

SERVICE = "GmailNotifier"


class FakeKeyringError(Exception):
    """Mirrors keyring.errors.PasswordDeleteError for missing entries."""


class FakeKeyring:
    """Minimal in-memory stand-in for the keyring module API."""

    def __init__(self) -> None:
        self.entries: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self.entries[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self.entries.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.entries:
            raise FakeKeyringError("entry does not exist")
        del self.entries[(service, username)]


@pytest.fixture()
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> FakeKeyring:
    fake = FakeKeyring()
    monkeypatch.setattr("gmail_notifier.auth.keyring", fake)
    return fake
