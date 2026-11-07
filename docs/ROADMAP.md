# ROADMAP.md

One milestone per agent session. Tick the boxes when done. Prompts for each milestone are in `docs/AGENT_PROMPTS.md`.

Order matters: each milestone builds on the previous one.

## M0 — Scaffold, models, settings, text utilities
- [x] `pyproject.toml`, `.gitignore`, `client_config.example.json`
- [x] Package skeleton: every module in the layout exists with a responsibility docstring
- [x] Implemented: `config`, `errors`, `models`, `settings`, `text_utils`, `logging_setup`
- [x] Tests for text_utils (RFC 2047, unicode, snippets, truncation), settings, models

**Acceptance:** `pip install -e ".[dev]"`, `pytest` and `ruff check .` pass; `python -m gmail_notifier` logs a startup line and exits cleanly.

## M1 — Auth and accounts
- [x] `auth.py`: client config loading, `add_account_interactive`, `credentials_for`, `remove_account`
- [x] `accounts.py`: `AccountStore` with atomic JSON writes
- [x] `scripts/dev_add_account.py`
- [x] Tests with mocked keyring and flow

**Acceptance:** Running the dev script opens Chrome, the user picks an account, the email is printed, the token appears in Windows Credential Manager, `accounts.json` has the email and **no token**. Adding the same account twice does not duplicate it. Removal deletes both.

## M2 — Gmail client and parsing
- [x] `gmail_client.py` (`latest_inbox_ids`, `get_mail`, `profile_email`) plus pure parser
- [x] `links.py`
- [x] Error mapping to `errors.py`
- [x] `scripts/dev_fetch.py` (prints the latest 3 mails to the console only)
- [x] Tests with JSON fixtures (encoded headers, missing subject, no display name, HTML entities)

**Acceptance:** `dev_fetch.py` shows the 3 latest mails of a real account with correct sender names and subjects (including non-ASCII). Tests pass offline.

## M3 — State and poller
- [x] `state.py` (thread-safe, merged latest N, subscriptions)
- [x] `poller.py` (baseline, dedupe, cutoff, backoff, reauth handling, wake, stop)
- [x] Tests with a fake client for every rule in ARCHITECTURE section 7

**Acceptance:** A console harness (no tray) prints "new mail" events within one interval of a real mail arriving, prints nothing at startup, survives offline/online, and never duplicates an event.

## M4 — Formatting, tray, app wiring
- [x] `formatting.py` (menu line, tooltip, toast content) with tests for limits
- [x] `tray.py` (icon states, dynamic menu, default left-click action)
- [x] `app.py`, `__main__.py` (single instance), stub notifier that only logs
- [x] First-run auto sign-in, Add/Remove account from the menu

**Acceptance:** Tray icon appears; right-click menu shows the 3 latest mails with accounts; tooltip shows sender and subject within 127 characters; adding a second account works; Quit exits cleanly with no leftover threads.

## M5 — Notifications
- [x] `notifier.py` with title/sender/preview/account layout
- [x] Click opens the right mail; summary toast for bursts
- [x] `show_preview`, `notification_sound` honored
- [x] Verified: no console window flashes; Focus Assist behavior noted

**Acceptance:** A real new mail produces a toast with the correct content; clicking opens the mail in the right account; 5 mails at once produce one summary toast.

## M6 — Settings, autostart, reauth UX
- [x] Settings submenu toggles saved to `settings.json`; "Check now"; "Open data folder"
- [x] `autostart.py` (HKCU Run) and the menu toggle
- [x] "Sign in again" flow, one toast per expiry, warning icon state
- [x] First-run flag and welcome toast

**Acceptance:** Settings persist across restarts; autostart works after reboot; revoking access in the Google account page leads to the warning state and a successful re-sign-in.

## M7 — Packaging
- [x] `scripts/make_icons.py` (generate `.ico`), `scripts/build_exe.ps1`
- [x] PyInstaller `--onedir --windowed`, bundled client config, hidden imports
- [x] Optional Inno Setup script
- [x] Measured: idle RAM, startup time

**Acceptance:** The built app runs on a clean Windows machine without Python, signs in, notifies, and idles at <= 80 MB.

## M8 — Hardening and release
- [x] Full review against `docs/SECURITY.md` checklist
- [x] Log audit (no mail content), dependency audit (`pip-audit`), pinned versions
- [ ] 24-hour soak test (memory stays flat)
- [x] README for end users, release checklist completed

**Acceptance:** All items in the release checklist below are ticked.

## Later (not v1)

- `history.list` incremental sync and unread-state refresh (labels removed)
- Snooze / pause notifications
- Per-account nickname editor
- "Notify for mail that arrived while closed" (persist only a last-seen timestamp)
- Chrome profile selection for opening mail
- Code signing, auto-update (would need a network host, so a DECISIONS entry first)

## Release checklist

- [x] `pytest`, `ruff check .`, `pip-audit` clean
- [ ] Manual QA in `docs/TESTING.md` passed on Windows 10 and 11
- [x] No mail content in logs (grep and manual log read)
- [x] `client_config.json` not in Git history
- [ ] Antivirus check of the build (for example VirusTotal)
- [ ] Google Auth Platform: published to production (for daily use) and test users reviewed
