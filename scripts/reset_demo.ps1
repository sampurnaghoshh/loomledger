# Wipe and rebuild the demo database (Windows PowerShell twin of scripts/reset_demo.sh).
#
#   .\scripts\reset_demo.ps1                       reset
#   .\scripts\reset_demo.ps1 -Anchor 2026-10-12    reset with another demo day
#   .\scripts\reset_demo.ps1 -Smoke [-Url URL]     rehearsal check: reset -> walk the whole demo over HTTP -> reset
#                                                  (backend must be running, default URL http://localhost:8000)
# Run from any folder, with the venv active. If PowerShell blocks scripts:
#   powershell -ExecutionPolicy Bypass -File .\scripts\reset_demo.ps1 -Smoke
param(
    [switch]$Smoke,
    [string]$Url = "http://localhost:8000",
    [string]$Anchor
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not $env:DATABASE_URL) { $env:DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/loomledger" }

$seedArgs = @()
if ($Anchor) { $seedArgs += @("--anchor", $Anchor) }

function Reset-Demo {
    python -m seed.seed @seedArgs
    if ($LASTEXITCODE -ne 0) { throw "seed failed (exit $LASTEXITCODE)" }
}

Reset-Demo
if ($Smoke) {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8     # show the smoke's check marks and rupee signs
    python -m scripts.demo_smoke $Url
    $status = $LASTEXITCODE
    Write-Host "Resetting again so the stage starts clean..."
    Reset-Demo
    exit $status
}
