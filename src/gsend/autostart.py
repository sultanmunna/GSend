"""Start-with-Windows via the HKCU Run key (docs/PRODUCT.md section 7).

Registered command: the frozen exe when packaged (PyInstaller), otherwise
pythonw.exe -m gsend. The three `_registry_*` wrappers are thin winreg
calls and the test seam; the public functions own the error policy — failures
are logged by type only and never raise (Windows-only module, per AGENTS.md).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from gsend import config

logger = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = config.APP_NAME
_LEGACY_VALUE_NAME = config.LEGACY_APP_NAME


def migrate_legacy_value() -> None:
    """Move a pre-rename autostart entry to the current value name (D-23).

    A leftover "GmailNotifier" Run value would try to start the old module
    name and silently fail. If it exists, drop it and register the current
    command; if not, do nothing. Never raises.
    """
    try:
        if _registry_read(_LEGACY_VALUE_NAME) is None:
            return
        _registry_delete(_LEGACY_VALUE_NAME)
        _registry_write(_VALUE_NAME, command())
        logger.info("autostart entry migrated to the current value name")
    except OSError as exc:
        logger.warning("autostart migration failed (%s)", type(exc).__name__)


def command() -> str:
    """The command that starts the app with Windows."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw}" -m gsend'


def enable() -> None:
    try:
        _registry_write(_VALUE_NAME, command())
        logger.info("autostart enabled")
    except OSError as exc:
        logger.warning("registry write failed (%s)", type(exc).__name__)


def disable() -> None:
    try:
        _registry_delete(_VALUE_NAME)
        logger.info("autostart disabled")
    except FileNotFoundError:
        return  # already disabled
    except OSError as exc:
        logger.warning("registry delete failed (%s)", type(exc).__name__)


def is_enabled() -> bool:
    try:
        return _registry_read(_VALUE_NAME) is not None
    except OSError as exc:
        logger.warning("registry read failed (%s)", type(exc).__name__)
        return False


# -- registry wrappers (seams for tests; thin winreg calls) --------------------


def _registry_read(value_name: str) -> str | None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
        value, _type = winreg.QueryValueEx(key, value_name)
        return str(value)


def _registry_write(value_name: str, data: str) -> None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, data)


def _registry_delete(value_name: str) -> None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.DeleteValue(key, value_name)
