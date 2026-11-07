# PRODUCT.md

Working name: **Gmail Tray Notifier**. Platform: **Windows 10 (1809+) and Windows 11**.

## 1. Problem

On Android, the Gmail app pushes a notification the moment mail arrives. On Windows there is no Gmail app. The Gmail website can notify only while its tab is open and awake, so notifications are unreliable.

## 2. Vision

A tiny always-on tray app that makes Gmail on Windows behave like Gmail on the phone: new mail, toast, click, mail opens. Sign-in takes a few clicks, nothing leaves the PC except normal calls to Google, and memory use is very small.

## 3. Goals (v1)

1. Sign in with Google in a few clicks (browser OAuth). No passwords. End users never touch Google Cloud.
2. Support **multiple Gmail accounts** and always show which account received a mail.
3. Tray menu with the **3 latest mails**; hover tooltip with the latest mail's sender and subject.
4. Windows **toast** per new mail: subject, short preview, account.
5. Clicking a toast or menu item opens the mail in the default browser, in the right account.
6. **100% local and private**: no server, no telemetry, mail content only in RAM.
7. Light: idle RAM <= 80 MB, near-zero CPU.

## 4. Non-goals (v1)

- No inbox window; no reading, composing or replying (no GPUI, Tkinter, Qt, web view).
- No mark-as-read, archive or delete (read-only scope).
- No Outlook/IMAP/other providers. No macOS/Linux.
- No push (Pub/Sub) and no server of any kind.
- No nickname editor. A `label` field in `accounts.json` is supported but edited by hand.

## 5. User flows

**First run (no accounts).** App starts, tray icon appears, the browser opens Google sign-in automatically (once, only if `first_run_done` is false). The user picks an account and clicks Allow, sees "You can close this tab", and a toast confirms: "Signed in as x@gmail.com. You'll get notifications for new mail." Start-with-Windows is enabled (default).

**Add another account.** Right-click tray, Accounts, Add account. The Google account chooser is always shown. After Allow, the account appears in the menu. Adding an existing account just refreshes its token.

**New mail.** The poller detects it, a toast appears, and clicking it opens `https://mail.google.com/mail/?authuser=<email>#all/<threadId>`. Menu and tooltip update, and the icon shows the unread dot.

**Remove account.** Accounts, the account, Remove. The token is deleted from Credential Manager (and revoked best-effort), and the account disappears from the list and from memory.

**Sign-in expired or revoked.** The account shows "Sign in again" with a warning mark in the menu, one toast is shown, and polling for that account pauses. Clicking the item re-runs sign-in.

**No internet.** Nothing visible. The app retries with backoff and recovers by itself.

## 6. UI specification

### 6.1 Tray icon

- Envelope icon drawn with Pillow at runtime (16/32 px). No binary assets needed at runtime.
- States: `idle`, `unread` (small dot), `warning` (an account needs attention; highest priority).
- **Left click** = default action: open the latest mail; if none, open the Gmail inbox of the first account; if there is no account, start Add account.
- **Right click** = menu.

### 6.2 Menu

```
● John Smith: Meeting moved to 3pm          2m · you
○ Amazon: Your order has shipped           12m · work
○ Bank: New statement                          1h
──────────────────────────────
Open Gmail                  (one account: opens inbox; several: submenu per account)
Check now
──────────────────────────────
Accounts ▸  you@gmail.com ▸ Remove
            work@gmail.com   ⚠ Sign in again
            Add account…
Settings ▸  ✓ Show message preview
            ✓ Primary tab only
            ✓ Start with Windows
            Open data folder
──────────────────────────────
Quit
```

- "●" marks unread mails (as known to the app); "○" marks read mails. The two glyphs
  have the same width in Segoe UI, so senders stay aligned (D-16).
- Each line ends with a tab; Win32 renders the text after it right-aligned (the
  accelerator column): the mail's age — `now`, `5m`, `3h`, `2d` — and, when shown,
  the account (D-16).
- Mail items open that mail in the browser and mark it locally as acknowledged.
- Empty state: a disabled item "No recent mail".
- No accounts: first item is "Add account…" and the tooltip says to add one.

### 6.3 Tooltip (hover)

Windows limits the tooltip to **127 characters** including the newline, so it shows only the latest mail:

```
Line 1: {sender}{ · account}
Line 2: {subject}
```

If too long, truncate the subject first, then the sender. Priority of what to show: no account > account needs sign-in > latest mail.

- No account: `Gmail Notifier: no account. Right-click to add one.`
- Needs sign-in: `Gmail Notifier: sign-in needed. Right-click to fix.`
- No mail: `Gmail Notifier: no recent mail`

### 6.4 Toast (new mail)

```
Title : {subject}                    (<= 70 chars)
Line 1: {sender}{ · account}
Line 2+: {preview}                   (<= 180 chars; omitted if show_preview is off)
```

- Clicking the toast opens the mail. An optional "Open" button does the same.
- Sound follows `notification_sound`.
- If more than `max_toasts_per_poll` new unread mails arrive for one account in a single poll, show **one summary toast** instead: title `{n} new mails`, body `{sender1}, {sender2}, {sender3} and {k} more` plus the account. Clicking it opens that account's inbox.

### 6.5 Text rules (used by menu, tooltip and toast)

- **Sender:** display name if present, else the email address. Decode RFC 2047 encoded-words (non-ASCII names such as Bangla are common). Strip surrounding quotes.
- **Subject:** decoded; empty becomes `(no subject)`; whitespace collapsed.
- **Preview (snippet):** HTML-unescape (Gmail snippets contain entities like `&#39;`), remove invisible padding characters (U+200B, U+200C, U+200D, U+034F, U+00AD, U+FEFF), collapse whitespace, truncate at a word boundary.
- **Truncation** adds `…` (counts as 1 character). Limits: menu line 64, tooltip 127 total, toast title 70, toast preview 180.
- **Account display** (`show_account`): `auto` shows it only when 2 or more accounts exist; `always`; `never`. It uses the account `label` if set, else the local part of the email (before the `@`) (D-16).

## 7. Settings

Stored in `%APPDATA%\GmailNotifier\settings.json`. Invalid values are clamped or reset to defaults; a corrupt file never crashes the app.

| Key | Default | Notes |
|---|---|---|
| `poll_interval_seconds` | 45 | min 20, max 600 |
| `only_primary` | true | uses `category:primary` |
| `show_preview` | true | off hides the snippet only (sender and subject stay) |
| `show_account` | `"auto"` | `auto` / `always` / `never` |
| `notification_sound` | true | |
| `max_toasts_per_poll` | 3 | more than this becomes a summary toast |
| `start_with_windows` | true | applied after the first account is added; toggle in the menu |
| `first_run_done` | false | set after the first sign-in attempt |

## 8. Non-functional requirements

- Windows 10 1809+ / Windows 11, Python 3.11+.
- Idle RAM <= 80 MB; CPU ~0% between polls; startup < 3 s; one poll cycle typically < 2 s per account.
- New mail appears within `poll_interval_seconds` + 5 s.
- Resilient: offline, sleep/resume and API errors never crash the app.
- Privacy: see `docs/SECURITY.md`.

## 9. Known limitations (documented, accepted for v1)

- Not instant: notification delay is up to one poll interval.
- Windows 11 may hide new tray icons in the overflow; the user pins it once.
- The tooltip shows only the latest mail (127-character limit).
- The unread dot can lag if mail is read on another device.
- Mail that arrived while the app was closed is not notified (baseline at start).
- Google shows an "unverified app" warning; Testing mode allows 100 test users and tokens expire after 7 days.
- Toast previews remain in the Windows Action Center (use `show_preview` off on shared PCs).
- Mail opens in the default browser; which Chrome profile is used is up to the browser.

## 10. v1 is done when

- A new user can install, sign in and receive a toast in under 2 minutes.
- Two accounts work side by side and every mail shows its account.
- Nothing is written to disk except `settings.json`, `accounts.json`, rotating logs without mail content, and the refresh tokens in Credential Manager.
- The app idles at <= 80 MB and survives sleep, offline and revoked-token cases.
