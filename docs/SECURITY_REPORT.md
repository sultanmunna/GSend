# SECURITY_REPORT.md

Security testing and hardening pass, 2026-11-07. Scope: full repository audit against
`docs/SECURITY.md`, `AGENTS.md` hard rules and the ten-phase plan (secrets, static
analysis, privacy canary, OAuth, hostile mail content, URL/process launching,
Windows hardening, robustness/DoS, supply chain). All tests use fake data only.

Baseline before this pass: the working tree contained a completed, uncommitted
hardening change (redacting log formatter, keyring backend guard, bandit — DECISIONS
D-17), verified and committed as `dcc4451` before the audit started.

## Findings

| ID | Severity | Phase | Location | Description | Evidence | Status | Fix commit | Test |
|---|---|---|---|---|---|---|---|---|
| SEC-01 | Critical | 5 | `src/gmail_notifier/notifier.py` (`WinotifyBackend.show`); winotify 1.1.0 `__init__.py` (`TEMPLATE`, `_run_ps`) | Mail-controlled title/message/launch were embedded **unescaped** into a generated PowerShell script whose toast XML lives in an *expandable* here-string (`@"..."@`) with CDATA text fields: a subject containing `$(calc)` is **executed** by PowerShell when the toast shows; a `"` breaks out of `$Toast.Tag = "{tag}"`; a message line starting with `"@` terminates the here-string (arbitrary trailing commands); `]]>` closes a CDATA section and allows toast XML injection, e.g. `<action activationType="protocol" arguments="https://evil.test/phish"/>` | Installed library source read line-by-line; `tests/test_toast_injection.py` drives the real backend with a fake process runner over the hostile corpus and asserts the script is inert; mutation check (removing the `$` escape) makes the tests fail | fixed | `bda179c` | `test_toast_injection.py` |
| SEC-02 | High | 6 | `src/gmail_notifier/links.py` | Mail URLs were built from unvalidated parts: message/thread IDs and the account email went into the URL unchecked. Now the email must have address shape and the ID must match `^[0-9a-fA-F]+$`, else `ValueError`; the notifier keeps the toast but drops the click target, and menu-open logs and skips the browser | Tamper corpus: `../`, `javascript:alert(1)`, `http://evil.test`, spaces, unicode, shell text | fixed | `785b0b7` | `test_links.py`, `test_notifier.py`, `test_app.py` |
| SEC-03 | High | 4 | `src/gmail_notifier/auth.py` (`_profile_email`) | The email returned by `getProfile` was used as keyring key and `accounts.json` identity without normalization or validation; Credential Manager keys are case-sensitive, so a casing change between sign-ins would fork accounts, and unusable values were storable | Code review; keyring semantics | fixed | `adfda75` | `test_auth.py` (`_normalize_profile_email`, sign-in stores under normalized key) |
| SEC-04 | Medium | 4/6 | `gmail_client._build_service`, `auth._profile_email` | Startup fetched the discovery document from `https://www.googleapis.com` — a fourth host outside the documented allowlist (SECURITY section 3) | `build(..., static_discovery=True)` uses the bundled document whose `rootUrl` is exactly `https://gmail.googleapis.com/` (D-19) | fixed | `d464b03` | `test_gmail_client.py` |
| SEC-05 | Medium | 4 | `auth.py` | `client_config.json` URIs were not host-validated: a swapped/edited local config could point the consent page (`auth_uri`) or the token exchange (`token_uri`) at a non-Google host, phishing the user or receiving the refresh token. `auth_uri` must now be under `https://accounts.google.com/`, `token_uri` must be the Google token endpoint, and the built credential is pinned to `config.GOOGLE_TOKEN_URL` (D-21) | Code review | fixed | `4f2b249` | `test_auth.py` |
| SEC-06 | Medium | 4 | `auth.py` (`_run_local_sign_in`) | The OAuth token exchange had **no timeout**: a hung connection to the token endpoint blocked the single-flight auth worker forever (no further sign-ins possible). `flow.fetch_token` now passes the 30 s socket timeout (requests_oauthlib defaults to `timeout=None`) | Library source: `requests_oauthlib.oauth2_session.fetch_token(timeout=None)` | fixed | `02f90c7` | `test_auth.py` (fake loopback server records the timeout kwarg) |
| SEC-07 | Medium | 5 | `src/gmail_notifier/tray.py` | pystray 0.19.5 passes menu text to `InsertMenuItem` unescaped: a single `&` from a sender, subject, account email or hand-edited label hides a character and underlines the next (Win32 accelerator). Mail lines, account entries and "Open Gmail" labels now double `&` | pystray `_win32.py` source read | fixed | `bfa4995` | `test_app.py` |
| SEC-08 | Medium | 5 | `src/gmail_notifier/text_utils.py` | Bidi override/isolate characters (U+202A–202E, U+2066–2069, LRM/RLM) in sender/subject/snippet could visually reorder tray, tooltip and toast text (direction spoofing). Now stripped on decode and clean (D-20) | Unit tests; corpus in the injection suite | fixed | `b9f70e9` | `test_text_utils.py`, `test_toast_injection.py` |
| SEC-09 | Medium | 9 | repository | No CI, no dependabot, no lock file. Added `.github/workflows/security.yml` (pytest, ruff, bandit, pip-audit on Windows 3.11/3.13 + gitleaks over full history; `permissions: contents: read`; actions pinned by commit SHA), `.github/dependabot.yml` (pip + github-actions, weekly) and `requirements-lock.txt` | Repo state | fixed | `67cb838` | workflow itself |
| SEC-10 | Low | 7/8 | `settings.py`, `accounts.py` | Config JSON was read fully into memory with no size bound: a planted multi-gigabyte file spikes memory. Files larger than 1 MiB are now backed up as `.bad` and replaced with defaults | Unit tests with >1 MiB files | fixed | `c318929` | `test_settings.py`, `test_accounts.py` |
| SEC-11 | Low | 1 | `.gitignore` | `.venv-build/` (the clean build venv from `build_exe.ps1`) was not ignored and could be committed | `git check-ignore` | fixed | `c318929` | — |
| SEC-12 | Info | 2 | `auth.py` (`_revoke_token`) | ruff `S310` audit markers missing on the guarded `urlopen`/`Request` (bandit B310 was already annotated in D-17). `# noqa: S310` added next to the existing https scheme check | `ruff check --select S` | fixed | `c318929` | — |
| SEC-13 | Info | 3 | `tests/test_privacy_canary.py` | New automated privacy canary: canary-marked fake mails (subject/sender/snippet/IDs) run through the full pipeline while transient, malformed-API, unexpected and reauth errors are forced; every sink (log records with tracebacks, real log files, settings/accounts files, system temp dir, exception text) is scanned — zero matches required. Fake secrets must not reach any persistent sink even from a deliberately bad logging call | Suite added; positive control asserts the redacted file content | fixed | `884f03d` | `test_privacy_canary.py` |
| SEC-14 | Info | 8 | `tests/test_memory_soak.py` | 50,000-cycle poller soak with a fake client: exactly one toast (mid-soak arrival), tracemalloc heap growth < 512 KiB (measured < 1 KiB). Hostile 10,000-id listings stay bounded (seen set ≤ 500, cache ≤ 10) | Suite added | fixed | `53836f1`, `67cb838`+ | `test_memory_soak.py`, `test_poller.py` |

## Verified clean (no change needed)

- **Git history (Phase 1):** no secret-shaped values in any commit (`git log -p -S` for
  `client_secret`, `refresh_token`, `access_token`, `GOCSPX-`, `ya29.`, `1//`, private
  key headers); `client_config.json`, `.env`, keys were never committed; `.gitignore`
  covers `client_config.json`, `.env`, logs, build/dist.
- **Static analysis (Phase 2):** bandit `src` — no medium/high; pip-audit — no known
  vulnerabilities; ruff `S` rules — only false positives (S105 on a URL constant named
  `*_TOKEN_URL` and on fake test tokens, documented).
- **OAuth (Phase 4):** scope list is exactly `gmail.readonly`; PKCE
  (`autogenerate_code_verifier=True`) and `state` are enforced by google-auth-oauthlib
  1.5.0 (state mismatch raises `MismatchingStateError` before tokens exist); the
  loopback listener binds `localhost` on an ephemeral port, waits ≤ 180 s, and the
  server is closed in a `finally`; a missing `refresh_token` is refused before any
  storage; "Sign in again" with a different account is kept as an additional account;
  account removal deletes the keyring entry and revokes best-effort.
- **URL/process launching (Phase 6):** the only `urlopen` is the fixed Google revoke
  endpoint (https-checked); `webbrowser.open` receives only validated Gmail URLs;
  `os.startfile` is used once, on the fixed app-data folder; no `shell=True`, no
  `eval`/`exec`/`pickle`/`yaml.load` anywhere; no URL is ever taken from mail content.
- **Windows hardening (Phase 7):** autostart writes a quoted path to HKCU only;
  settings/accounts writes are atomic (temp + `os.replace`) with corrupt-file recovery
  (garbage, empty, wrong-type JSON covered by existing tests, huge by SEC-10); the
  single-instance mutex is session-local (`Local\...`) so another user cannot block
  the app; nothing needs admin and nothing writes outside `%APPDATA%`/`%LOCALAPPDATA%`;
  the PyInstaller build is `--onedir --windowed` from a clean venv with pinned
  `requirements-build.txt`, bundling only `client_config.json` as a secret-like file.
- **Robustness (Phase 8):** the poller survives offline, 429/5xx, 403, malformed API
  shapes and unexpected exceptions (catch-all, logged by type); collections are
  bounded (`seen_ids` ≤ 500, cache ≤ 10, opened ≤ 500, logs rotate at 512 KiB×3);
  Gmail services are created and used on the poller thread only; shutdown joins
  threads with timeouts; repeated "Add account" clicks are collapsed by the
  single-flight worker.

## Accepted risks / false positives

| Item | Reason |
|---|---|
| bandit `B105` on `GOOGLE_TOKEN_URL` | The name contains "TOKEN"; the value is a public constant URL, not a credential |
| ruff/bandit `S606`/`B606` on `os.startfile` | By design: opens the fixed app-data folder in Explorer (`# noqa: S606`) |
| `S105` findings in tests | Fake tokens/secret strings (`test-secret`, `FAKE-...`), not real credentials |
| Poller reads `_poll_state.get(email)` outside the lock | Benign under the GIL: worst case one extra cycle for a just-removed account |
| winotify runs each toast via `powershell.exe` subprocess | Kept (D-11/D-18): the script is inert for attacker content; a switch to WinRT (windows-toasts) would add a large dependency for the same property |

## Not verified (needs human)

- Real Google sign-in end-to-end, token expiry, revocation and `invalid_grant` flows.
- Real Windows toasts: appearance, click-to-open, sound, and that the escaped script
  renders true content (the tests prove script inertness with a fake process runner,
  not PowerShell's rendering; one manual toast with a `$(...)` subject is recommended).
- Focus Assist / Do Not Disturb behavior (T-17).
- Tray icon, menu and tooltip on Windows 10 and 11 with DPI scaling; the D-16
  right-aligned tab column rendering.
- Antivirus / SmartScreen reaction to the built exe; 24-hour soak on the real build
  (the 50k-cycle in-process soak is automated, the OS-level soak is not).
- Gitleaks first run in CI (workflow added; executes on GitHub).
- gitleaks/trufflehog were not installable locally; the history scan used
  `git log -p -S` + `git grep` over all commits instead.
