"""pystray tray icon: icon states, dynamic menu, tooltip. No business logic.

Every action arrives as a callback in `TrayCallbacks` (wired by app.py); text
comes from formatting.py; data comes from the AppState snapshot. No imports of
poller or auth (docs/ARCHITECTURE.md section 3). Icons are drawn with Pillow at
runtime (docs/PRODUCT.md section 6.1) — no binary assets. On Windows, pystray's
title/icon setters use Shell_NotifyIcon and update_menu() rebuilds a plain
HMENU, so refresh() is safe from the poller thread (verified against the
pystray 0.19 win32 source; see the M4 report).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import StrEnum, auto
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from gmail_notifier import formatting
from gmail_notifier.models import Account, AccountStatus, Mail
from gmail_notifier.settings import Settings
from gmail_notifier.state import AppState

logger = logging.getLogger(__name__)


def _action_with(call: Callable[[Mail | str], None], value: Mail | str) -> Callable[[], None]:
    """Zero-argument menu action with `value` frozen in.

    pystray inspects `co_argcount` and calls one-argument actions with the tray
    icon, so the usual `lambda v=value:` freeze silently binds the icon instead
    of the value. A closure over a factory parameter binds the value.
    """
    return lambda: call(value)


_ICON_SIZE = 32
_ENVELOPE_FILL = (66, 133, 244, 255)
_ENVELOPE_LINE = (43, 93, 173, 255)
_UNREAD_DOT = (234, 67, 53, 255)
_WARNING_DOT = (251, 148, 0, 255)


class IconState(StrEnum):
    """Tray icon states per docs/PRODUCT.md section 6.1."""

    IDLE = auto()
    UNREAD = auto()
    WARNING = auto()


@dataclass(frozen=True)
class TrayCallbacks:
    """Everything the tray can trigger; wired by app.py."""

    on_open_mail: Callable[[Mail], None]
    on_open_inbox: Callable[[str], None]
    on_add_account: Callable[[], None]
    on_remove_account: Callable[[str], None]
    on_sign_in_again: Callable[[str], None]
    on_check_now: Callable[[], None]
    on_toggle_setting: Callable[[str], None]
    on_quit: Callable[[], None]


def draw_icon(state: IconState, size: int = _ICON_SIZE) -> Image.Image:
    """Draw the envelope icon for a state: idle, unread (red dot) or warning (amber).

    All geometry scales with `size` (designed on a 32 px grid) so the same
    drawing feeds both the tray icon and the multi-size .ico file.
    """
    scale = size / _ICON_SIZE

    def box(x0: int, y0: int, x1: int, y1: int) -> list[int]:
        return [round(x0 * scale), round(y0 * scale), round(x1 * scale), round(y1 * scale)]

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        box(2, 7, 29, 25), radius=round(2 * scale), fill=_ENVELOPE_FILL, outline=_ENVELOPE_LINE
    )
    draw.line(
        [box(3, 8, 0, 0)[:2], box(16, 18, 0, 0)[:2]],
        fill=_ENVELOPE_LINE,
        width=max(1, round(2 * scale)),
    )
    draw.line(
        [box(29, 8, 0, 0)[:2], box(16, 18, 0, 0)[:2]],
        fill=_ENVELOPE_LINE,
        width=max(1, round(2 * scale)),
    )
    if state is not IconState.IDLE:
        color = _UNREAD_DOT if state is IconState.UNREAD else _WARNING_DOT
        draw.ellipse(box(19, 1, 30, 12), fill=color, outline=(255, 255, 255, 255))
    return image


class Tray:
    """Owns the pystray icon and menu; all behavior arrives via callbacks."""

    def __init__(
        self,
        state: AppState,
        settings: Settings,
        callbacks: TrayCallbacks,
        data_folder: Path | None = None,
    ) -> None:
        self._state = state
        self._settings = settings
        self._callbacks = callbacks
        self._data_folder = data_folder
        self._icon = pystray.Icon(
            "GmailNotifier",
            icon=draw_icon(IconState.IDLE),
            title="Gmail Notifier: starting…",
            menu=pystray.Menu(self._menu_items),
        )

    def run(self) -> None:
        """Block the calling (main) thread until stop()."""
        self._icon.run()

    def stop(self) -> None:
        self._icon.stop()

    def update_settings(self, settings: Settings) -> None:
        self._settings = settings
        self.refresh()

    def refresh(self) -> None:
        """Re-render icon, tooltip and menu from the current state; thread-safe on Windows."""
        try:
            accounts = self._state.accounts()
            icon_state = _state_for(self._state, accounts)
            self._icon.icon = draw_icon(icon_state)
            self._icon.title = formatting.tooltip(self._snapshot(accounts), self._settings)
            self._icon.update_menu()
        except Exception as exc:
            logger.exception("tray refresh failed (%s)", type(exc).__name__)

    # -- menu -------------------------------------------------------------------

    def _menu_items(self) -> Iterator[pystray.MenuItem]:
        """Generator consumed by pystray whenever the menu is rebuilt."""
        accounts = self._state.accounts()
        mails = self._state.latest(3)
        callbacks = self._callbacks

        if mails:
            for index, mail in enumerate(mails):
                yield pystray.MenuItem(
                    formatting.menu_line(
                        mail, self._settings, self._display_for(mail.account, accounts)
                    ),
                    _action_with(callbacks.on_open_mail, mail),
                    default=index == 0,
                )
        else:
            yield pystray.MenuItem("No recent mail", None, enabled=False)

        yield pystray.Menu.SEPARATOR
        if accounts:
            yield self._open_gmail_item(accounts, default=not mails)
        else:
            yield pystray.MenuItem("Add account…", callbacks.on_add_account, default=True)
        yield pystray.MenuItem("Check now", callbacks.on_check_now)

        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem("Accounts", pystray.Menu(*self._account_items(accounts)))

        yield pystray.Menu.SEPARATOR
        yield self._settings_item()

        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem("Quit", callbacks.on_quit)

    def _settings_item(self) -> pystray.MenuItem:
        """Settings submenu (docs/PRODUCT.md section 6.2): checkable toggles."""
        callbacks = self._callbacks

        def toggle(key: str):
            return lambda: callbacks.on_toggle_setting(key)

        items = [
            pystray.MenuItem(
                "Show message preview",
                toggle("show_preview"),
                checked=lambda _item: self._settings.show_preview,
                radio=False,
            ),
            pystray.MenuItem(
                "Primary tab only",
                toggle("only_primary"),
                checked=lambda _item: self._settings.only_primary,
                radio=False,
            ),
            pystray.MenuItem(
                "Start with Windows",
                toggle("start_with_windows"),
                checked=lambda _item: self._settings.start_with_windows,
                radio=False,
            ),
        ]
        if self._data_folder is not None:
            items.append(pystray.MenuItem("Open data folder", self._open_data_folder))
        return pystray.MenuItem("Settings", pystray.Menu(*items))

    def _open_data_folder(self) -> None:
        if self._data_folder is not None:
            os.startfile(self._data_folder)  # noqa: S606 - Explorer, by design

    def _open_gmail_item(self, accounts: list[Account], *, default: bool) -> pystray.MenuItem:
        if len(accounts) == 1:
            return pystray.MenuItem(
                "Open Gmail",
                _action_with(self._callbacks.on_open_inbox, accounts[0].email),
                default=default,
            )
        items = [
            pystray.MenuItem(
                a.label or a.email,
                _action_with(self._callbacks.on_open_inbox, a.email),
            )
            for a in accounts
        ]
        # pystray submenus: a Menu passed as the item's action.
        return pystray.MenuItem("Open Gmail", pystray.Menu(*items), default=default)

    def _account_items(self, accounts: list[Account]) -> list[pystray.MenuItem]:
        items: list[pystray.MenuItem] = []
        for account in accounts:
            text = account.email
            if account.status is AccountStatus.NEEDS_REAUTH:
                text += "  ⚠"
            subs: list[pystray.MenuItem] = []
            if account.status is AccountStatus.NEEDS_REAUTH:
                subs.append(
                    pystray.MenuItem(
                        "Sign in again",
                        _action_with(self._callbacks.on_sign_in_again, account.email),
                    )
                )
            subs.append(
                pystray.MenuItem(
                    "Remove",
                    _action_with(self._callbacks.on_remove_account, account.email),
                )
            )
            items.append(pystray.MenuItem(text, pystray.Menu(*subs)))
        items.append(pystray.MenuItem("Add account…", self._callbacks.on_add_account))
        return items

    # -- helpers ------------------------------------------------------------------

    def _display_for(self, email: str, accounts: list[Account]) -> str | None:
        account = next((a for a in accounts if a.email == email), None)
        return formatting.account_display(
            self._settings, len(accounts), email, account.label if account else None
        )

    def _snapshot(self, accounts: list[Account]) -> formatting.TooltipSnapshot:
        latest = self._state.latest(1)
        return formatting.TooltipSnapshot(
            account_count=len(accounts),
            needs_sign_in=any(a.status is AccountStatus.NEEDS_REAUTH for a in accounts),
            latest=latest[0] if latest else None,
            show_account=(self._display_for(latest[0].account, accounts) if latest else None),
        )


def _state_for(state: AppState, accounts: list[Account]) -> IconState:
    if state.worst_status() is not AccountStatus.OK:
        return IconState.WARNING
    if state.has_unread():
        return IconState.UNREAD
    return IconState.IDLE
