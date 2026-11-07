# QA_RESULTS.md — GSend manual QA session

- Commit: `f6d2826` (QA session start)
- App version: 0.1.0
- Windows: Windows 11 22H2, build 10.0.22621, 1920x1080 (confirmed by tester)
- Dates: session started 2026-11-07; Group 1 recorded 2026-11-08
- Build: `dist\GSend` from `scripts/build_exe.ps1` (frozen `--self-check` all PASS)
- Rules: no real mail content, addresses or tokens in this file — results are described
  in words and accounts are referred to as account#1, account#2.

## Results

| ID | Scenario | Result | Notes |
|---|---|---|---|
| S-1 | Toast injection (hostile subject + hostile first body line) | **pass** | Whole hostile subject rendered as literal text in the toast (command substitution, quote-at, XML pseudo-tags, ampersand all visible; nothing bold, nothing swallowed, nothing executed). Persisted toast payload parses as well-formed XML with the full subject in one text node (exactly the sent length, all markers present). Tray menu row shows the same text up to the by-design `…` truncation; age and account column correct. Calculator never appeared (process-checked after every toast and every screenshot frame). Menu ampersand also verified in code (doubled for Win32). |
| S-2 | Bangla subject, "&" display name, bidi control subject | **pass** | Sender display name with both ampersands visible in toast body and menu row. Bangla renders, word order intact; the embedded Latin word reads the backwards spelling — direction-control characters removed (payload text node exactly 2 chars shorter than the input; zero bidi control codepoints present) and the reordering failure signature (the forward spelling) is absent. No console flash at toast time. |
| S-3 | "Show message preview" off | **pass** | Toast shows subject plus a single "sender · account" line; the preview sentence from the mail body is absent from banner and payload. Setting re-ticked afterwards and persisted (`show_preview: true`). |
| T-01 | pass | Recorded from the tester's blanket group report (already tested); no per-test detail. | |
| T-02 | pass | Recorded from the tester's blanket group report (already tested); no per-test detail. | |
| T-03 | pass | Recorded from the tester's blanket group report (already tested); no per-test detail. | |
| T-04 | pass | Recorded from the tester's blanket group report (already tested); no per-test detail. | |
| T-05 | pass | Recorded from the tester's blanket group report (already tested); no per-test detail. | |
| T-06 | pass | Recorded from the tester's blanket group report (already tested); no per-test detail. | |
| T-07 | pass | Recorded from the tester's blanket group report (already tested); no per-test detail. | |
| T-08 | pass | Recorded from the tester's blanket group report (already tested); no per-test detail. | |
| T-09 | pass | Recorded from the tester's blanket group report (already tested); no per-test detail. | |
| T-10 | pass | Recorded from the tester's blanket group report (already tested); no per-test detail. | |
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

## Session notes

- Group 2 (T-01..T-10) recorded as a blanket pass on the tester's report; per-test
  detail was not captured this session. T-01's first-run path remains covered by the
  M6 sign-off; it cannot be reproduced here without wiping the account list and the
  first-run flag.

- Group 1 sender mailbox: a third mailbox the tester controls (allowed by the
  S-1 wording "any other mailbox you control"); its display name was changed
  for S-2 and reverted on Gmail's settings page.
- S-1/S-3 toasts fired via the 45 s auto-poll before "Check now" was clicked
  (mail-to-toast latency ≈ one poll interval, no other delay); "Check now"
  exercised successfully during S-2.
- One S-3 tray-click attempt missed due to a tester-side UIA lookup flake
  (clicked empty desktop; no app involvement).
- Notification-center collapsed entry shows only the first toast line —
  cosmetic, Windows-side rendering, not app behavior.

## Defects

*(none recorded yet)*

## Deferred (human, after this session)

- T-22: 24-hour soak with `scripts/soak_monitor.py`
- T-24: clean machine without Python
- Windows 10 vs Windows 11 comparison
