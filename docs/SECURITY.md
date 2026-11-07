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
| Refresh token | Credential Manager (DPAPI-protected) | Until account removed | Yes |
| Account email addresses | `accounts.json` | Until removed | Personal |
| Sender, subject, snippet, IDs | RAM only | Until replaced or app exits | Yes |
| Settings | `settings.json` | Permanent | No |
| Logs | `app.log` (rotating) | Rotated | Must contain no mail content or tokens |
| OAuth Client ID/secret | Bundled in the app | Permanent | Low (not confidential for desktop apps) but keep out of Git |
| Toast text | Windows Action Center | Controlled by Windows | Yes (preview); mitigated by `show_preview` off |

## 3. Network allowlist

`accounts.google.com`, `oauth2.googleapis.com` (token and revoke), `gmail.googleapis.com`. Nothing else: no analytics, crash reporting, update checks, fonts or images.

## 4. OAuth specifics

- Installed-app flow with a **loopback redirect** on a random local port, bound to `localhost` only, open only while a sign-in is in progress (timeout 180 s).
- PKCE and the `state` parameter must be used (the library does this; verify).
- `prompt=select_account consent` so the chooser is shown and a refresh token is returned.
- The app never sees the Google password.
- On account removal: delete the stored token and revoke it (best effort).
- An unverified app shows Google's warning screen. This is expected while the app is not verified.

## 5. Logging rules

- Never log: subjects, sender names/addresses of mails, snippets, message/thread IDs, tokens, client secret, full URLs containing IDs.
- Allowed: counts, durations, error class names, HTTP status codes, account **index** (`account#1`). Account email addresses at DEBUG level only.
- Exceptions: log with `logger.exception` only if the message cannot include mail data; otherwise log the type only.
- Dev scripts (`scripts/dev_*.py`) may print to the console, but must never write mail content to files.

## 6. Threats and mitigations

| Threat | Mitigation |
|---|---|
| Someone else at the PC sees previews on screen or in Action Center | `show_preview` setting; document it |
| Malware running as the same Windows user | Out of scope (it can also read the browser). DPAPI protects tokens at rest from other users. |
| Hijack of the localhost redirect | Random port, short-lived listener, PKCE, `state` |
| Token leakage through logs or crash output | Logging rules above; token only handled in `auth.py` |
| Leaked client secret | Low impact (cannot access users' data alone); keep out of Git; rotate if leaked |
| Revoked or stolen token | Detect `invalid_grant`, show "Sign in again"; user can revoke in their Google account |
| Malicious dependency | Pinned versions, `pip-audit`, minimal dependencies, build from a clean venv |
| Antivirus false positives on PyInstaller builds | `--onedir`, clean venv, optional code signing, VirusTotal check before release |

## 7. Agent checklist before finishing any task

- [ ] No `print(` in `src/` (outside `scripts/`)
- [ ] Search `src/` for logging calls that include `subject`, `snippet`, `sender`, `token`, `secret`
- [ ] No file writes of mail data; `open(..., "w")` only for settings, accounts, logs
- [ ] No new network hosts; no new scopes; no new dependencies without a DECISIONS entry
- [ ] `client_config.json` and `.env` are git-ignored and not referenced in tests
- [ ] Tests use fake data only (no real addresses, no real tokens)
