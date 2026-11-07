# ARCHITECTURE.md

## 1. Overview

One Python process, no server.

| Thread | Role |
|---|---|
| Main | `pystray` event loop (tray icon, menu). Never blocks. |
| Poller | Every `poll_interval_seconds` loops over accounts, talks to Gmail, updates `state`, calls `notifier`. Owns all Gmail service objects. |
| Auth worker | Short-lived thread started by "Add account" / "Sign in again". Runs the OAuth flow, which blocks until the user finishes in the browser. At most one at a time. |

```
        ┌──────────────────────── Windows PC (everything runs here) ───────────────────────┐
Chrome ◄┤ auth.py (loopback 127.0.0.1)  ◄── tray menu: "Add account"                       │
        │     │ refresh token                                                              │
        │     ▼                                                                            │
        │ Windows Credential Manager (keyring)                                             │
        │                                                                                  │
        │ poller.py ──► gmail_client.py ──HTTPS──► Gmail API (Google)                      │
        │     │                                                                            │
        │     ▼                                                                            │
        │ state.py  (in-memory: latest mails, account status)                              │
        │     ├──► tray.py      (icon, menu, tooltip)                                      │
        │     └──► notifier.py  (toasts) ── click ──► default browser (Gmail URL)          │
        └──────────────────────────────────────────────────────────────────────────────────┘
```

## 2. Modules

| Module | Responsibility |
|---|---|
| `__main__.py` | Entry point. Single-instance mutex, logging setup, calls `app.run()`. |
| `app.py` | Composition root. Creates settings, accounts, state, poller, tray, notifier and wires callbacks. Handles quit. |
| `config.py` | Constants (app name, keyring service, scopes, URLs) and paths (`%APPDATA%`, `%LOCALAPPDATA%`). |
| `errors.py` | `AuthCancelled`, `ReauthRequired`, `TransientError`, `GmailError`, `ConfigError`. |
| `models.py` | Frozen dataclasses: `Mail`, `Account`, `AccountStatus` (OK, NEEDS_REAUTH, ERROR). |
| `settings.py` | `Settings` dataclass, load/save with validation, atomic writes. |
| `text_utils.py` | `decode_header_value`, `parse_sender`, `clean_snippet`, `truncate`. Pure. |
| `formatting.py` | Pure functions that build menu text, tooltip text and toast content from `Mail`/`Settings`. |
| `links.py` | `mail_url(email, thread_id)`, `inbox_url(email)`. |
| `accounts.py` | `AccountStore`: reads/writes `accounts.json` (emails and optional labels only). |
| `auth.py` | Client config loading, OAuth flow, keyring token storage, building credentials, revoking. Windows keyring access lives here. |
| `gmail_client.py` | Thin Gmail API wrapper plus pure parsers from API dicts to `Mail`. Maps errors to `errors.py`. |
| `state.py` | Thread-safe in-memory store, merged "latest N", unread/status queries, change subscriptions. |
| `poller.py` | Polling loop, per-account bookkeeping (baseline, dedupe, backoff), emits new-mail events. |
| `tray.py` | pystray icon, dynamic menu, tooltip, icon states. No business logic. |
| `notifier.py` | Sends toasts, wires click-to-open. |
| `autostart.py` | Start-with-Windows via `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. |
| `logging_setup.py` | Rotating file log, no content logging. |

## 3. Layering rules

```
config, errors, models, text_utils, links           leaf modules (no internal imports except config/models)
settings                                            -> config
formatting                                          -> models, settings, text_utils
accounts, auth, gmail_client                        -> config, errors, models, text_utils
state                                               -> models
poller                                              -> gmail_client (via Protocol), auth, accounts, state, settings, errors
tray, notifier                                      -> formatting, state, links, settings   (NEVER poller/auth)
app                                                 -> everything (wiring only)
__main__                                            -> app
```

`tray.py` triggers Add account, Remove, Check now, Quit through **callbacks passed in by `app.py`**.

## 4. Data model

```python
@dataclass(frozen=True)
class Mail:
    account: str  # receiving Gmail address
    id: str
    thread_id: str
    sender_name: str  # decoded display name, or the address if no name
    sender_email: str
    subject: str  # decoded, "(no subject)" if empty
    snippet: str  # cleaned preview
    received_at: datetime  # from internalDate (UTC)
    unread: bool


@dataclass(frozen=True)
class Account:
    email: str
    label: str | None
    status: AccountStatus  # OK | NEEDS_REAUTH | ERROR
```

## 5. Storage

| What | Where | Notes |
|---|---|---|
| Refresh token | Windows Credential Manager via `keyring`, service `GSend`, username = email | Only the refresh token. |
| Account list | `%APPDATA%\GSend\accounts.json` | `[{"email": "...", "label": null}]`. No tokens, no mail. |
| Settings | `%APPDATA%\GSend\settings.json` | See PRODUCT.md section 7. |
| Logs | `%LOCALAPPDATA%\GSend\logs\app.log` | Rotating (e.g. 3 x 512 KB). No mail content, no tokens. |
| OAuth client config | Bundled with the app (`client_config.json`) | Not in Git. Load order: env `GSEND_CLIENT_CONFIG` path, then bundled resource (`sys._MEIPASS`), then `./client_config.json` for development. |
| Mail data | **RAM only** | Never persisted. |

All JSON writes are atomic (write temp file in the same folder, then `os.replace`).

## 6. Auth flow

1. Tray "Add account" starts an auth worker thread (ignore the click if one is already running).
2. `InstalledAppFlow.from_client_config(client_config, SCOPES)`.
3. `auth._run_local_sign_in(flow, timeout_seconds)` (DECISIONS D-14): bind the loopback server on `localhost` with a random port, build the authorization URL with `prompt="select_account consent"` and PKCE (the flow autogenerates the verifier), open the browser, then wait in a loop until the redirect arrives or 180 s elapse — an aborted browser connection must not end the wait (the library's `run_local_server` does, which left the redirect refused). Raises `AuthCancelled` on timeout.
4. Build a Gmail service with the returned credentials and call `users().getProfile(userId="me")` to learn `emailAddress`.
5. `keyring.set_password("GSend", email, creds.refresh_token)`. If `refresh_token` is missing, raise an error (do not store `None`).
6. Add the email to `accounts.json` if new; set status OK; wake the poller.
7. Discard the temporary service and credentials.

Credentials for polling are rebuilt from the stored refresh token:

```python
Credentials(
    None,
    refresh_token=rt,
    token_uri="https://oauth2.googleapis.com/token",
    client_id=cid,
    client_secret=csecret,
    scopes=SCOPES,
)
```

Refresh happens automatically on the first request. `RefreshError` becomes `ReauthRequired`.

**Remove account:** delete the keyring entry, remove from `accounts.json`, drop from state, and best-effort revoke the token with a POST to `https://oauth2.googleapis.com/revoke`. Revocation failure must not block removal.

## 7. Polling algorithm

Per account the poller keeps: `seen_ids` (set, bounded to 500, oldest dropped first), `cache` (`dict[id, Mail]`), `baseline_done`, `cutoff` (datetime), `failures`, `next_allowed`.

```
poll_account(acct):
    ids = client.latest_inbox_ids(limit=10, only_primary=settings.only_primary)   # newest first
    missing = [i for i in ids if i not in cache]
    fetched = [client.get_mail(i) for i in missing]                                # metadata only

    if not baseline_done:
        cutoff = max(m.received_at for m in fetched + cached) or now_utc          # use Google's time, not the PC clock
        seen_ids |= set(ids); baseline_done = True
        new = []                                                                   # baseline never toasts
    else:
        new = [m for m in fetched
               if m.id not in seen_ids and m.unread and m.received_at > cutoff]
        seen_ids |= set(missing)

    cache = {i: cache.get(i) or fetched_by_id[i] for i in ids}                     # prune to current top 10
    state.update_mails(acct.email, [cache[i] for i in ids])
    if new: on_new_mails(acct.email, new)                                          # newest first
```

- **Why `seen_ids` and `cutoff`:** if the user deletes newer mails, an old mail can re-enter the top 10. It is fetched as "missing" but must not toast. `seen_ids` and the `received_at > cutoff` check prevent that.
- **Loop:** `stop_event.wait(timeout)` between cycles (never `time.sleep`). `wake()` (Check now, new account) sets a second event to run immediately.
- **Backoff:** on `TransientError`, `failures += 1` and `delay = min(interval * 2**failures, 300)`; reset to 0 on success.
- **Reauth:** on `ReauthRequired`, set status NEEDS_REAUTH, emit one event (toast once), and skip that account until the user signs in again.
- **Cap:** fetch at most 10 new mails per account per poll.
- **Thread safety:** the poller thread creates and uses the Gmail service objects. Auth workers use their own temporary service.

## 8. Gmail API usage

Scope: `gmail.readonly` only. Always pass `fields` to keep responses small, and `num_retries=2`. Build with `build("gmail", "v1", credentials=..., cache_discovery=False)`.

```
users.getProfile(userId="me", fields="emailAddress")

users.messages.list(userId="me", labelIds=["INBOX"], maxResults=10,
                    q="category:primary" (when only_primary), fields="messages(id,threadId)")

users.messages.get(userId="me", id=ID, format="metadata",
                   metadataHeaders=["From", "Subject"],
                   fields="id,threadId,internalDate,labelIds,snippet,payload/headers")
```

- `internalDate` is milliseconds since epoch (string). `unread` = `"UNREAD" in labelIds`.
- Header values can be RFC 2047 encoded (`=?UTF-8?B?...?=`); decode them with `email.header` and parse addresses with `email.utils.parseaddr`.
- Quota is not a concern: about 5 units per list/get against a per-user limit of 250 units per second.

## 9. Error handling

| Condition | Detected as | Behavior |
|---|---|---|
| No internet, DNS, timeout | `OSError`, `TimeoutError`, `httplib2.ServerNotFoundError` | `TransientError`; silent; backoff |
| HTTP 429 / 5xx | `HttpError` status | `TransientError`; backoff |
| Token revoked/expired, `invalid_grant` | `google.auth.exceptions.RefreshError` | `ReauthRequired`; NEEDS_REAUTH; one toast; menu warning |
| No token in keyring | `credentials_for` finds none | `ReauthRequired` |
| 403 (API disabled, scope) / other 4xx | `HttpError` | status ERROR; log type only; menu warning; no toast spam |
| Auth cancelled or timed out | `AuthCancelled` | log; no toast |
| Toast fails | exception in `notifier` | log; never crash the poller |
| Corrupt `settings.json` / `accounts.json` | JSON error | back up as `.bad`, use defaults, log |

No exception may escape the poller loop or kill a thread silently: wrap each account's poll in try/except and log with `logger.exception` (message must not contain mail content).

## 10. UI plumbing

- `state.subscribe(callback)`: called after any change from the changing thread. `app.py` subscribes a function that updates `icon.title` (tooltip), swaps the icon image if the state changed, and calls `icon.update_menu()`.
- Build the pystray menu from a callable (`pystray.Menu(lambda: build_items())`) so it is always current.
- Menu item text and tooltip text come from `formatting.py` only.
- Opening a mail uses `webbrowser.open(url)`; it works from any thread.
- Toast click opens the same URL via the toast library's launch mechanism (no Python callback required while the app is idle). If the library offers only callbacks, keep the callback tiny and thread-safe.
- Verify on a real machine whether pystray's `icon.title` and `update_menu()` calls are safe from the poller thread; if not, marshal them onto the tray thread.

## 11. Packaging

- PyInstaller `--onedir --windowed`, with an icon, `--add-data client_config.json;.`, and hidden imports as needed (`keyring.backends.Windows`, `pystray._win32`).
- Built from a clean virtualenv with pinned dependencies.
- `onedir` is preferred over `onefile`: faster startup and fewer antivirus false positives (DECISIONS D-12). An Inno Setup installer is optional.
- The exe is unsigned unless a certificate is available; expect a SmartScreen "unknown publisher" prompt.

## 12. Performance targets and how to check

- Idle RSS <= 80 MB: check in Task Manager (Details tab) after 10 minutes idle.
- CPU ~0% between polls: no busy loops; use `Event.wait`.
- Startup < 3 s from launch to tray icon visible.
- No memory growth over 24 h: `seen_ids` is bounded; no unbounded lists.
