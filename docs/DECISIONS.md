# DECISIONS.md

Architecture decision log. Add a new entry (next number) for any change to a decision, dependency or hard rule. Format: Decision, Why, Consequences.

## D-01 Python with pystray
- **Decision:** Python 3.11+, `pystray` for the tray.
- **Why:** Fastest path to a working app; the hard parts are OAuth and mail logic, not the UI. Rust/C# are lighter but slower to build.
- **Consequences:** ~40 to 80 MB RAM. Logic is kept pure and modular so a port to Rust/C# stays possible.

## D-02 OAuth installed-app loopback flow with PKCE, no server
- **Decision:** `InstalledAppFlow.run_local_server` on `localhost` with a random port.
- **Why:** Standard for desktop apps, one-click experience (Chrome account chooser), no developer-run server.
- **Consequences:** The developer owns one Google Cloud project/Client ID. Users see Google's unverified-app warning.

## D-03 `gmail.readonly` only
- **Decision:** One scope, read-only.
- **Why:** Enough for sender, subject, snippet and labels. Least privilege.
- **Consequences:** Restricted scope, so public distribution needs Google verification. No mark-as-read or delete in v1.

## D-04 Poll `messages.list` every ~45 s
- **Decision:** Polling (`messages.list` + `messages.get` metadata).
- **Why:** Fully local. Pub/Sub `watch()` needs a Cloud topic and is not local. IMAP IDLE needs app passwords (clunky setup). `history.list` is a later optimization.
- **Consequences:** Delay up to one interval. Cheap in quota.

## D-05 Only the refresh token goes into keyring
- **Decision:** Store the refresh token (not the access token or full credentials JSON) in Windows Credential Manager.
- **Why:** Smaller (Credential Manager has a size limit), and access tokens are short-lived.
- **Consequences:** Credentials are rebuilt from the refresh token plus the client config on each start.

## D-06 Mail data is memory-only
- **Decision:** Never persist mail content or IDs.
- **Why:** Privacy promise.
- **Consequences:** After restart the app re-baselines; mail that arrived while closed is not notified (D-09).

## D-07 Toast click opens the browser; no inbox window
- **Decision:** Open `https://mail.google.com/mail/?authuser=<email>#all/<threadId>` in the default browser. No GPUI or other inbox UI.
- **Why:** Gmail's web UI is already a full, signed-in client. A custom inbox means rendering HTML mail, attachments and more, and heavier memory.
- **Consequences:** If the browser is not signed in to that account, Google shows its sign-in page first.

## D-08 Tray menu is the only UI
- **Decision:** No windows in v1; sign-in happens in the browser.
- **Why:** Lowest memory and complexity.
- **Consequences:** No nickname editor; `label` in `accounts.json` is edited by hand.

## D-09 Baseline at start and a `received_at` cutoff
- **Decision:** The first poll per account never toasts; later toasts require unread, unseen ID and `received_at > cutoff` (cutoff from Google's `internalDate`, not the PC clock).
- **Why:** Avoids a burst of old-mail toasts at startup and toasts for old mails that re-enter the top 10 after deletions.
- **Consequences:** Mail received while the app was closed is not notified.

## D-10 INBOX + `category:primary` by default
- **Decision:** Poll INBOX filtered to the Primary tab (setting `only_primary`).
- **Why:** Matches what the Gmail phone app notifies by default.
- **Consequences:** Promotions/Social mails are ignored unless the user turns the setting off.

## D-11 `winotify` for toasts, fallback `windows-toasts`
- **Decision:** Use `winotify` with a launch URL for click-to-open.
- **Why:** Simple, no packaging needed for toasts.
- **Consequences:** Verify on a real machine: click-to-open, no console flash, multi-line body. If `winotify` is not good enough, switch to `windows-toasts` and record it here.

## D-12 PyInstaller `--onedir`
- **Decision:** Ship a folder (optionally wrapped in an Inno Setup installer).
- **Why:** Faster startup and fewer antivirus false positives than `--onefile`.
- **Consequences:** Distribution is a folder or installer, not a single exe.

## D-13 Client config bundled in the app
- **Decision:** Embed `client_config.json` at build time (not committed).
- **Why:** Users should not need to create a Cloud project; desktop client secrets are not truly confidential.
- **Consequences:** Rotate the client if the file ever leaks publicly.

## D-14 Custom loopback wait in `auth.py` instead of `run_local_server`
- **Decision:** `_run_local_sign_in` reimplements the wait loop of `InstalledAppFlow.run_local_server` (bind, authorization URL, browser open, wait, `fetch_token`), reusing the library's flow API and — when importable — its hardened `_ExclusiveWSGIServer`.
- **Why:** google-auth-oauthlib 1.5.0 ends `run_local_server` on the first aborted connection: `handle_request` returns without a redirect, `last_request_uri` is `None`, and the flow raises `WSGITimeoutError` — an `AttributeError` subclass — then closes the server, so the browser's real redirect is refused. Browsers routinely open and abandon a first connection (preconnect, aborted `::1` attempt), so real sign-ins failed with "localhost refused to connect" plus a logged `AttributeError`.
- **Consequences:** `auth.py` imports private names from `google_auth_oauthlib.flow` behind a guarded import with a plain-`WSGIServer` fallback; the deadline and `AuthCancelled` are handled by our loop instead of `timeout_seconds`.

## D-15 `google_auth_httplib2.AuthorizedHttp` instead of `Credentials.authorize`
- **Decision:** Build the Gmail API http object as `AuthorizedHttp(credentials, httplib2.Http(timeout=...))` from the `google-auth-httplib2` package (declared explicitly in `pyproject.toml`).
- **Why:** google-auth 2.62 removed the deprecated `Credentials.authorize()` and the whole `google.auth.transport.httplib2` module; the first real sign-in crashed in `auth._profile_email` with `AttributeError`, and `gmail_client._build_service` had the same latent bug. `google-auth-httplib2` is the supported wrapper (googleapiclient itself uses it).
- **Consequences:** The socket timeout still comes from the wrapped `httplib2.Http` (AuthorizedHttp does not take one); refreshes still raise `google.auth.exceptions.RefreshError`, which `_map_google_errors` maps to `ReauthRequired` as before.

## D-16 Menu line layout: tab column, hollow read marker, short account names
- **Decision:** Menu lines are `● /○ sender: subject\t{age} · {account}` within 64 characters (previously one 80-character line with `● `/two spaces and the full email). `account_display` falls back to the local part of the address when no label is set.
- **Why:** The 80-character line rendered as a very wide menu with sender, subject, ellipsis and full email run together at one visual weight. Win32 renders text after `\t` right-aligned (the accelerator column), which separates the volatile parts cleanly without owner-drawing. `●`/`○` have equal widths in Segoe UI, so senders align, which two spaces did not. Ages (`now`, `5m`, `3h`, `2d`, from `Mail.received_at`) and short account names cut most of the noise and the forced truncation.
- **Consequences:** PRODUCT.md sections 6.2 and 6.5 updated; toasts and the tooltip show the short account name too (same `account_display`). Needs human: confirm the tab column renders right-aligned in the themed Windows 10/11 menu.

## D-17 Security hardening: redacting log formatter, keyring backend guard, `bandit`
- **Decision:** (1) All log handlers format through `security_logging.RedactingFormatter`, which scrubs registered secret values (refresh tokens and client secret, registered by `auth.py` as they enter memory) and OAuth-shaped patterns from messages and tracebacks. (2) `auth.py` fails closed with `KeyringBackendError` unless the active `keyring` backend is Windows Credential Manager (or a chain containing it). (3) `bandit` joins the dev tooling; the one finding (`B310` on `urlopen`) is resolved by an explicit https scheme check in `_revoke_token` plus a `# nosec B310`.
- **Why:** The section 5 logging rules relied on call-site discipline; tokens are knowable strings, so they can be made structurally unleakable. `keyring` silently picks a fallback backend when Credential Manager is unavailable, which could put refresh tokens in a plain file. Static scanning catches what review misses, same role as `ruff` for style.
- **Consequences:** Mail content still relies on the section 5 call-site rules (it cannot be enumerated), and the registry is capped at 64 values. On a machine without Credential Manager, sign-in and polling refuse to run instead of degrading silently. `bandit>=1.7` added to `[dev]`; SECURITY.md sections 2, 4, 5, 6 and 7 updated.

## D-18 Toast boundary: PowerShell/XML escaping for winotify content
- **Decision:** `WinotifyBackend.show()` passes every title, message and launch URL through `text_utils.escape_winotify` before handing them to winotify 1.1. The escape backtick-quotes `` ` ``, `$` and `"` (making `$(...)` subexpressions, `$var` expansions, `"$Toast.Tag"` breakouts and line-start `"@` here-string terminators impossible) and splices `]]>` as `]]]]><![CDATA[>` so toast XML (e.g. protocol actions) cannot be injected. Verified against the installed winotify 1.1.0 source (`__init__.py`, `TEMPLATE`, `_run_ps`): the library does no escaping of its own. `tests/test_toast_injection.py` drives the real backend with a fake process runner over the hostile corpus.
- **Why:** winotify 1.1 embeds title/message/launch by `str.format` into a PowerShell script whose toast XML lives in an *expandable* here-string and CDATA sections. Raw mail content in that script is remote-ish code execution: a subject like `$(calc)` runs when the toast shows, and `]]>` allows attacker toast buttons with arbitrary protocol arguments. Escaping at our boundary keeps winotify (D-11) without shipping an executable toast path.
- **Consequences:** Toasts display true content (backtick escapes are what PowerShell renders literally). A future winotify upgrade that escapes internally makes our layer redundant but harmless. If winotify is ever replaced (e.g. windows-toasts/WinRT), the escape belongs at whatever boundary generates code.

## D-19 Gmail services use the bundled discovery document (`static_discovery=True`)
- **Decision:** `_build_service` and `_profile_email` call `build(..., static_discovery=True)`. Startup no longer fetches the discovery document from `https://www.googleapis.com/discovery/v1/apis/gmail/v1/rest`; the document bundled in `google-api-python-client` is used instead, and its `rootUrl` for gmail v1 is exactly `https://gmail.googleapis.com/`.
- **Why:** docs/SECURITY.md section 3 allows `accounts.google.com`, `oauth2.googleapis.com` and `gmail.googleapis.com` — but the discovery fetch contacted a fourth host (`www.googleapis.com`). Bundling the document removes that contact, matches the documented allowlist exactly, and slightly speeds startup.
- **Consequences:** Discovery content is pinned to the installed library version; a Google-side discovery change applies only after a dependency upgrade (the same trust model as the code itself). Tests assert both build sites pass `static_discovery=True`.

## D-20 Bidi control characters are stripped from decoded headers and snippets
- **Decision:** `text_utils` removes the directional formatting characters (bidi overrides U+202A-U+202E, isolates U+2066-U+2069, LRM/RLM U+200E/U+200F) in `decode_header_value` and `clean_snippet`, next to the existing invisible-padding cleanup.
- **Why:** Senders, subjects and snippets are attacker-controlled; a directional override can visually reorder tray menu, tooltip and toast text so a spoofed name reads differently from its bytes (classic price/name-swap trick, "PayPa\u202el Support"). Rendering safely matters more than fidelity for invisible, semantics-only characters.
- **Consequences:** A mail whose sender genuinely uses an RTL override renders without direction control (the RTL glyphs themselves still display). Existing truncation limits are unchanged.

## D-21 OAuth client-config URIs are validated; the credential is pinned to Google's token endpoint
- **Decision:** `auth._validate_installed_config` accepts `client_config.json` only when `auth_uri` is under `https://accounts.google.com/` and `token_uri` is exactly `https://oauth2.googleapis.com/token`; `credentials_for` builds the credential with `config.GOOGLE_TOKEN_URL` regardless of the file's `token_uri` (SECURITY_REPORT SEC-05).
- **Why:** `client_config.json` is a local, user-editable file that used to be trusted blindly: a swapped config could route the consent page or the token exchange (and with it the refresh token) to a non-Google host. Failing loudly (`ConfigError`) beats silently trusting the file.
- **Consequences:** A config with a non-canonical but Google-owned token URI (none are known) would be refused; the browser flow still uses the file's `auth_uri` after the prefix check.
