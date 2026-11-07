"""Tests for AccountStore: duplicates, removal, corrupt recovery, atomic writes, token hygiene.

All tests use explicit paths under tmp_path; the real %APPDATA% is never touched.
"""

from __future__ import annotations

import json

from gsend.accounts import AccountStore, StoredAccount


def test_add_and_list_roundtrip(tmp_path):
    store = AccountStore(tmp_path / "accounts.json")
    store.add("a@example.com", label="Work")
    store.add("b@example.com")
    assert store.list() == [
        StoredAccount(email="a@example.com", label="Work"),
        StoredAccount(email="b@example.com", label=None),
    ]


def test_duplicate_add_is_case_insensitive(tmp_path):
    path = tmp_path / "accounts.json"
    store = AccountStore(path)
    store.add("User@Gmail.com")
    store.add("user@gmail.com")
    assert len(store.list()) == 1
    assert store.list()[0].email == "User@Gmail.com"  # first-seen spelling is kept


def test_has(tmp_path):
    store = AccountStore(tmp_path / "accounts.json")
    store.add("A@Example.com")
    assert store.has("a@example.com")
    assert not store.has("other@example.com")


def test_remove_existing_and_missing(tmp_path):
    store = AccountStore(tmp_path / "accounts.json")
    store.add("a@example.com")
    store.remove("A@Example.com")
    assert store.list() == []
    store.remove("a@example.com")  # no-op, no raise


def test_corrupt_file_backed_up_and_starts_empty(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text("{oops", encoding="utf-8")
    store = AccountStore(path)
    assert store.list() == []
    bad = path.with_name("accounts.json.bad")
    assert bad.exists()
    assert "oops" in bad.read_text(encoding="utf-8")
    store.add("a@example.com")  # next mutation writes a clean file
    assert len(json.loads(path.read_text(encoding="utf-8"))) == 1


def test_malformed_entries_skipped(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text(
        json.dumps([{"email": "a@example.com", "label": None}, {"nope": 1}, "junk", {"email": 42}]),
        encoding="utf-8",
    )
    assert AccountStore(path).list() == [StoredAccount(email="a@example.com", label=None)]


def test_file_holds_only_email_and_label(tmp_path):
    path = tmp_path / "accounts.json"
    store = AccountStore(path)
    store.add("a@example.com", label="Work")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == [{"email": "a@example.com", "label": "Work"}]


def test_file_never_contains_token_strings(tmp_path, fake_keyring):
    # The keyring holds a token for the account; the store must never copy it into the file.
    fake_keyring.set_password("GSend", "a@example.com", "refresh-token-xyz")
    path = tmp_path / "accounts.json"
    AccountStore(path).add("a@example.com")
    text = path.read_text(encoding="utf-8")
    assert "refresh-token-xyz" not in text
    assert "token" not in text.lower()


def test_save_is_atomic_and_creates_missing_dirs(tmp_path):
    path = tmp_path / "nested" / "accounts.json"
    store = AccountStore(path)
    store.add("a@example.com")
    assert path.exists()
    assert list(tmp_path.rglob("*.tmp")) == []  # no temp file left behind


def test_oversized_accounts_file_is_recovered(tmp_path):
    """A planted multi-MB file must not be read into memory (SECURITY 6)."""
    path = tmp_path / "accounts.json"
    path.write_text("y" * (1024 * 1024 + 1), encoding="utf-8")
    store = AccountStore(path)
    assert store.list() == []
    assert (tmp_path / "accounts.json.bad").exists()
