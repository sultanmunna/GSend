"""AccountStore: the list of configured accounts in accounts.json.

The file holds emails and optional labels ONLY (docs/ARCHITECTURE.md section 5)
— never tokens, never mail data. Reads happen per operation, so hand-edited
labels apply without a restart; writes are atomic (temp file + os.replace); a
corrupt file is backed up as accounts.json.bad and treated as empty.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from gmail_notifier import config

logger = logging.getLogger(__name__)

# accounts.json holds one small entry per account; anything larger is not ours.
# Read caps keep a planted multi-gigabyte file from spiking memory (SECURITY 6).
_MAX_JSON_BYTES = 1024 * 1024


@dataclass(frozen=True)
class StoredAccount:
    """One persisted account: email plus optional hand-edited label."""

    email: str
    label: str | None = None


class AccountStore:
    """Read/modify/write access to accounts.json; duplicate-safe, case-insensitive."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else config.accounts_path()

    def list(self) -> list[StoredAccount]:
        return self._load()

    def has(self, email: str) -> bool:
        wanted = email.strip().lower()
        return any(account.email.lower() == wanted for account in self._load())

    def add(self, email: str, label: str | None = None) -> None:
        """Add an account; adding an existing address (case-insensitive) is a no-op."""
        accounts = self._load()
        wanted = email.strip().lower()
        if any(account.email.lower() == wanted for account in accounts):
            return
        accounts.append(StoredAccount(email=email.strip(), label=label))
        self._save(accounts)

    def remove(self, email: str) -> None:
        """Remove an account (case-insensitive); removing an unknown address is a no-op."""
        accounts = self._load()
        wanted = email.strip().lower()
        remaining = [a for a in accounts if a.email.lower() != wanted]
        if len(remaining) != len(accounts):
            self._save(remaining)

    # -- storage --

    def _load(self) -> list[StoredAccount]:
        try:
            if self._path.stat().st_size > _MAX_JSON_BYTES:
                return self._recover_corrupt()
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError:
            logger.warning("accounts file unreadable; starting empty")
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return self._recover_corrupt()
        if not isinstance(data, list):
            return self._recover_corrupt()
        accounts: list[StoredAccount] = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            email = entry.get("email")
            label = entry.get("label")
            if isinstance(email, str) and email and (label is None or isinstance(label, str)):
                accounts.append(StoredAccount(email=email, label=label))
            else:
                logger.warning("skipping a malformed account entry")
        return accounts

    def _save(self, accounts: list[StoredAccount]) -> None:
        config.ensure_dir(self._path.parent)
        tmp = self._path.with_name(self._path.name + ".tmp")
        payload = (
            json.dumps(
                [{"email": a.email, "label": a.label} for a in accounts],
                indent=2,
                ensure_ascii=False,
            )
            + "\n"
        )
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self._path)

    def _recover_corrupt(self) -> list[StoredAccount]:
        logger.warning("accounts file corrupt; backed it up and starting empty")
        bad = self._path.with_name(self._path.name + ".bad")
        try:
            os.replace(self._path, bad)
        except OSError:
            logger.warning("could not back up the corrupt accounts file")
        return []
