"""Windows toasts via winotify (DECISIONS D-11): layout, click-to-open, summary.

Clicking a toast opens the mail URL through winotify's `launch` attribute
(activationType=protocol) — no callbacks and no action scripts, so no console
flash. The toast body joins the content lines with newlines (winotify passes
them into the toast XML text element). Toast failures are logged by type only
and never raise (docs/ARCHITECTURE.md section 9).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from gmail_notifier import config, formatting, links, text_utils
from gmail_notifier.models import Mail
from gmail_notifier.settings import Settings
from gmail_notifier.state import AppState

logger = logging.getLogger(__name__)

_APP_ID = config.APP_NAME


class ToastBackend:
    """What Notifier needs from a toast library; the test seam."""

    def show(self, title: str, message: str, launch: str | None, sound: bool) -> None:
        raise NotImplementedError


class WinotifyBackend(ToastBackend):
    """Real toasts; winotify is imported lazily to keep startup light."""

    def show(self, title: str, message: str, launch: str | None, sound: bool) -> None:
        from winotify import Notification, audio

        # winotify embeds these strings into a generated PowerShell script
        # (expandable here-string + CDATA); they must be escaped at our
        # boundary so mail content can never inject XML or commands (D-18).
        notification = Notification(
            app_id=_APP_ID,
            title=text_utils.escape_winotify(title),
            msg=text_utils.escape_winotify(message),
            launch=text_utils.escape_winotify(launch) if launch else "",
        )
        # set_audio(sound, loop): loop is a required positional in winotify 1.1.
        notification.set_audio(audio.Default if sound else audio.Silent, loop=False)
        notification.show()


class Notifier:
    """Sends new-mail and reauth toasts; burst mail becomes one summary toast."""

    def __init__(
        self, settings: Settings, state: AppState, backend: ToastBackend | None = None
    ) -> None:
        self._settings = settings
        self._state = state
        self._backend = backend if backend is not None else WinotifyBackend()

    def update_settings(self, settings: Settings) -> None:
        self._settings = settings

    def notify_new_mails(self, account_email: str, mails: list[Mail]) -> None:
        """One toast per mail, or a single summary toast when over the cap."""
        if not mails:
            return
        if len(mails) > self._settings.max_toasts_per_poll:
            self._safe(lambda: self._send_summary(account_email, mails))
            return
        for mail in mails:  # each toast fails alone so the rest still show
            self._safe(lambda m=mail: self._send_mail_toast(account_email, m))

    def notify_reauth_needed(self, account_email: str) -> None:
        self._safe(lambda: self._send_reauth_toast(account_email))

    def notify_welcome(self, account_email: str) -> None:
        """First-sign-in confirmation (docs/PRODUCT.md section 5)."""
        self._safe(
            lambda: self._backend.show(
                "Gmail Notifier",
                f"Signed in as {account_email}. You'll get notifications for new mail.",
                None,
                self._settings.notification_sound,
            )
        )

    def notify_message(self, title: str, message: str) -> None:
        """Informational toast without a launch target (no sound)."""
        self._safe(lambda: self._backend.show(title, message, None, False))

    # -- internals ----------------------------------------------------------------

    def _safe(self, job) -> None:
        try:
            job()
        except Exception as exc:
            logger.warning("toast failed (%s)", type(exc).__name__)

    def _send_mail_toast(self, account_email: str, mail: Mail) -> None:
        content = formatting.toast_content(mail, self._settings, self._display_for(account_email))
        self._backend.show(
            content.title,
            "\n".join(content.lines),
            self._launch_url(lambda: links.mail_url(mail.account, mail.thread_id)),
            self._settings.notification_sound,
        )

    def _send_summary(self, account_email: str, mails: list[Mail]) -> None:
        content = formatting.summary_toast(mails, self._display_for(account_email))
        self._backend.show(
            content.title,
            "\n".join(content.lines),
            self._launch_url(lambda: links.inbox_url(account_email)),
            self._settings.notification_sound,
        )

    @staticmethod
    def _launch_url(build: Callable[[], str]) -> str | None:
        """The launch URL, or None when the parts do not validate (still toast).

        A tampered message id or malformed account email must never become a
        URL; the toast simply loses its click target instead (SECURITY section 6).
        """
        try:
            return build()
        except ValueError:
            logger.warning("toast launch skipped (unvalidated URL parts)")
            return None

    def _send_reauth_toast(self, account_email: str) -> None:
        display = self._display_for(account_email)
        message = (
            f"Sign-in needed for {display}. Right-click the tray icon and choose Sign in again."
        )
        self._backend.show("Gmail Notifier: sign-in needed", message, None, False)

    def _display_for(self, account_email: str) -> str | None:
        accounts = self._state.accounts()
        account = next((a for a in accounts if a.email == account_email), None)
        label = account.label if account else None
        return formatting.account_display(self._settings, len(accounts), account_email, label)
