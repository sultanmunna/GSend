"""Constants and filesystem paths for GSend.

Central place for the app name, the keyring service name, the single OAuth
scope, the Google URLs the app is allowed to contact, and the locations of the
settings, accounts and log files under %APPDATA% and %LOCALAPPDATA%. Folders
are created lazily via `ensure_dir`, never at import time.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "GSend"
DISPLAY_NAME = "GSend"

# Service name under which refresh tokens are stored in Windows Credential Manager.
KEYRING_SERVICE = "GSend"

# Pre-rename names (see docs/DECISIONS.md D-23). Used ONLY by the one-time
# migrations that move tokens, files and the autostart entry over to GSend;
# never used for new writes.
LEGACY_APP_NAME = "GmailNotifier"
LEGACY_KEYRING_SERVICE = "GmailNotifier"

# Hard rule 2: exactly one scope, read-only. Never add anything here.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Allowed network hosts (docs/SECURITY.md section 3). Nothing else may be contacted.
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GMAIL_BASE_URL = "https://mail.google.com/mail/"

# Socket timeout for every Gmail API request; a hung connection must never
# stall the poller thread past this (docs/ARCHITECTURE.md section 9).
HTTP_TIMEOUT_SECONDS = 30

SETTINGS_FILE_NAME = "settings.json"
ACCOUNTS_FILE_NAME = "accounts.json"
LOG_FILE_NAME = "app.log"


def _app_dir(env_var: str, fallback: Path) -> Path:
    """Return the app's folder under the given base directory (read at call time)."""
    base = Path(os.environ.get(env_var) or fallback)
    return base / APP_NAME


def appdata_dir() -> Path:
    """%APPDATA%\\GmailNotifier — settings.json and accounts.json live here."""
    return _app_dir("APPDATA", Path.home() / "AppData" / "Roaming")


def localappdata_dir() -> Path:
    """%LOCALAPPDATA%\\GmailNotifier — logs live here."""
    return _app_dir("LOCALAPPDATA", Path.home() / "AppData" / "Local")


def settings_path() -> Path:
    return appdata_dir() / SETTINGS_FILE_NAME


def accounts_path() -> Path:
    return appdata_dir() / ACCOUNTS_FILE_NAME


def logs_dir() -> Path:
    return localappdata_dir() / "logs"


def log_file_path() -> Path:
    return logs_dir() / LOG_FILE_NAME


def ensure_dir(path: Path) -> Path:
    """Create `path` (and parents) if missing; called lazily by writers only."""
    path.mkdir(parents=True, exist_ok=True)
    return path
