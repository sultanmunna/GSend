"""Entry point: single-instance named mutex, logging setup, runs the app.

The Windows-specific mutex lives here (AGENTS.md); a second instance exits
silently with exit code 0. Clean shutdown: app.run() stops the poller and the
tray; the mutex is released in the finally block.
"""

from __future__ import annotations

import ctypes
import logging

from gmail_notifier import app, config, logging_setup

logger = logging.getLogger(__name__)

_MUTEX_NAME = "Local\\GmailNotifierSingleInstance"
_ERROR_ALREADY_EXISTS = 183

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def _acquire_single_instance_mutex() -> int | None:
    """Create and hold the single-instance mutex; None when one is already held."""
    handle = _kernel32.CreateMutexW(None, 1, _MUTEX_NAME)
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        _kernel32.CloseHandle(handle)
        return None
    return handle


def main() -> int:
    mutex = _acquire_single_instance_mutex()
    if mutex is None:
        return 0  # second instance: exit silently
    logging_setup.setup_logging()
    logger.info("%s starting", config.DISPLAY_NAME)
    try:
        return app.run()
    finally:
        _kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    raise SystemExit(main())
