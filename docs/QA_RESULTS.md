# QA_RESULTS.md — Gmail Tray Notifier manual QA session

- Commit: `(recorded after the scaffold commit; see the header note below)`
- App version: 0.1.0
- Windows: build 10.0.22621 — **tester to confirm/correct** (expected Windows 11)
- Date: 2026-11-07
- Build: `dist\GmailNotifier` from `scripts/build_exe.ps1` (frozen `--self-check` all PASS)
- Rules: no real mail content, addresses or tokens in this file — results are described
  in words and accounts are referred to as account#1, account#2.

## Results

| ID | Scenario | Result | Notes |
|---|---|---|---|
| S-1 | Toast injection (hostile subject + hostile first body line) | pending | |
| S-2 | Bangla subject, "&" display name, bidi control subject | pending | |
| S-3 | "Show message preview" off | pending | |
| T-01 | Sign in with a Google account | pending | |
| T-02 | First-run automatic sign-in | pending | |
| T-03 | New mail toast (subject + preview + account) | pending | |
| T-04 | Tray menu shows the 3 latest mails | pending | |
| T-05 | Tooltip shows the latest mail's sender and subject | pending | |
| T-06 | Click a toast opens that mail | pending | |
| T-07 | Click a menu item opens that mail | pending | |
| T-08 | Read mail: icon back to idle, no re-toast | pending | |
| T-09 | Old mail re-entering top 10 does not toast | pending | |
| T-10 | Burst: 5 mails quickly | pending | |
| T-12 | Offline 5 min, reconnect | pending | |
| T-13 | Sleep and resume | pending | |
| T-14 | Revoke access, warning state, re-sign-in | pending | |
| T-15 | Remove an account | pending | |
| T-17 | Focus Assist / Do Not Disturb | pending | |
| T-18 | Start the app twice | pending | |
| T-19 | Quit from the menu | pending | |
| T-16 | Reboot with autostart on | pending | |
| T-20 | Corrupt settings.json | pending | |
| T-21 | Idle 10 min (measure_idle.py) | pending | |
| T-25 | 150% DPI | pending | |
| T-23 | Log review for a known subject/sender | pending | |
| P-1 | Privacy test (TESTING.md §4): folder scan | pending | |
| S-4 | Same account re-signed-in with different letter case | pending | |

## Defects

*(none recorded yet)*

## Deferred (human, after this session)

- T-22: 24-hour soak with `scripts/soak_monitor.py`
- T-24: clean machine without Python
- Windows 10 vs Windows 11 comparison
