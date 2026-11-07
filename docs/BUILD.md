# Building the Windows app

Prerequisites on the build machine: Python 3.11+ on `PATH`, PowerShell, and the
repo. Everything else happens inside a clean build venv.

## One-time setup

`client_config.json` must exist in the repo root (git-ignored, real OAuth
client — see `docs/GOOGLE_CLOUD_SETUP.md`). The build **fails** without it; it
is bundled into the exe at build time (DECISIONS D-13) and never committed.

## Build

```powershell
.\scripts\build_exe.ps1
```

The script: creates a clean `.venv-build`, installs the pinned versions from
`requirements-build.txt`, regenerates `assets\app.ico` from the runtime tray
drawing, and runs PyInstaller (`--onedir --windowed`, hidden imports for the
keyring/pystray Windows backends, version resource). Output:

```
dist\GSend\GSend.exe
```

Verified contents of `dist\GSend\` (M7 re-verification, 2026-11-07):

- `GSend.exe` — PE32+, **subsystem 2 (WINDOWS_GUI)**, so no console
  window; icon and version resource embedded from `assets\`.
- `_internal\client_config.json` — the real OAuth client, bundled at build time.
- `_internal\googleapiclient\discovery_cache\documents\gmail.v1.json` — the
  bundled discovery document that `static_discovery=True` (D-19) reads; no
  extra PyInstaller hook needed.

Pin updates: refresh `requirements-build.txt` from the dev venv (`pip freeze`)
and record dependency changes in `docs/DECISIONS.md` (hard rule 9). winotify is
pinned exactly (`==`) and guarded by `tests/test_winotify_tripwire.py` — see
the tripwire's re-audit message before accepting a bump.

## Self-check

```powershell
.\dist\GSend\GSend.exe --self-check
```

Runs offline checks only (no network, sign-in, tray or mutex) and prints one
`PASS`/`FAIL` line per check plus an overall line; exit code 0 or 1:

app version · settings load · accounts load · client config valid (Google
endpoints) · keyring is Windows Credential Manager · gmail service builds from
bundled discovery · winotify imports · pystray imports · tray icon images
generate.

The windowed exe has no console, so the self-check attaches to the parent
terminal (or allocates one) and also records the same lines (names only, no
values) to `%LOCALAPPDATA%\GSend\logs\self_check.log`. **The scan
build (below) intentionally FAILs the "client config valid" line** — its fake
client is unusable by design.

## Release packaging

```powershell
.\scripts\package_release.ps1             # real build -> dist\GSend-<version>.zip + SHA256SUMS.txt
.\scripts\package_release.ps1 -ScanBuild  # scan build  -> dist\GSend-<version>-scan.zip + SHA256SUMS-scan.txt
```

## Antivirus scanning: scan build ONLY

The real build bundles the real `client_config.json`. Sharing it with users is
fine, but it must **never** be uploaded to VirusTotal or any other scanning
service — files uploaded there are shared with security vendors. For scanning,
build the scan build first, which bundles `client_config.example.json` (fake
client, no secret) instead:

```powershell
.\scripts\build_exe.ps1 -ScanBuild
.\scripts\package_release.ps1 -ScanBuild
```

The scan build is for scanning only; its sign-in cannot work (fake client) and
it must not be distributed for daily use.

## Measurements

Measured on the dev machine (Windows 11, build 22621, Python 3.13), 2026-11-07,
with `scripts/measure_idle.py` (psutil, DECISIONS D-22), app idling with one
real account, poll interval 45 s:

| Metric | Value | Target |
|---|---|---|
| Startup (to the "starting" log line) | 0.8 s | < 3 s |
| Idle RSS after 10 minutes | 72.8 MB (flat from ~1 min: 63 → 72.6 → 72.8 MB) | <= 80 MB |
| Idle CPU (average over 10 min) | 0.08% (~0% between polls) | ~0% |
| `dist\GSend` folder size | 152.7 MB | informational |

Re-measure on every release. The 24-hour soak (T-22) uses
`scripts/soak_monitor.py`: start the exe, run
`python scripts/soak_monitor.py --pid <pid>`; it appends one CSV line per
minute (timestamp, pid, RSS MB, CPU %, threads, handles — numbers only) to
`%LOCALAPPDATA%\GSend\logs\soak_metrics.csv`.

## Optional installer

```powershell
iscc installer\GSend.iss
```

Produces `dist\installer\GSendSetup.exe` — a per-user install (no
admin rights) into `%LOCALAPPDATA%\Programs\GSend`.

## Checks before release

| Check | How | Target |
|---|---|---|
| `--self-check` | run the exe with the flag (above) | all PASS, exit 0 |
| Runs without Python | copy `dist\GSend\` to a clean Windows 10/11 machine, start the exe | sign-in + toast work |
| Startup | `scripts/measure_idle.py` (to "starting" log line), then confirm the tray icon is visible | < 3 s |
| Idle RAM / CPU | `scripts/measure_idle.py --exe dist\GSend\GSend.exe --minutes 10` | <= 80 MB, ~0% |
| 24-hour soak | `scripts/soak_monitor.py` against the running exe | RSS flat over 24 h |
| Folder size | `measure_idle.py --dist dist\GSend` | informational |
| Single instance | start the exe twice | second exits silently |
| Antivirus | upload the **scan build zip only** (see above) | no flags (unsigned: SmartScreen warning is expected) |
| Logs | `%LOCALAPPDATA%\GSend\logs\app.log` contains no mail content | privacy test in docs/TESTING.md §4 |

Verification run 2026-11-07 (dev machine): frozen `--self-check` all PASS
(recorded in `self_check.log`); 60-second live run — process alive, no console
window (GUI subsystem), one INFO startup line, zero ERROR/WARNING lines, zero
token/secret/code URL patterns in the new log text; clean terminate; no process
remained. No SmartScreen/antivirus prompt was observed launching from
PowerShell on the dev machine (expected: unsigned exe shows SmartScreen on the
first Explorer launch — needs human confirmation).

## Known expectations

- The exe is **unsigned**: SmartScreen shows "unknown publisher" until a code
  signing certificate is used.
- `--onedir` ships a folder (~150 MB with the Google API client); an installer
  or single-file build is not planned for v1 (DECISIONS D-12).
- Windows Defender may scan the new exe on first start; subsequent starts are
  faster.
