"""Settings dataclass plus validated, atomic load/save of settings.json.

Rules (docs/PRODUCT.md section 7): unknown keys are ignored, numeric values are
clamped into range, wrong-typed values fall back to defaults, and a corrupt file
is backed up as settings.json.bad and replaced by defaults. Writes are atomic
(temp file in the same folder, then os.replace). A missing file returns defaults
without creating anything.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from gmail_notifier import config

logger = logging.getLogger(__name__)

POLL_INTERVAL_MIN = 20
POLL_INTERVAL_MAX = 600
MAX_TOASTS_MIN = 1
MAX_TOASTS_MAX = 10
SHOW_ACCOUNT_MODES = ("auto", "always", "never")
# A settings file is a few hundred bytes; anything larger is not ours. Read
# caps keep a planted multi-gigabyte file from spiking memory (SECURITY 6).
_MAX_JSON_BYTES = 1024 * 1024


@dataclass(frozen=True)
class Settings:
    """User-visible settings; see docs/PRODUCT.md section 7."""

    poll_interval_seconds: int = 45
    only_primary: bool = True
    show_preview: bool = True
    show_account: str = "auto"
    notification_sound: bool = True
    max_toasts_per_poll: int = 3
    start_with_windows: bool = True
    first_run_done: bool = False


DEFAULTS = Settings()


def load(path: Path | None = None) -> Settings:
    """Load settings from `path` (default: %APPDATA%/GmailNotifier/settings.json)."""
    path = path if path is not None else config.settings_path()
    try:
        if path.stat().st_size > _MAX_JSON_BYTES:
            return _recover_corrupt(path)
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return DEFAULTS
    except OSError:
        logger.warning("settings file unreadable; using defaults")
        return DEFAULTS

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _recover_corrupt(path)
    if not isinstance(data, dict):
        return _recover_corrupt(path)
    return _from_dict(data)


def save(settings: Settings, path: Path | None = None) -> None:
    """Write `settings` atomically: temp file in the same folder, then os.replace."""
    path = path if path is not None else config.settings_path()
    config.ensure_dir(path.parent)
    tmp = path.with_name(path.name + ".tmp")
    payload = json.dumps(asdict(settings), indent=2, ensure_ascii=False) + "\n"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _from_dict(data: dict[str, Any]) -> Settings:
    """Build a Settings from raw JSON values; unknown keys are ignored."""
    return Settings(
        poll_interval_seconds=_clamp_number(
            data.get("poll_interval_seconds"),
            DEFAULTS.poll_interval_seconds,
            POLL_INTERVAL_MIN,
            POLL_INTERVAL_MAX,
        ),
        only_primary=_as_bool(data.get("only_primary"), DEFAULTS.only_primary),
        show_preview=_as_bool(data.get("show_preview"), DEFAULTS.show_preview),
        show_account=_as_mode(data.get("show_account"), DEFAULTS.show_account),
        notification_sound=_as_bool(data.get("notification_sound"), DEFAULTS.notification_sound),
        max_toasts_per_poll=_clamp_number(
            data.get("max_toasts_per_poll"),
            DEFAULTS.max_toasts_per_poll,
            MAX_TOASTS_MIN,
            MAX_TOASTS_MAX,
        ),
        start_with_windows=_as_bool(data.get("start_with_windows"), DEFAULTS.start_with_windows),
        first_run_done=_as_bool(data.get("first_run_done"), DEFAULTS.first_run_done),
    )


def _clamp_number(value: Any, default: int, lo: int, hi: int) -> int:
    """Clamp numeric values into [lo, hi]; anything else (incl. bool) resets to default."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return int(min(max(value, lo), hi))


def _as_bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _as_mode(value: Any, default: str) -> str:
    if isinstance(value, str) and value in SHOW_ACCOUNT_MODES:
        return value
    return default


def _recover_corrupt(path: Path) -> Settings:
    """Back the unreadable file up as <name>.bad, then write defaults over it."""
    logger.warning("settings file corrupt; backing it up and using defaults")
    bad = path.with_name(path.name + ".bad")
    try:
        os.replace(path, bad)
    except OSError:
        logger.warning("could not back up the corrupt settings file")
    try:
        save(DEFAULTS, path)
    except OSError:
        logger.warning("could not write default settings")
    return DEFAULTS
