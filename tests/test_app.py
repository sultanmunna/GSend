"""Smoke tests for app.py and tray.py, plus M6 settings/sign-in wiring tests."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

from gmail_notifier import app as app_module
from gmail_notifier import autostart
from gmail_notifier.accounts import AccountStore
from gmail_notifier.app import _App, _SingleFlightWorker
from gmail_notifier.models import Account, AccountStatus, Mail
from gmail_notifier.settings import Settings
from gmail_notifier.state import AppState
from gmail_notifier.tray import IconState, Tray, TrayCallbacks, draw_icon


class FakeRegistry:
    """In-memory stand-in for the HKCU Run key (same shape as in test_autostart)."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def read(self, name: str) -> str | None:
        return self.values.get(name)

    def write(self, name: str, data: str) -> None:
        self.values[name] = data

    def delete(self, name: str) -> None:
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


def _callbacks() -> TrayCallbacks:
    return TrayCallbacks(
        on_open_mail=lambda mail: None,
        on_open_inbox=lambda email: None,
        on_add_account=lambda: None,
        on_remove_account=lambda email: None,
        on_sign_in_again=lambda email: None,
        on_check_now=lambda: None,
        on_toggle_setting=lambda key: None,
        on_quit=lambda: None,
    )


class FakeNotifier:
    """Records every notifier call; never touches a real toast."""

    def __init__(self) -> None:
        self.welcomes: list[str] = []
        self.messages: list[tuple[str, str]] = []
        self.settings_updates: list[Settings] = []

    def update_settings(self, settings: Settings) -> None:
        self.settings_updates.append(settings)

    def notify_new_mails(self, email: str, mails: list[Mail]) -> None:
        pass

    def notify_reauth_needed(self, email: str) -> None:
        pass

    def notify_welcome(self, email: str) -> None:
        self.welcomes.append(email)

    def notify_message(self, title: str, message: str) -> None:
        self.messages.append((title, message))


def make_app(tmp_path, notifier=None, settings=None):
    store = AccountStore(tmp_path / "accounts.json")
    state = AppState()
    app = _App(settings or Settings(), store, state, notifier=notifier)
    return app, store, state


def wait_for_worker(app: _App, timeout: float = 5.0) -> bool:
    for _ in range(int(timeout / 0.05)):
        if not app._auth_worker.busy:
            return True
        time.sleep(0.05)
    return False


def install_fake_registry(monkeypatch) -> FakeRegistry:
    fake = FakeRegistry()
    monkeypatch.setattr(autostart, "_registry_read", fake.read)
    monkeypatch.setattr(autostart, "_registry_write", fake.write)
    monkeypatch.setattr(autostart, "_registry_delete", fake.delete)
    return fake


def make_mail(mid: str, *, account: str = "a@x.com", unread: bool = True) -> Mail:
    return Mail(
        account=account,
        id=mid,
        thread_id=f"t-{mid}",
        sender_name="Jane Doe",
        sender_email="jane@example.com",
        subject="Hello",
        snippet="Preview",
        received_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        unread=unread,
    )


# --- _SingleFlightWorker -------------------------------------------------------


def test_single_flight_worker_ignores_extra_starts():
    worker = _SingleFlightWorker("auth-worker-test")
    running = threading.Event()
    release = threading.Event()

    def job() -> None:
        running.set()
        release.wait(5)

    assert worker.start(job) is True
    assert running.wait(5)
    assert worker.busy is True
    assert worker.start(lambda: None) is False  # second click while one runs

    release.set()
    for _ in range(100):  # wait for the worker to finish
        if not worker.busy:
            break
        time.sleep(0.05)
    assert worker.busy is False
    assert worker.start(lambda: None) is True  # can run again


# --- Tray menu smoke ------------------------------------------------------------


def test_tray_menu_without_accounts():
    state = AppState()
    tray = Tray(state, Settings(), _callbacks())
    items = list(tray._menu_items())
    texts = [getattr(item, "text", None) for item in items]
    assert "Add account…" in texts
    assert "No recent mail" in texts
    assert "Quit" in texts
    assert "Check now" in texts


def test_tray_refresh_replaces_starting_tooltip():
    # The constructor tooltip says "starting…"; with zero accounts no state
    # change ever fires, so the app must refresh once at startup to show the
    # real no-account text.
    state = AppState()
    tray = Tray(state, Settings(), _callbacks())
    assert tray._icon.title == "Gmail Notifier: starting…"
    tray.refresh()
    assert tray._icon.title == "Gmail Notifier: no account. Right-click to add one."


def test_tray_menu_with_mail_and_accounts():
    state = AppState()
    state.set_accounts(
        [
            Account("a@x.com", None, AccountStatus.OK),
            Account("b@x.com", "Work", AccountStatus.NEEDS_REAUTH),
        ]
    )
    state.update_mails("a@x.com", [make_mail("m1")])
    tray = Tray(state, Settings(), _callbacks())
    items = list(tray._menu_items())

    mail_item = items[0]
    assert "● Jane Doe: Hello" in mail_item.text  # auto shows accounts only with 2+
    assert "\t" in mail_item.text and mail_item.text.endswith("· a")  # age · account, short name
    assert mail_item.default is True  # left click opens the latest mail

    texts = [getattr(item, "text", None) for item in items]
    assert "Open Gmail" in texts  # several accounts -> submenu
    accounts_menu = next(item for item in items if getattr(item, "text", None) == "Accounts")
    submenu_texts = [sub.text for sub in accounts_menu.submenu]
    assert any("b@x.com" in text and "⚠" in text for text in submenu_texts)
    assert "Add account…" in submenu_texts


def test_menu_actions_receive_the_frozen_value_not_the_icon():
    # pystray calls one-argument actions with the tray icon; the menu must
    # freeze each item's mail/email in a zero-argument closure instead
    # (regression: `lambda m=mail:` bound the icon and crashed on click).
    state = AppState()
    state.set_accounts(
        [
            Account("a@x.com", None, AccountStatus.OK),
            Account("b@x.com", None, AccountStatus.OK),
        ]
    )
    state.update_mails("a@x.com", [make_mail("m1")])
    opened_mails: list[Mail] = []
    opened_inboxes: list[str] = []
    callbacks = TrayCallbacks(
        on_open_mail=opened_mails.append,
        on_open_inbox=opened_inboxes.append,
        on_add_account=lambda: None,
        on_remove_account=lambda email: None,
        on_sign_in_again=lambda email: None,
        on_check_now=lambda: None,
        on_toggle_setting=lambda key: None,
        on_quit=lambda: None,
    )
    tray = Tray(state, Settings(), callbacks)

    items = list(tray._menu_items())
    items[0](None)  # pystray invokes MenuItem(icon); the wrapper drops the args
    assert opened_mails == [make_mail("m1")]

    open_menu = next(item for item in items if getattr(item, "text", None) == "Open Gmail")
    for sub in open_menu.submenu:
        sub(None)
    assert opened_inboxes == ["a@x.com", "b@x.com"]  # one per item, not the last one


def test_account_submenu_actions_receive_the_frozen_email():
    state = AppState()
    state.set_accounts([Account("a@x.com", None, AccountStatus.NEEDS_REAUTH)])
    reauth_requested: list[str] = []
    removals: list[str] = []
    callbacks = TrayCallbacks(
        on_open_mail=lambda mail: None,
        on_open_inbox=lambda email: None,
        on_add_account=lambda: None,
        on_remove_account=removals.append,
        on_sign_in_again=reauth_requested.append,
        on_check_now=lambda: None,
        on_toggle_setting=lambda key: None,
        on_quit=lambda: None,
    )
    tray = Tray(state, Settings(), callbacks)

    accounts_menu = next(
        item for item in tray._menu_items() if getattr(item, "text", None) == "Accounts"
    )
    account_menu = next(iter(accounts_menu.submenu))  # the only account's submenu
    subs = {sub.text: sub for sub in account_menu.submenu}
    subs["Sign in again"](None)
    subs["Remove"](None)
    assert reauth_requested == ["a@x.com"]
    assert removals == ["a@x.com"]


def test_tray_refresh_updates_icon_and_title():
    state = AppState()
    state.set_accounts([Account("a@x.com", None, AccountStatus.OK)])
    tray = Tray(state, Settings(), _callbacks())
    state.update_mails("a@x.com", [make_mail("m1")])
    tray.refresh()  # app.py subscribes this to state changes; the poller calls it too
    assert tray._icon.title == "Jane Doe\nHello"
    assert "●" not in tray._icon.title
    assert tray._icon.icon is not None


def test_icon_states_draw_differently():
    idle = draw_icon(IconState.IDLE).tobytes()
    unread = draw_icon(IconState.UNREAD).tobytes()
    warning = draw_icon(IconState.WARNING).tobytes()
    assert len({idle, unread, warning}) == 3  # three distinct images


# --- M6: settings toggles, autostart default, re-sign-in UX -------------------


def test_toggle_propagates_everywhere(tmp_path, monkeypatch):
    saved: list[Settings] = []
    monkeypatch.setattr(app_module, "save_settings", lambda s: saved.append(s))
    app, _store, _state = make_app(tmp_path, notifier=FakeNotifier())
    app._toggle_setting("show_preview")
    assert app._settings.show_preview is False
    assert app._poller._settings.show_preview is False
    assert app._tray._settings.show_preview is False
    assert saved and saved[-1].show_preview is False


def test_toggle_start_with_windows_updates_registry(tmp_path, monkeypatch):
    install_fake_registry(monkeypatch)
    monkeypatch.setattr(app_module, "save_settings", lambda s: None)
    app, _store, _state = make_app(tmp_path, notifier=FakeNotifier())
    app._toggle_setting("start_with_windows")  # default True -> False
    assert app._settings.start_with_windows is False
    assert autostart.is_enabled() is False
    app._toggle_setting("start_with_windows")  # back to True
    assert autostart.is_enabled() is True


def test_toggle_only_primary_rebaselines_silently(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "save_settings", lambda s: None)
    app, store, _state = make_app(tmp_path, notifier=FakeNotifier())
    store.add("a@x.com")
    app._poller.reload_accounts()
    poll = app._poller._poll_state["a@x.com"]
    poll.baseline_done = True
    app._toggle_setting("only_primary")
    assert app._settings.only_primary is False
    assert poll.baseline_done is False  # next poll re-baselines without toasts


def test_unknown_toggle_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "save_settings", lambda s: None)
    app, _store, _state = make_app(tmp_path, notifier=FakeNotifier())
    before = app._settings
    app._toggle_setting("bogus_key")
    assert app._settings is before


def test_welcome_toast_and_autostart_default_on_first_account(tmp_path, monkeypatch):
    fake_registry = install_fake_registry(monkeypatch)
    monkeypatch.setattr(app_module.auth, "add_account_interactive", lambda: "first@x.com")
    fake = FakeNotifier()
    app, store, _state = make_app(tmp_path, notifier=fake)
    app._add_account()
    assert wait_for_worker(app)
    assert fake.welcomes == ["first@x.com"]
    assert store.has("first@x.com")
    assert "GmailNotifier" in fake_registry.values  # default applied once


def test_different_account_on_re_sign_in_becomes_new_account(tmp_path, monkeypatch):
    install_fake_registry(monkeypatch)
    monkeypatch.setattr(app_module.auth, "add_account_interactive", lambda: "b@other.com")
    fake = FakeNotifier()
    store = AccountStore(tmp_path / "accounts.json")
    store.add("a@x.com")  # before construction, so the app's state knows it
    state = AppState()
    app = _App(Settings(), store, state, notifier=fake)
    app._sign_in_again("a@x.com")
    assert wait_for_worker(app)
    assert store.has("b@other.com")
    assert fake.welcomes == []  # not the first account
    assert any("b@other.com" in message and "a@x.com" in message for _t, message in fake.messages)


def test_tray_menu_escapes_ampersands_from_mail_and_accounts():
    """Win32 menus treat '&' as the accelerator marker: content must be doubled."""
    from datetime import timedelta

    state = AppState()
    state.set_accounts(
        [
            Account("a@x.com", None, AccountStatus.OK),
            Account("b@x.com", "R&D", AccountStatus.OK),
        ]
    )
    hostile = Mail(
        account="a@x.com",
        id="16a7c1f2e3d4b5a6",
        thread_id="16a7c1f2e3d4b5a6",
        sender_name="Tom & Jerry",
        sender_email="tom@evil.test",
        subject="Q1 & Q2 savings",
        snippet="Preview",
        received_at=datetime.now(UTC) - timedelta(minutes=1),
        unread=True,
    )
    state.update_mails("a@x.com", [hostile])
    tray = Tray(state, Settings(show_account="always"), _callbacks())
    items = list(tray._menu_items())
    mail_line = items[0].text
    assert "Tom && Jerry" in mail_line
    assert "Q1 && Q2" in mail_line
    texts = [getattr(item, "text", "") for item in items]
    accounts_index = texts.index("Accounts")
    account_texts = [item.text for item in items[accounts_index].submenu]
    assert "a@x.com" in account_texts
    open_gmail_index = texts.index("Open Gmail")
    open_texts = [item.text for item in items[open_gmail_index].submenu]
    assert "R&&D" in open_texts


# --- startup keyring case migration (SEC-03 follow-up) -------------------------


def test_startup_migration_renames_account_row_and_keyring(tmp_path, fake_keyring):
    """Mixed-case legacy rows end up lower-cased in accounts.json and keyring."""
    store = AccountStore(tmp_path / "accounts.json")
    store.add("MixedCase@Gmail.COM", label="Work")
    fake_keyring.set_password("GmailNotifier", "MixedCase@Gmail.COM", "stored-token")
    app_module._migrate_account_keys(store)
    accounts = store.list()
    assert len(accounts) == 1
    assert accounts[0].email == "mixedcase@gmail.com"
    assert accounts[0].label == "Work"
    assert fake_keyring.get_password("GmailNotifier", "mixedcase@gmail.com") == "stored-token"
    assert fake_keyring.get_password("GmailNotifier", "MixedCase@Gmail.COM") is None


def test_startup_migration_leaves_normalized_accounts_alone(tmp_path, fake_keyring):
    store = AccountStore(tmp_path / "accounts.json")
    store.add("user@example.com")
    fake_keyring.set_password("GmailNotifier", "user@example.com", "stored-token")
    before = dict(fake_keyring.entries)
    app_module._migrate_account_keys(store)
    assert [a.email for a in store.list()] == ["user@example.com"]
    assert fake_keyring.entries == before
