# AGENT_PROMPTS.md

Copy-paste prompts for coding agents (Claude Code, Codex, Cursor, etc.). Each prompt is self-contained and points the agent to the docs.

## How to use

1. Put `AGENTS.md`, `CLAUDE.md` and `docs/` in your repo and commit them.
2. Use a **fresh agent session per prompt** and a **git branch per milestone** (`m0-scaffold`, `m1-auth`, ...).
3. Run the **Kickoff** prompt first and read the answer. Fix any doc problems it finds.
4. Run **M0 to M8 in order**. After each one: review the diff yourself, run the commands from "Acceptance", do the manual checks, tick the box in `docs/ROADMAP.md`, merge.
5. Anything the agent cannot test (real Google sign-in, tray, toasts) must be tested by you. The report lists what needs a human.
6. Use the utility prompts (review, security audit, bug fix, new feature) whenever needed.

Tip: if an agent drifts from the rules, point it back to "Hard rules" in `AGENTS.md`.

---

## Kickoff (no code)

```
You are joining a new project: GSend (Windows tray app, Python, 100% local, no server).
Read in this order: AGENTS.md, docs/PRODUCT.md, docs/ARCHITECTURE.md, docs/SECURITY.md,
docs/DECISIONS.md, docs/ROADMAP.md, docs/TESTING.md.
Do NOT write code or create files yet.
Reply in under 60 lines with:
1. A 10-line summary of what the app does and its hard rules, in your own words.
2. The module list with a one-line responsibility each.
3. Anything ambiguous, contradictory or missing in the docs, each with a proposed resolution.
4. The top 5 technical risks (for example toast click handling, pystray thread safety) and how you would de-risk each.
```

---

## M0 — Scaffold, models, settings, text utilities

```
Task: Milestone M0 (project scaffold). Follow AGENTS.md: hard rules, conventions, definition of done, report format.
Read: AGENTS.md, docs/ARCHITECTURE.md (sections 2 to 5), docs/PRODUCT.md (sections 6.5 and 7), docs/ROADMAP.md (M0).

Build:
1. pyproject.toml: name gsend, Python >=3.11, src layout, dependencies (pystray, Pillow,
   google-api-python-client, google-auth, google-auth-oauthlib, keyring, winotify), optional dev
   dependencies (pytest, ruff, pyinstaller, pip-audit), ruff and pytest config, script entry "gsend".
2. .gitignore (.venv, build, dist, __pycache__, logs, client_config.json, .env) and
   client_config.example.json with placeholder values in the "installed" format.
3. Package src/gsend/ with EVERY module from the layout in AGENTS.md as a stub that has a
   docstring stating its responsibility. Fully implement only:
   - config.py: APP_NAME, KEYRING_SERVICE="GSend", SCOPES (gmail.readonly only), URL constants,
     paths under %APPDATA% and %LOCALAPPDATA% (create folders lazily).
   - errors.py: AuthCancelled, ReauthRequired, TransientError, GmailError, ConfigError.
   - models.py: Mail, Account, AccountStatus as frozen dataclasses (fields exactly as in ARCHITECTURE section 4).
   - settings.py: Settings dataclass with the defaults and ranges from PRODUCT.md section 7; load/save with
     validation, clamping, unknown keys ignored, corrupt file backed up as .bad and replaced by defaults,
     atomic writes.
   - text_utils.py: decode_header_value (RFC 2047), parse_sender, clean_snippet, truncate, exactly per PRODUCT.md 6.5.
   - logging_setup.py: rotating file log under %LOCALAPPDATA%, console handler only in dev, never logs content.
4. Tests for text_utils (encoded words, Bangla/unicode names, quotes, missing name, invisible characters,
   HTML entities, truncation at word boundary), settings (defaults, clamping, corrupt file, atomic write), models.

Do not implement auth, Gmail access, tray or toasts yet.
Acceptance: pip install -e ".[dev]" works; pytest and ruff check . pass; "python -m gsend" logs a
startup line and exits cleanly.
```

---

## M1 — Auth and accounts

```
Task: Milestone M1 (auth and accounts). Follow AGENTS.md.
Read: AGENTS.md, docs/ARCHITECTURE.md (sections 5, 6, 9), docs/SECURITY.md, docs/GOOGLE_CLOUD_SETUP.md, docs/ROADMAP.md (M1).

Build:
1. auth.py:
   - load_client_config() with the load order from ARCHITECTURE section 5 (env path, bundled resource, ./client_config.json).
   - add_account_interactive(timeout_seconds=180) -> str: the flow in ARCHITECTURE section 6
     (prompt="select_account consent", PKCE, localhost listener, success message). It fetches the email via
     users().getProfile, stores ONLY the refresh token with keyring (service "GSend", username = email),
     and returns the email. Raise AuthCancelled on cancel/timeout and a clear error if no refresh token returned.
   - credentials_for(email) -> google.oauth2.credentials.Credentials built from the stored refresh token and
     client config. Raise ReauthRequired if there is no token.
   - remove_account(email): delete the keyring entry and best-effort revoke (POST to the Google revoke
     endpoint); revoke errors are logged (type only) and ignored.
   - has_token(email) -> bool.
2. accounts.py: AccountStore backed by accounts.json (list of {"email", "label"}), atomic writes, add (no duplicates,
   case-insensitive), remove, list, corrupt-file handling. The file must never contain tokens.
3. scripts/dev_add_account.py: CLI with "add", "list", "remove <email>". Prints emails only.
4. Tests: mock keyring (in-memory backend) and the OAuth flow; test duplicate add, token stored under the right key,
   missing refresh token, removal, revoke failure ignored, accounts.json never contains token strings.

Constraints: the OAuth flow runs only when called (never at import); no GUI; no logging of tokens or secrets.
Acceptance: pytest and ruff pass. Manual (needs human): run "python scripts/dev_add_account.py add", Chrome opens,
after Allow the email is printed, Windows Credential Manager shows the entry, accounts.json has the email and no
token; "remove" cleans both.
```

---

## M2 — Gmail client and parsing

```
Task: Milestone M2 (Gmail client). Follow AGENTS.md.
Read: AGENTS.md, docs/ARCHITECTURE.md (sections 4, 8, 9), docs/PRODUCT.md (6.5), docs/ROADMAP.md (M2).

Build:
1. gmail_client.py:
   - A Protocol "MailSource" with latest_inbox_ids(limit, only_primary) -> list[str] and get_mail(id) -> Mail,
     so the poller can use a fake in tests.
   - class GmailClient(account_email, credentials) implementing it with the exact API calls and `fields` from
     ARCHITECTURE section 8, build(..., cache_discovery=False), num_retries=2.
   - parse_message(account_email, api_dict) -> Mail: pure function. Decode RFC 2047 headers, parse sender with
     text_utils, subject fallback "(no subject)", clean snippet, internalDate (ms) to UTC datetime,
     unread = "UNREAD" in labelIds.
   - Error mapping: RefreshError -> ReauthRequired; 429/5xx/network/timeouts -> TransientError;
     other HttpError -> GmailError. No mail content in exception messages.
2. links.py: mail_url(email, thread_id) -> "https://mail.google.com/mail/?authuser=<url-quoted email>#all/<thread_id>",
   inbox_url(email).
3. scripts/dev_fetch.py: for an account added via M1, print the latest 3 mails (sender, subject, unread flag) to the
   console only. Never write mail data to files.
4. Tests with JSON fixtures: encoded subject and sender (Bangla), missing Subject, no display name, HTML entities in
   snippet, UNREAD vs read, error mapping, URL quoting of "+" in emails.

Acceptance: pytest and ruff pass offline. Manual (needs human): dev_fetch.py prints the 3 latest mails of a real
account with correct names and subjects, including non-ASCII.
```

---

## M3 — State and poller

```
Task: Milestone M3 (state and poller). Follow AGENTS.md.
Read: AGENTS.md, docs/ARCHITECTURE.md (sections 1, 3, 7, 9), docs/PRODUCT.md (sections 5 and 8), docs/TESTING.md (poller and state rows).

Build:
1. state.py: thread-safe AppState per ARCHITECTURE section 10 and this API: set_accounts, update_mails(email, mails),
   set_account_status, latest(n=3) merged across accounts sorted by received_at desc, mark_opened(mail_id) (local
   acknowledgement that clears the unread flag in the display), has_unread(), worst_status(), subscribe(callback).
   Callbacks run outside the lock.
2. poller.py: Poller(client_factory, account_store, state, settings, on_new_mails). Implement EXACTLY the algorithm in
   ARCHITECTURE section 7: baseline without toasts, seen_ids (bounded 500), cache pruned to the current top 10,
   cutoff from Google's internalDate, unread-only new mails, max 10 fetched per poll, exponential backoff
   (min(interval*2**failures, 300)), ReauthRequired -> status NEEDS_REAUTH and one on_reauth_needed callback,
   stop_event.wait loop (no time.sleep), wake() for "Check now", reload_accounts() for add/remove during runtime.
   Every account poll is wrapped in try/except so no exception can kill the thread.
   client_factory(email) -> MailSource is injected; the poller itself must not import googleapiclient.
3. scripts/dev_poll.py: console harness that runs the poller for the real accounts and prints "NEW MAIL for
   account#N" with sender and subject to the console only. It must print nothing at startup.
4. Tests with FakeMailSource covering every rule: silent baseline, single emit, read mail not emitted, old mail
   re-entering top 10 not emitted, clock skew immunity (only received_at used), burst handling, backoff and reset,
   reauth pause and resume, account removed mid-loop, prompt stop(), wake().

Acceptance: pytest and ruff pass. Manual (needs human): with dev_poll.py running, send yourself a mail and see the event
within one interval; disconnect/reconnect the network without crashes; restart shows no event for old mail.
```

---

## M4 — Formatting, tray and app wiring

```
Task: Milestone M4 (formatting, tray, app wiring). Follow AGENTS.md.
Read: AGENTS.md, docs/PRODUCT.md (sections 5 to 7), docs/ARCHITECTURE.md (sections 2, 3, 10), docs/ROADMAP.md (M4).

Build:
1. formatting.py (pure): menu_line(mail, settings, show_account), tooltip(state_snapshot, settings),
   toast_content(mail, settings, show_account) -> dataclass(title, lines), summary_toast(mails, account). Follow the exact
   formats and limits in PRODUCT.md 6.2 to 6.5 (menu 80, tooltip 127 total including newline, toast title 70,
   preview 180). Account is shown per the show_account rule.
2. tray.py: pystray icon, icon images drawn with Pillow (idle, unread dot, warning), dynamic menu built from a callable,
   default left-click action, tooltip via icon.title. It receives callbacks from app.py (add account, remove account,
   open mail, open inbox, check now, quit). No business logic and no imports of poller/auth.
3. app.py: composition root. Creates settings, accounts, state, poller (with GmailClient factory using auth),
   tray and a STUB notifier that only logs "new mail event (count)" without content. Subscribes to state changes
   to refresh tooltip, icon and menu. Add account runs in a single auth worker thread; a second click while one runs
   is ignored. First-run behavior: if no accounts and first_run_done is false, start sign-in automatically once.
4. __main__.py: single-instance guard using a Windows named mutex (ctypes); second instance exits silently.
   Clean shutdown: stop poller, stop icon, join threads with timeouts.
5. Tests for formatting (limits, truncation order, account rule, empty states). Keep tray/app thin so they need no tests
   beyond a smoke test.

Verify and note in the report: whether pystray's icon.title and update_menu() are safe to call from the poller thread
on Windows. If not, marshal them.
Acceptance: pytest and ruff pass. Manual (needs human): tray icon appears; right-click shows the 3 latest mails with
accounts; hover shows sender and subject within 127 chars; adding a second account works; Quit leaves no process behind.
```

---

## M5 — Notifications

```
Task: Milestone M5 (toasts). Follow AGENTS.md.
Read: AGENTS.md, docs/PRODUCT.md (6.4, 6.5, 7), docs/DECISIONS.md (D-07, D-11), docs/ARCHITECTURE.md (section 10).

Build:
1. notifier.py: Notifier(settings, state) with notify_new_mails(account_email, mails) and notify_reauth_needed(account_email).
   Use formatting.toast_content and summary_toast. Use winotify with the mail URL (links.mail_url) as the launch target so
   clicking opens the right mail; fall back to its action button API if needed. Map ToastContent(title, lines) to the
   library (if multi-line body is not supported, join lines with a newline or " - " and record what you chose).
   Honor show_preview and notification_sound. If more than max_toasts_per_poll mails arrive, send one summary toast
   whose click opens inbox_url. Toast failures are logged (type only) and never raise.
2. Wire it in app.py in place of the stub. Mark a mail as opened in state when its menu item is clicked.
3. Tests for the mapping logic with a fake toast backend (no real toasts in tests).

Verify on a real machine (needs human) and write findings in the report: click-to-open works; no console window flashes
(run windowed); app name shown in the toast header; behavior with Focus Assist. If winotify cannot meet these, propose
windows-toasts and add a DECISIONS entry.
Acceptance: pytest and ruff pass. A real new mail produces a toast with the right title, sender, preview and account;
clicking opens the mail; 5 simultaneous mails give one summary toast.
```

---

## M6 — Settings, autostart, reauth UX

```
Task: Milestone M6 (settings menu, autostart, re-sign-in). Follow AGENTS.md.
Read: AGENTS.md, docs/PRODUCT.md (sections 5, 6.2, 7), docs/ROADMAP.md (M6), docs/ARCHITECTURE.md (sections 6, 9).

Build:
1. Settings submenu in tray.py: checkable items for show_preview, only_primary, start_with_windows; "Open data folder"
   (opens %APPDATA%\GSend in Explorer); "Check now" (poller.wake()). Changes are saved atomically and take effect
   immediately (poller reloads settings; only_primary change triggers a re-baseline for that account's cache without toasts).
2. autostart.py: enable/disable/is_enabled via HKCU\Software\Microsoft\Windows\CurrentVersion\Run. When frozen, point to the
   exe; when running from source, use pythonw -m gsend. Apply the default (enabled) after the first account is
   added, once.
3. Re-sign-in UX: account in NEEDS_REAUTH shows a warning item in Accounts; clicking runs the sign-in flow again and
   verifies the same email came back (if a different account was chosen, treat it as a new account and tell the user via
   a toast). One toast per expiry event, not per poll. The tray icon shows the warning state.
4. First-run flag: set first_run_done after the first sign-in attempt (success or cancel). A welcome toast after the first
   successful sign-in.
5. Tests: settings change propagation, autostart with a fake registry wrapper, reauth state transitions.

Acceptance: pytest and ruff pass. Manual (needs human): settings persist after restart; autostart works after reboot
without opening a browser; revoking access at myaccount.google.com leads to the warning state, one toast, and a successful
re-sign-in.
```

---

## M7 — Packaging

```
Task: Milestone M7 (Windows build). Follow AGENTS.md.
Read: AGENTS.md, docs/ARCHITECTURE.md (sections 5, 11, 12), docs/DECISIONS.md (D-12, D-13), docs/SECURITY.md (sections 6 and 7).

Build:
1. scripts/make_icons.py: generate assets/app.ico (multiple sizes) with Pillow, matching the tray icon style.
2. scripts/build_exe.ps1: create a clean venv, install pinned dependencies, run PyInstaller with --onedir --windowed,
   the icon, --add-data client_config.json;. (fail with a clear message if the file is missing), hidden imports for the
   keyring Windows backend and pystray win32 backend, and Windows version info. Output to dist/GSend/.
3. Make sure the frozen app finds client_config.json via sys._MEIPASS and that autostart points to the frozen exe.
4. Optional: installer/GSend.iss for Inno Setup (per-user install, no admin needed, optional start with Windows).
5. A short docs/BUILD.md with the exact steps and the checks below.

Measure and report: idle RAM after 10 minutes (Task Manager, Details), startup time to tray icon, folder size.
Acceptance: the build runs on a clean Windows machine without Python, signs in, shows toasts, and idles at <= 80 MB.
List anything that triggers antivirus or SmartScreen warnings.
```

---

## M8 — Hardening and release

```
Task: Milestone M8 (hardening). Follow AGENTS.md. Do not add features.
Read: ALL docs, especially docs/SECURITY.md (section 7 checklist), docs/TESTING.md, docs/ROADMAP.md (release checklist).

Do:
1. Run the SECURITY.md section 7 checklist against the code with real searches (grep) and report each result.
2. Audit every logging call and every exception message for mail content or tokens. Fix violations.
3. Run pip-audit; pin dependency versions; report findings.
4. Review thread safety (service objects per thread, state locking, shutdown), bounded collections, and timeouts on all
   network and OAuth calls.
5. Add missing tests for any bug you find. Fix bugs with minimal diffs.
6. Write README.md for end users: what it is, install, first sign-in (including the "unverified app" screen with
   screenshots placeholders), privacy statement, settings, troubleshooting, uninstall (remove accounts first).
7. Produce a short "manual QA to run" list from docs/TESTING.md for the human, ordered by risk.

Acceptance: report with a pass/fail line for each release-checklist item you can verify, and a clear list of the ones a
human must verify.
```

---

## Utility prompts

### Code review

```
Review the changes on this branch against main as a strict reviewer. Read AGENTS.md and docs/SECURITY.md first.
Check: hard rules, layering rules (docs/ARCHITECTURE.md section 3), thread safety, error handling table (section 9),
logging of private data, test quality (offline, meaningful assertions), docs consistency.
Output: (1) blocking issues, (2) non-blocking suggestions, (3) missing tests, (4) a verdict. Do not edit files.
```

### Security and privacy audit

```
Perform a security and privacy audit of the whole repo. Read AGENTS.md and docs/SECURITY.md.
Follow the checklist in SECURITY.md section 7 and prove each item with search results.
Also check: any network host outside the allowlist, any scope other than gmail.readonly, any place a token or
client secret could be printed or logged, any file write that could contain mail data, exception messages that
embed mail content, and temp files.
Output a table: item, result, evidence (file:line), fix. Make no changes unless I ask.
```

### Bug fix

```
Bug: <describe what you saw, what you expected, steps to reproduce, Windows version, app version>.
Read AGENTS.md and the docs relevant to the area. First write a failing test that reproduces the bug if it is testable
offline. Then fix it with the smallest change. Do not refactor unrelated code. Report root cause, the fix, the test, and
anything that needs a manual check.
```

### New feature or change

```
Change request: <describe it>.
Read AGENTS.md, docs/PRODUCT.md (goals and non-goals) and docs/DECISIONS.md.
Step 1: tell me if it conflicts with a hard rule, a non-goal or a decision, and what docs would need to change.
Step 2: propose the smallest design and the tests, and wait for my approval before coding.
After approval: update the docs first (PRODUCT/ARCHITECTURE/DECISIONS/ROADMAP), then implement, then report.
```

### Docs sync

```
Compare the code on this branch with docs/PRODUCT.md, docs/ARCHITECTURE.md and docs/DECISIONS.md.
List every place where they disagree. For each, say whether the docs or the code should change and why.
Update the docs where the code is right. Do not change code.
```
