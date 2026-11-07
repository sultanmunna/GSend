# AGENTS.md

Entry point for every coding agent working on **Gmail Tray Notifier**. Read this first, then the docs named in your prompt.

## What this project is

A small Windows 10/11 tray app that gives Gmail desktop notifications the way the Gmail Android app does.
The user signs in with Google once (browser OAuth), can add several Gmail accounts, and then:

- sees the **3 latest mails** in the tray icon's menu (sender, subject, which account),
- sees the latest mail's sender and subject in the tray icon's **hover tooltip**,
- gets a **Windows toast** for each new mail (subject + short preview + account),
- opens the mail in the browser by clicking a toast or a menu item.

**Everything runs locally on the user's PC. There is no server, no backend and no telemetry.**

## Tech stack

- Python 3.11+ (Windows only), `src/` layout, package `gmail_notifier`
- Tray: `pystray` + `Pillow` (icons drawn at runtime)
- Google: `google-api-python-client`, `google-auth`, `google-auth-oauthlib` (installed-app loopback flow with PKCE)
- Secrets: `keyring` (Windows Credential Manager)
- Toasts: `winotify` (fallback: `windows-toasts`, see DECISIONS D-11)
- Packaging: PyInstaller (`--onedir`, windowed)
- Dev: `pytest`, `ruff`, `pip-audit`

## Hard rules (never break these)

1. **Local only.** No server, cloud database, analytics, crash reporter or update ping. Allowed network hosts: `accounts.google.com`, `oauth2.googleapis.com`, `gmail.googleapis.com`.
2. **One scope:** `https://www.googleapis.com/auth/gmail.readonly`. Never request more. Never call send, modify, trash or delete endpoints.
3. **Mail content stays in memory.** Sender, subject, snippet and message/thread IDs must never be written to disk, logs, crash dumps, temp files or the clipboard.
4. **Tokens:** only the refresh token, only in Windows Credential Manager via `keyring` (service `GmailNotifier`, username = account email). Never in files, env vars, logs or error messages.
5. **Secrets stay out of Git.** `client_config.json` is git-ignored; only `client_config.example.json` is committed.
6. **No windows in v1.** The UI is the tray icon, its menu and toasts. No Tkinter, Qt, web views or GPUI.
7. **Never block the tray thread.** Network and OAuth work run in worker threads. Google API service objects are not thread-safe: create and use each in one thread only.
8. **Budgets:** idle memory <= 80 MB, ~0% CPU between polls, startup < 3 s.
9. **No silent architecture changes.** Changing a dependency, one of these rules, or an architecture decision requires an entry in `docs/DECISIONS.md` and a note in your report.

## Repo layout

Responsibilities and layering rules are in `docs/ARCHITECTURE.md`.

```
src/gmail_notifier/
  __main__.py app.py config.py errors.py models.py settings.py text_utils.py
  formatting.py links.py accounts.py auth.py gmail_client.py state.py poller.py
  tray.py notifier.py autostart.py logging_setup.py
tests/      unit tests (no network, no real Google calls)
scripts/    dev_add_account.py, dev_fetch.py, make_icons.py, build_exe.ps1
docs/       project documentation
```

## Commands (PowerShell)

```
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m gmail_notifier        # run the app
pytest                          # tests
ruff check . ; ruff format .    # lint + format
pip-audit                       # dependency audit
.\scripts\build_exe.ps1         # build the exe (milestone M7)
```

## Conventions

- Type hints everywhere, `from __future__ import annotations`, frozen dataclasses for data.
- Put logic in **pure functions** (formatting, parsing, dedupe) so it is unit-testable; keep OS/UI calls in thin wrappers.
- Use `logging`, never `print`, inside the app. Log events, counts and error types, never mail content or tokens. Account addresses at DEBUG level only.
- Small modules, small functions. Respect the layering rules in `docs/ARCHITECTURE.md`.
- Tests use `pytest`, no real network, a fake Gmail client. New behavior needs tests.
- Windows-specific code lives only in `tray.py`, `notifier.py`, `autostart.py`, `__main__.py` (single instance) and `auth.py` (keyring).

## Definition of done (every task)

- [ ] `pytest` and `ruff check .` pass
- [ ] Acceptance criteria of the milestone in `docs/ROADMAP.md` are met
- [ ] No hard rule is violated; no secrets or mail content in code, logs or tests
- [ ] Docs updated if behavior changed (ROADMAP checkboxes, DECISIONS, PRODUCT, ARCHITECTURE)
- [ ] Manual checks from `docs/TESTING.md` that you cannot run are listed as "needs human"

## How to work

1. Read this file and the docs named in your prompt. Do not read or edit unrelated files.
2. Write a short plan (5 to 10 lines) before coding.
3. Implement one milestone per session. Stay in scope; list extra ideas instead of building them.
4. If a requirement is unclear or conflicts with the docs, state your assumption in the report (or ask) instead of guessing silently.
5. End with a report: **what changed**, **how to verify** (commands and manual steps), **assumptions / open questions**, **follow-ups**.

## Docs map

| File | Read it for |
|---|---|
| `docs/PRODUCT.md` | What we build: goals, UX, exact text formats, settings |
| `docs/ARCHITECTURE.md` | Modules, threads, data flow, algorithms, API calls |
| `docs/SECURITY.md` | Privacy and security rules, threat model |
| `docs/GOOGLE_CLOUD_SETUP.md` | OAuth client setup and `client_config.json` |
| `docs/DECISIONS.md` | Why things are the way they are |
| `docs/ROADMAP.md` | Milestones M0 to M8 with acceptance criteria |
| `docs/TESTING.md` | Unit test strategy and manual QA checklist |
| `docs/AGENT_PROMPTS.md` | Ready-made prompts for each milestone |
