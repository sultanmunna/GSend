# TESTING.md

## 1. Strategy

- **Unit tests (pytest):** fast, offline, no real Google calls, no real tokens or addresses.
- **Pure logic first:** parsing, formatting, dedupe/cutoff, backoff and settings are pure and heavily tested.
- **Fakes, not mocks everywhere:** a `FakeGmailClient` (scripted responses and errors) drives the poller tests; an in-memory keyring backend drives auth tests.
- **Manual QA** for everything that touches Windows UI (tray, toasts, autostart) and real Google sign-in.

## 2. Unit test plan

| Area | Cases |
|---|---|
| `text_utils.decode_header_value` | plain ASCII, `=?UTF-8?B?...?=`, `=?UTF-8?Q?...?=`, mixed encodings, Bangla/Arabic/CJK, broken encoding (no crash) |
| `text_utils.parse_sender` | `"Name" <a@b.c>`, no name, quoted commas, empty header, only address |
| `text_utils.clean_snippet` | entities (`&#39;`, `&amp;`), zero-width padding, long whitespace, empty |
| `text_utils.truncate` | exact limit, over limit, word boundary, limit smaller than ellipsis |
| `settings` | defaults, clamping (`poll_interval_seconds`), unknown keys ignored, corrupt file, atomic write |
| `accounts` | add, duplicate add, remove, corrupt file, **no token ever in the file** |
| `auth` (mocked) | refresh token stored under the right key, missing refresh token raises, remove deletes and revoke failure is ignored |
| `gmail_client` parser | metadata fixtures, missing Subject, UNREAD label, `internalDate` to UTC |
| error mapping | `RefreshError` to `ReauthRequired`, 429/5xx/network to `TransientError`, 403 to `GmailError` |
| `poller` | baseline is silent; new unread mail emits once; read mail does not toast; old mail re-entering top 10 does not toast; clock skew (use `received_at` only); burst cap; backoff growth and reset; reauth pauses account; removal mid-loop; `stop()` is prompt; `wake()` triggers a poll |
| `state` | merged latest 3 across accounts sorted by `received_at`; unread/status queries; subscriptions fire |
| `formatting` | tooltip never exceeds 127 chars (property-style loop over long inputs); truncation order; account shown only per `show_account` rule; `show_preview` off; empty and no-account states; summary toast text |
| **privacy canary** (`test_privacy_canary.py`) | canary-marked fake mails through the full pipeline (parse → poller → notifier → tray) with forced transient/malformed/unexpected/reauth errors; scans log records, log files, settings/accounts files, the system temp dir and exception text — zero matches required; fake secrets never reach a persistent sink even from a deliberately bad logging call |
| **toast injection** (`test_toast_injection.py`) | real `WinotifyBackend` with a fake process runner (monkeypatched `winotify._run_ps`) over the hostile corpus: `$(...)`, backticks, `"`, line-start `"@`, `]]>`, XML action injection; asserts the generated PowerShell script is inert and content appears only in escaped/spliced form |
| **links tamper** (`test_links.py`) | `../`, `javascript:`, spaces, unicode, empty and non-hex ids raise `ValueError`; malformed emails rejected; notifier keeps the toast but drops the click target |
| **memory soak** (`test_memory_soak.py`) | 50,000 poller cycles with a fake client; exactly one toast (mid-soak arrival); tracemalloc heap growth < 512 KiB |
| **oversized JSON** (`test_settings.py`, `test_accounts.py`) | files larger than 1 MiB are backed up as `.bad` and replaced with defaults, never read fully into memory |

## 3. Manual QA checklist (Windows 10 and 11)

Mark each: pass / fail / n.a. Record the Windows version and app version.

| ID | Scenario | Expected |
|---|---|---|
| T-01 | First run with no accounts | Tray icon appears, browser opens sign-in once, after Allow a welcome toast shows |
| T-02 | Sign in with an account already logged into Chrome | Account chooser lists it; one click finishes |
| T-03 | Add a second account | Chooser shown again; both accounts in the menu |
| T-04 | Send a mail to account 1 | Toast within the poll interval + 5 s; title is the subject; account shown (2 accounts) |
| T-05 | Click the toast | Mail opens in the right account |
| T-06 | Right-click the tray icon | Last 3 mails with unread dot and account; clicking one opens it |
| T-07 | Hover the tray icon | Sender and subject, one mail, within 127 chars |
| T-08 | Left-click the tray icon | Opens the latest mail (or inbox) |
| T-09 | Non-ASCII sender/subject (Bangla, emoji) | Displayed correctly in menu, tooltip, toast |
| T-10 | Burst: send 5 mails quickly | One summary toast, no flood |
| T-11 | Turn off "Show message preview" | Toast has no preview; subject and sender remain |
| T-12 | Disconnect internet for 5 min, reconnect | No errors shown; new mail toasts again after reconnect |
| T-13 | Sleep and resume the PC | Polling continues; mails received during sleep are notified |
| T-14 | Revoke access in the Google account page | Warning state, one toast, "Sign in again" works |
| T-15 | Remove an account | Gone from menu; token gone from Credential Manager; no more toasts for it |
| T-16 | Restart Windows with autostart on | App starts, no browser pops up, tray icon present |
| T-17 | Windows Focus Assist / Do Not Disturb on | No toast shown, tray menu still updates (note behavior) |
| T-18 | Start the app twice | Second instance exits silently |
| T-19 | Quit from the menu | Process ends; no leftover python/exe in Task Manager |
| T-20 | Corrupt `settings.json` by hand | App starts with defaults |
| T-21 | Idle 10 minutes | RAM <= 80 MB, CPU ~0% (Task Manager, Details tab) |
| T-22 | 24-hour soak | RAM stays flat (no growth trend) |
| T-23 | Log review | `app.log` contains no subjects, senders, snippets, tokens |
| T-24 | Built exe on a clean machine without Python | Everything above works |
| T-25 | High-DPI / 150% scaling | Tray icon crisp, tooltip readable |

## 4. Privacy test

After a session with real mail: search `%LOCALAPPDATA%\GmailNotifier` and `%APPDATA%\GmailNotifier` for a known subject line and sender name. There must be **zero** matches. Check Credential Manager contains only refresh tokens for GmailNotifier.
