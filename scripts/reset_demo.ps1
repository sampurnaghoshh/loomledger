# Wipe and rebuild a LoomLedger database (Windows PowerShell twin of scripts/reset_demo.sh).
#
#   .\scripts\reset_demo.ps1                          reset the demo DB ($env:DATABASE_URL, default .../loomledger)
#   .\scripts\reset_demo.ps1 -DatabaseUrl URL         reset another database (created if missing)
#   .\scripts\reset_demo.ps1 -Smoke [-Url API]        reset -> walk the whole demo over HTTP against a RUNNING backend -> reset
#   .\scripts\reset_demo.ps1 -Rehearsal [-Port 8001]  private rehearsal, leaves the demo DB and :8000 alone:
#                                                     loomledger_rehearsal (created if missing) + its own backend on :8001
#                                                     -> reset -> smoke -> stop that backend -> reset
#   .\scripts\reset_demo.ps1 -Anchor 2026-10-12       another demo day
#   .\scripts\reset_demo.ps1 -Eval                    evaluator playground: loomledger_eval (created if missing) reset with
#                                                     --profile eval (the story + ~300 rolls of history). Starts NOTHING;
#                                                     see docs/DEMO_RUNBOOK.md "Evaluator playground" (backend :8002, frontend :5174)
# Run with the venv active. If PowerShell blocks scripts:
#   powershell -ExecutionPolicy Bypass -File .\scripts\reset_demo.ps1 -Rehearsal
param(
    [string]$DatabaseUrl,
    [switch]$Smoke,
    [string]$Url = "http://localhost:8000",
    [switch]$Rehearsal,
    [int]$Port = 8001,
    [string]$Anchor,
    [switch]$Eval
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if ($Eval -and ($Rehearsal -or $Smoke)) { [Console]::Error.WriteLine("-Eval only resets loomledger_eval; it can't be combined with -Smoke/-Rehearsal"); exit 2 }
if ($Eval -and -not $DatabaseUrl) { $DatabaseUrl = "postgresql://postgres:postgres@localhost:5432/loomledger_eval" }
if ($Rehearsal) {
    if (-not $DatabaseUrl) { $DatabaseUrl = "postgresql://postgres:postgres@localhost:5432/loomledger_rehearsal" }
    $Url = "http://localhost:$Port"
    $Smoke = $true
}
if ($DatabaseUrl) { $env:DATABASE_URL = $DatabaseUrl }
elseif (-not $env:DATABASE_URL) { $env:DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/loomledger" }
python -m scripts.ensure_db $env:DATABASE_URL                  # creates it if missing; harmless otherwise
if ($LASTEXITCODE -ne 0) { Write-Host "(could not check/create the database - continuing)" }
Write-Host ("database: " + ($env:DATABASE_URL -split "/")[-1])

$seedArgs = @()
if ($Anchor) { $seedArgs += @("--anchor", $Anchor) }
if ($Eval) { $seedArgs += @("--profile", "eval") }

function Reset-Demo {
    python -m seed.seed @seedArgs
    if ($LASTEXITCODE -ne 0) { throw "seed failed (exit $LASTEXITCODE)" }
}

function Test-Health([string]$api) {
    try { return (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "$api/api/health").StatusCode -eq 200 } catch { return $false }
}

Reset-Demo
if (-not $Smoke) { exit 0 }

$backend = $null
try {
    if ($Rehearsal) {
        $probe = New-Object System.Net.Sockets.TcpClient
        try { $probe.Connect("localhost", $Port); $busy = $true } catch { $busy = $false } finally { $probe.Close() }
        if ($busy) { [Console]::Error.WriteLine("port $Port is already in use - stop that process or pass -Port"); exit 2 }
        # inherits $env:DATABASE_URL, so this backend only ever sees the rehearsal database
        $backend = Start-Process python -ArgumentList "-m", "uvicorn", "app.main:app", "--port", $Port, "--log-level", "warning" `
            -PassThru -NoNewWindow
        for ($i = 0; $i -lt 40 -and -not (Test-Health $Url); $i++) { Start-Sleep -Milliseconds 500 }
    }
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8     # show the smoke's check marks and rupee signs
    python -m scripts.demo_smoke $Url
    $status = $LASTEXITCODE
} finally {
    if ($backend) { Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue }   # only the backend we started
}
Write-Host ("Resetting " + ($env:DATABASE_URL -split "/")[-1] + " again so it starts clean...")
Reset-Demo
exit $status
