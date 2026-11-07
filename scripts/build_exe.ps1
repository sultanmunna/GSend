# Builds dist/GmailNotifier with PyInstaller from a clean venv (DECISIONS D-12/D-13).
# Run from the repo root in PowerShell:  .\scripts\build_exe.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# Hard rule 5: the real client config is bundled at build time, never committed.
if (-not (Test-Path "client_config.json")) {
    Write-Error "client_config.json is missing in the repo root. See docs/GOOGLE_CLOUD_SETUP.md."
    exit 1
}

# Hard rule 3: mail content must never end up in the bundle or the build dir.
if (Test-Path ".venv-build") { Remove-Item -Recurse -Force ".venv-build" }
python -m venv .venv-build
if ($LASTEXITCODE -ne 0) { Write-Error "python -m venv failed"; exit 1 }

& .venv-build\Scripts\python.exe -m pip install --upgrade pip --quiet
& .venv-build\Scripts\python.exe -m pip install -r requirements-build.txt --quiet
if ($LASTEXITCODE -ne 0) { Write-Error "pip install failed"; exit 1 }

# Refresh the icon from the runtime drawing so exe and tray stay in sync.
& .venv-build\Scripts\python.exe -I scripts\make_icons.py

& .venv-build\Scripts\python.exe -m PyInstaller `
    --noconfirm --clean `
    --onedir --windowed `
    --name GmailNotifier `
    --paths src `
    --icon assets\app.ico `
    --add-data "client_config.json;." `
    --version-file assets\version_info.py `
    --hidden-import keyring.backends.Windows `
    --hidden-import pystray._win32 `
    src\gmail_notifier\__main__.py
if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller failed"; exit 1 }

Write-Host ""
Write-Host "Build output: $Root\dist\GmailNotifier\GmailNotifier.exe"
Write-Host "Next: smoke-test on this machine, then on a clean machine (docs/BUILD.md)."
