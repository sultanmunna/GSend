# Packages dist\GSend into a versioned zip plus a SHA256SUMS file.
# Run from the repo root in PowerShell:
#   .\scripts\package_release.ps1            (real build: for distribution to users)
#   .\scripts\package_release.ps1 -ScanBuild (scan build: for antivirus services ONLY)
#
# SECURITY: the real build bundles the real client_config.json. It is fine to
# share with users, but it must NEVER be uploaded to VirusTotal or any scanning
# service (uploads there are shared with security vendors). Build the scan
# build instead:  .\scripts\build_exe.ps1 -ScanBuild   (docs/BUILD.md).
param([switch]$ScanBuild)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$dist = "dist\GSend"
if (-not (Test-Path "$dist\GSend.exe")) {
    Write-Error "No build found. Run .\scripts\build_exe.ps1 first (add -ScanBuild to match)."
    exit 1
}

$versionMatch = Select-String -Path "src\gsend\__init__.py" -Pattern '__version__ = "(.+)"'
if (-not $versionMatch) { Write-Error "Could not read __version__ from src\gsend\__init__.py"; exit 1 }
$version = $versionMatch.Matches[0].Groups[1].Value
$suffix = if ($ScanBuild) { "-scan" } else { "" }

$zip = "dist\GSend-$version$suffix.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path "$dist\*" -DestinationPath $zip

$sumsFile = "dist\SHA256SUMS$suffix.txt"
if (Test-Path $sumsFile) { Remove-Item -Force $sumsFile }
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
"$hash  $(Split-Path -Leaf $zip)" | Set-Content -Encoding ascii $sumsFile

Write-Host ""
Write-Host "Packaged: $zip"
Write-Host "SHA256:   $hash (also in $sumsFile)"
if (-not $ScanBuild) {
    Write-Host ""
    Write-Host "NOTE: this zip contains the real client_config.json. Share with users,"
    Write-Host "but NEVER upload it to VirusTotal or any scanning service - use the"
    Write-Host "scan build for that (docs/BUILD.md)."
}
