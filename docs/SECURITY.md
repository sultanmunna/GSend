# SECURITY.md

Privacy is the product's main promise: **your mail never leaves your PC except in normal calls between your PC and Google.**

## 1. Principles

1. No server and no third party. The developer cannot see anyone's mail or tokens.
2. Least privilege: `gmail.readonly` only.
3. Mail content is in RAM only and lives only as long as needed.
4. Secrets are stored with the OS (Windows Credential Manager), never in plain files.
5. Assume logs and bug reports will be shared publicly: they must contain nothing private.

## 2. Data inventory

| Data | Stored where | How long | Sensitive |
|---|---|---|---|
| Refresh token | Credential Manager (DPAPI-protected); only stored after the keyring backend guard confirms it (D-17) | Until account removed | Yes |
| Account email addresses | `accounts.json` | Until removed | Personal |
| Sender, subject, snippet, IDs | RAM only | Until replaced or app exits | Yes |
| Settings | `settings.json` | Permanent | No |
| Logs | `app.log` (rotating) | Rotated | Must contain no mail content or tokens |
| OAuth Client ID/secret | Bundled in the app | Permanent | Low (not confidential for desktop apps) but keep out of Git |
| Toast text | Windows Action Center | Controlled by Windows | Yes (preview); mitigated by `show_preview` off |

## 3. Network allowlist

`accounts.google.com`, `oauth2.googleapis.com` (token and revoke), `gmail.googleapis.com`. Nothing else: no analytics, crash reporting, update checks, fonts or images. Gmail services are built with the **bundled** discovery document (`static_discovery=True`, D-19), so no discovery fetch contacts `www.googleapis.com`; `client_config.json` URIs are validated against these endpoints and the built credential is pinned to the Google token endpoint (D-21, SECURITY_REPORT SEC-05).

## 4. OAuth specifics

- Installed-app flow with a **loopback redirect** on a random local port, bound to `localhost` only, open only while a sign-in is in progress (timeout 180 s). The token exchange itself carries a socket timeout (SEC-06).
- **Keyring backend guard** (D-17): `keyring` silently picks a backend; `auth.py` refuses to store or read tokens unless the active backend is Windows Credential Manager (or a chain containing it). No silent plaintext fallback.
- PKCE and the `state` parameter must be used (the library does this; verify).
- `prompt=select_account consent` so the chooser is shown and a refresh token is returned.
- The profile email returned by `getProfile` is stripped, lower-cased and shape-checked before it becomes the keyring key or the `accounts.json` identity (SEC-03).
- The app never sees the Google password.
- On account removal: delete the stored token and revoke it (best effort).
- An unverified app shows Google's warning screen. This is expected while the app is not verified.

## 5. Logging rules

- Never log: subjects, sender names/addresses of mails, snippets, message/thread IDs, tokens, client secret, full URLs containing IDs.
- Allowed: counts, durations, error class names, HTTP status codes, account **index** (`account#1`). Account email addresses at DEBUG level only.
- Exceptions: log with `logger.exception` only if the message cannot include mail data; otherwise log the type only.
- Dev scripts (`scripts/dev_*.py`) may print to the console, but must never write mail content to files.
- **Last-resort layer (D-17):** every log handler formats through `RedactingFormatter` (`security_logging.py`): registered secret values — refresh tokens and the client secret, registered by `auth.py` as they enter memory — and OAuth-shaped patterns (`GOCSPX-…`, `ya29.…`, `1//…`, `code=`/`access_token=` query values) are replaced with `[REDACTED]` in messages and tracebacks. A future call-site mistake can therefore no longer leak a token. Mail content cannot be enumerated this way: the call-site rules above still apply to it.

## 6. Threats and mitigations

| Threat | Mitigation |
|---|---|
| Someone else at the PC sees previews on screen or in Action Center | `show_preview` setting; document it |
| Malware running as the same Windows user | Out of scope (it can also read the browser). DPAPI protects tokens at rest from other users. |
| Hijack of the localhost redirect | Random port, short-lived listener, PKCE, `state` |
| Token leakage through logs or crash output | Logging rules above; token only handled in `auth.py`; any leak is scrubbed by the redacting log formatter (D-17) |
| **Mail content executes code via the toast** (winotify generates a PowerShell script; an expandable here-string would run `$(...)` from a subject, `]]>` would inject toast XML) | Every title/message/launch is PowerShell/CDATA-escaped at the `WinotifyBackend` boundary (`text_utils.escape_winotify`, D-18); regression-tested with a fake process runner over a hostile corpus |
| **Hostile mail text breaks rendering** (bidi overrides spoof reading order, `&` corrupts Win32 menus) | Directional controls stripped on decode/clean (D-20); menu text has `&` doubled in `tray.py`; truncation limits enforced by `formatting.py` |
| **Tampered mail IDs or account values become URLs** | `links.mail_url`/`inbox_url` raise `ValueError` unless the id is hex and the email has address shape; the toast keeps its text but loses the click target (SEC-02) |
| Leaked client secret | Low impact (cannot access users' data alone); keep out of Git; rotate if leaked |
| Revoked or stolen token | Detect `invalid_grant`, show "Sign in again"; user can revoke in their Google account |
| Malicious dependency | Pinned versions (`requirements-lock.txt`, `requirements-build.txt`), `pip-audit`, `bandit -r src`, minimal dependencies, build from a clean venv, weekly dependabot, CI with `permissions: contents: read` and SHA-pinned actions |
| Planted huge local JSON file spikes memory on load | `settings.json`/`accounts.json` refuse files larger than 1 MiB and recover with defaults (SEC-10) |
| Antivirus false positives on PyInstaller builds | `--onedir`, clean venv, optional code signing, VirusTotal check before release |

## 7. Agent checklist before finishing any task

- [ ] No `print(` in `src/` (outside `scripts/`)
- [ ] Search `src/` for logging calls that include `subject`, `snippet`, `sender`, `token`, `secret`
- [ ] New secrets register with `security_logging.register_secret` when they enter memory
- [ ] No file writes of mail data; `open(..., "w")` only for settings, accounts, logs
- [ ] No new network hosts; no new scopes; no new dependencies without a DECISIONS entry
- [ ] `bandit -r src -ll` reports no medium/high findings
- [ ] `client_config.json` and `.env` are git-ignored and not referenced in tests
- [ ] Tests use fake data only (no real addresses, no real tokens)
