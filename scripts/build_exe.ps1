# Builds dist/GSend with PyInstaller from a clean venv (DECISIONS D-12/D-13).
# Run from the repo root in PowerShell:  .\scripts\build_exe.ps1
# -ScanBuild bundles client_config.example.json (fake client) instead of the real
# one; that output is for antivirus/scan services ONLY (docs/BUILD.md), not for use.
param([switch]$ScanBuild)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# Hard rule 5: the client config is bundled at build time, never committed.
$ClientConfig = if ($ScanBuild) { "client_config.example.json" } else { "client_config.json" }
if (-not (Test-Path $ClientConfig)) {
    Write-Error "$ClientConfig is missing in the repo root. See docs/GOOGLE_CLOUD_SETUP.md."
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
if ($LASTEXITCODE -ne 0) { Write-Error "make_icons failed"; exit 1 }

& .venv-build\Scripts\python.exe -m PyInstaller `
    --noconfirm --clean `
    --onedir --windowed `
    --name GSend `
    --paths src `
    --icon assets\app.ico `
    --add-data "$ClientConfig;." `
    --version-file assets\version_info.py `
    --hidden-import keyring.backends.Windows `
    --hidden-import pystray._win32 `
    src\gsend\__main__.py
if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller failed"; exit 1 }

Write-Host ""
Write-Host "Build output: $Root\dist\GSend\GSend.exe"
if ($ScanBuild) {
    Write-Host "SCAN BUILD: bundled client_config.example.json (fake client)."
    Write-Host "For antivirus/scan services ONLY - do not distribute for daily use."
}
Write-Host "Next: smoke-test on this machine, then on a clean machine (docs/BUILD.md)."
