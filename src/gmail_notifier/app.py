"""Composition root: creates settings, accounts, state, poller, tray and the
stub notifier, and wires their callbacks; handles quit.

Everything here is wiring; behavior lives in the modules. Network and OAuth
work runs on worker threads (never the tray thread); at most one sign-in runs
at a time and further clicks are ignored (docs/ARCHITECTURE.md sections 1-3).
The M5 milestone replaces the stub notifier with real toasts.
"""

from __future__ import annotations

import logging
import threading
import webbrowser
from collections.abc import Callable
from dataclasses import replace

from gmail_notifier import auth, autostart, config, links, logging_setup
from gmail_notifier.accounts import AccountStore
from gmail_notifier.gmail_client import GmailClient
from gmail_notifier.models import Account, AccountStatus, Mail
from gmail_notifier.notifier import Notifier
from gmail_notifier.poller import Poller
from gmail_notifier.settings import Settings
from gmail_notifier.settings import load as load_settings
from gmail_notifier.settings import save as save_settings
from gmail_notifier.state import AppState
from gmail_notifier.tray import Tray, TrayCallbacks

logger = logging.getLogger(__name__)

_TOGGLEABLE_SETTINGS = ("show_preview", "only_primary", "start_with_windows")


class _SingleFlightWorker:
    """Runs at most one job at a time; extra starts are ignored (menu double-click)."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._lock = threading.Lock()
        self._busy = False

    def start(self, job: Callable[[], None]) -> bool:
        with self._lock:
            if self._busy:
                return False
            self._busy = True

        def runner() -> None:
            try:
                job()
            finally:
                with self._lock:
                    self._busy = False

        threading.Thread(target=runner, name=self._name, daemon=True).start()
        return True

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy


class _App:
    """Owns every component and their callbacks; one instance per process."""

    def __init__(
        self,
        settings: Settings,
        store: AccountStore,
        state: AppState,
        notifier: Notifier | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._state = state
        self._auth_worker = _SingleFlightWorker("auth-worker")
        self._poller_thread: threading.Thread | None = None
        self._removal_thread: threading.Thread | None = None
        state.set_accounts([Account(a.email, a.label, AccountStatus.OK) for a in store.list()])
        self._notifier = notifier if notifier is not None else Notifier(settings, state)
        self._poller = Poller(
            client_factory=self._client_factory,
            account_store=store,
            state=state,
            settings=settings,
            on_new_mails=self._on_new_mails,
            on_reauth_needed=self._on_reauth_needed,
        )
        self._tray = Tray(
            state,
            settings,
            TrayCallbacks(
                on_open_mail=self._open_mail,
                on_open_inbox=self._open_inbox,
                on_add_account=self._add_account,
                on_remove_account=self._remove_account,
                on_sign_in_again=self._sign_in_again,
                on_check_now=self._poller.wake,
                on_toggle_setting=self._toggle_setting,
                on_quit=self._quit,
            ),
            data_folder=config.appdata_dir(),
        )
        state.subscribe(self._on_state_changed)
        # Initial render: with zero accounts no state change ever fires, and the
        # tooltip must not stay on the constructor's "starting…" text.
        self._tray.refresh()

    # -- lifecycle ----------------------------------------------------------------

    def start(self) -> None:
        self._poller_thread = threading.Thread(target=self._poller.run, name="poller", daemon=True)
        self._poller_thread.start()
        self._maybe_first_run()

    def wait(self) -> None:
        """Block the main thread in the tray loop until quit; then shut down."""
        self._tray.run()
        self._shutdown()

    def _shutdown(self) -> None:
        self._poller.stop()
        if self._poller_thread is not None:
            self._poller_thread.join(timeout=5)
        if self._removal_thread is not None:
            self._removal_thread.join(timeout=5)
        logger.info("shutdown complete")

    # -- callbacks ----------------------------------------------------------------

    def _client_factory(self, email: str) -> GmailClient:
        return GmailClient(email, auth.credentials_for(email))

    def _on_new_mails(self, email: str, mails: list[Mail]) -> None:
        self._notifier.notify_new_mails(email, mails)

    def _on_reauth_needed(self, email: str) -> None:
        self._notifier.notify_reauth_needed(email)

    def _open_mail(self, mail: Mail) -> None:
        try:
            url = links.mail_url(mail.account, mail.thread_id)
        except ValueError:
            logger.warning("mail open skipped (unvalidated id or account value)")
        else:
            webbrowser.open(url)
        self._state.mark_opened(mail.id)

    def _open_inbox(self, email: str) -> None:
        try:
            url = links.inbox_url(email)
        except ValueError:
            logger.warning("inbox open skipped (unvalidated account value)")
            return
        webbrowser.open(url)

    def _add_account(self) -> None:
        self._run_sign_in()

    def _sign_in_again(self, email: str) -> None:
        logger.debug("re-sign-in requested for %s", email)
        self._run_sign_in(expected=email)

    def _remove_account(self, email: str) -> None:
        def job() -> None:
            auth.remove_account(email)  # network revoke; off the tray thread
            self._store.remove(email)
            self._poller.reload_accounts()
            logger.info("account removed")

        # Tracked so quit can wait for it: a mid-removal exit must not leave
        # an orphaned token in Credential Manager.
        self._removal_thread = threading.Thread(target=job, name="remove-account", daemon=True)
        self._removal_thread.start()

    def _toggle_setting(self, key: str) -> None:
        if key not in _TOGGLEABLE_SETTINGS:
            logger.warning("ignored unknown setting toggle (%s)", key)
            return
        current = getattr(self._settings, key)
        self._apply_settings(replace(self._settings, **{key: not current}))
        if key == "only_primary":
            self._poller.rebaseline()  # silent re-baseline for the wider listing
        if key == "start_with_windows":
            if self._settings.start_with_windows:
                autostart.enable()
            else:
                autostart.disable()

    def _quit(self) -> None:
        logger.info("quit requested")
        self._tray.stop()

    # -- internals ------------------------------------------------------------------

    def _run_sign_in(self, expected: str | None = None) -> None:
        had_accounts = bool(self._state.accounts())

        def job() -> None:
            try:
                email = auth.add_account_interactive()
            except Exception as exc:  # AuthCancelled and friends; never kill the worker
                logger.warning("sign-in did not complete (%s)", type(exc).__name__)
                return
            self._on_signed_in(expected, email, had_accounts)

        started = self._auth_worker.start(job)
        if not started:
            logger.info("sign-in already running; extra click ignored")

    def _on_signed_in(self, expected: str | None, actual: str, had_accounts: bool) -> None:
        if expected is not None and actual != expected:
            # The user picked a different Google account: keep it as a new account.
            logger.info("sign-in returned a different account than requested")
            self._notifier.notify_message(
                "Gmail Notifier: account added",
                f"You signed in as {actual} instead of {expected}. "
                "Both accounts are now watched; sign in again for the other one.",
            )
        self._store.add(actual)
        self._poller.reload_accounts()
        if not had_accounts:  # first account ever: defaults per PRODUCT section 7
            if self._settings.start_with_windows and not autostart.is_enabled():
                autostart.enable()
            self._notifier.notify_welcome(actual)
        logger.info("sign-in finished; account ready")

    def _maybe_first_run(self) -> None:
        if self._state.accounts() or self._settings.first_run_done:
            return
        self._apply_settings(replace(self._settings, first_run_done=True))
        logger.info("first run: starting automatic sign-in")
        self._add_account()

    def _apply_settings(self, settings: Settings) -> None:
        save_settings(settings)
        self._settings = settings
        self._poller.update_settings(settings)
        self._notifier.update_settings(settings)
        self._tray.update_settings(settings)

    def _on_state_changed(self) -> None:
        self._tray.refresh()  # safe from the poller thread on Windows


def run() -> int:
    """Build the app, start the poller and block in the tray loop until quit."""
    logging_setup.setup_logging()
    settings = load_settings()
    state = AppState()
    application = _App(settings, AccountStore(), state)
    application.start()
    application.wait()
    return 0
