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
dist\GmailNotifier\GmailNotifier.exe
```

Pin updates: refresh `requirements-build.txt` from the dev venv (`pip freeze`)
and record dependency changes in `docs/DECISIONS.md` (hard rule 9).

## Optional installer

```powershell
iscc installer\GmailNotifier.iss
```

Produces `dist\installer\GmailNotifierSetup.exe` — a per-user install (no
admin rights) into `%LOCALAPPDATA%\Programs\GmailNotifier`.

## Checks before release

| Check | How | Target |
|---|---|---|
| Runs without Python | copy `dist\GmailNotifier\` to a clean Windows 10/11 machine, start the exe | sign-in + toast work |
| Startup | launch the exe, time to tray icon visible | < 3 s |
| Idle RAM | Task Manager → Details → GmailNotifier.exe after 10 min idle | <= 80 MB |
| Folder size | `Get-ChildItem dist\GmailNotifier -Recurse \| Measure-Object Length -Sum` | informational |
| Single instance | start the exe twice | second exits silently |
| Antivirus | upload the exe/folder to VirusTotal before sharing | no flags (unsigned: SmartScreen warning is expected) |
| Logs | `%LOCALAPPDATA%\GmailNotifier\logs\app.log` contains no mail content | privacy test in docs/TESTING.md §4 |

Measurements from the M7 build on the dev machine (Windows 11, Python 3.13):
startup 2.2 s (to running state; tray icon directly after), idle RAM 62 MB
working set / 49 MB private after ~1 min, folder 153 MB, second instance
exited silently. Re-measure on every release (ROADMAP M8 soak test).

## Known expectations

- The exe is **unsigned**: SmartScreen shows "unknown publisher" until a code
  signing certificate is used.
- `--onedir` ships a folder (~150 MB with the Google API client); an installer
  or single-file build is not planned for v1 (DECISIONS D-12).
- Windows Defender may scan the new exe on first start; subsequent starts are
  faster.
