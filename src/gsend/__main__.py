"""Entry point: single-instance named mutex, logging setup, runs the app.

The Windows-specific mutex lives here (AGENTS.md); a second instance exits
silently with exit code 0. Clean shutdown: app.run() stops the poller and the
tray; the mutex is released in the finally block.

`--self-check` (hidden flag, used by docs/BUILD.md verification) runs offline
checks only — no network, no sign-in, no tray, no mutex — and prints PASS/FAIL
lines, exiting 0 or 1. It never prints configuration values, tokens, addresses
or mail content. The frozen (windowed) exe has no console, so it attaches to
the parent's console (or allocates one) before printing.
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import sys

from gsend import app, config, logging_setup

logger = logging.getLogger(__name__)

_MUTEX_NAME = f"Local\\{config.APP_NAME}SingleInstance"
_ERROR_ALREADY_EXISTS = 183

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def _acquire_single_instance_mutex() -> int | None:
    """Create and hold the single-instance mutex; None when one is already held."""
    handle = _kernel32.CreateMutexW(None, 1, _MUTEX_NAME)
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        _kernel32.CloseHandle(handle)
        return None
    return handle


def _self_check_results() -> list[tuple[str, bool]]:
    """Run every offline check; returns (check name, passed) pairs only.

    Names may carry the app version (public); no check ever returns or prints
    configuration values, tokens, addresses or mail content.
    """
    from gsend import __version__

    results: list[tuple[str, bool]] = []
    results.append((f"app version ({__version__})", _try(_check_version)))
    results.append(("settings load", _try(_check_settings)))
    results.append(("accounts load", _try(_check_accounts)))
    results.append(("client config valid (Google endpoints)", _try(_check_client_config)))
    results.append(("keyring is Windows Credential Manager", _try(_check_keyring)))
    results.append(("gmail service builds from bundled discovery", _try(_check_service_build)))
    results.append(("winotify imports", _try(_check_winotify)))
    results.append(("pystray imports", _try(_check_pystray)))
    results.append(("tray icon images generate", _try(_check_icons)))
    return results


def _try(check) -> bool:
    try:
        return bool(check())
    except Exception:
        return False


def _check_version() -> bool:
    from gsend import __version__

    return bool(__version__)


def _check_settings() -> bool:
    from gsend.settings import load as load_settings

    load_settings()  # read-only; a corrupt file recovers to defaults
    return True


def _check_accounts() -> bool:
    from gsend.accounts import AccountStore

    AccountStore().list()  # read-only
    return True


def _check_client_config() -> bool:
    from gsend import auth

    cfg = auth.load_client_config()
    auth._validate_installed_config(cfg.get("installed") or {})
    return True


def _check_keyring() -> bool:
    from gsend import auth

    return auth._keyring_is_secure(auth.keyring.get_keyring())


def _check_service_build() -> bool:
    # Building with a bare httplib2 Http (no credentials) touches no network;
    # static_discovery=True raises UnknownApiNameOrVersion when the bundled
    # document is missing.
    import httplib2
    from googleapiclient.discovery import build

    service = build(
        "gmail", "v1", http=httplib2.Http(timeout=5), static_discovery=True, cache_discovery=False
    )
    service.close()
    return True


def _check_winotify() -> bool:
    import winotify  # noqa: F401 - the import is the check

    return True


def _check_pystray() -> bool:
    import pystray  # noqa: F401 - the import is the check

    return True


def _check_icons() -> bool:
    from gsend.tray import IconState, draw_icon

    return draw_icon(IconState.IDLE).size == (32, 32)


def _ensure_console_output() -> None:
    """Give the windowed (frozen) exe a console so --self-check output shows.

    PyInstaller --windowed ships without a console; attach to the parent's
    (started from a terminal) or allocate one, then point stdout/stderr at it.
    Development runs already have a stdout and frozen-only keeps tests unaffected.
    """
    if not getattr(sys, "frozen", False) or sys.stdout is not None:
        return
    if not _kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
        _kernel32.AllocConsole()
    for name in ("stdout", "stderr"):
        setattr(sys, name, open("CONOUT$", "w", buffering=1, encoding="utf-8"))  # noqa: SIM115


def _write_self_check_log(results: list[tuple[str, bool]], overall_ok: bool) -> None:
    """Frozen-run record for automated verification; check names only, no values."""
    try:
        config.ensure_dir(config.logs_dir())
        with open(config.logs_dir() / "self_check.log", "w", encoding="utf-8") as handle:
            for name, passed in results:
                handle.write(f"{'PASS' if passed else 'FAIL'} {name}\n")
            handle.write(f"{'PASS' if overall_ok else 'FAIL'} self-check overall\n")
    except OSError:
        pass  # a missing record file must not change the exit code


def _run_self_check() -> int:
    _ensure_console_output()
    results = _self_check_results()
    overall_ok = all(passed for _name, passed in results)
    for name, passed in results:
        print(f"{'PASS' if passed else 'FAIL'} {name}", flush=True)
    print(f"{'PASS' if overall_ok else 'FAIL'} self-check overall", flush=True)
    if getattr(sys, "frozen", False):
        _write_self_check_log(results, overall_ok)
    return 0 if overall_ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gsend", description="GSend tray app.")
    parser.add_argument("--self-check", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.self_check:
        return _run_self_check()

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
