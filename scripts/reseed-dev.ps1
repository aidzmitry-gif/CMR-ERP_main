# reseed-dev.ps1 -- full dev.db rebuild in one command: stop backend, drop db, seed, restart.
# Fixes the audit finding: 4 manual stop/rm/seed/start cycles per week, incl. a double
# rebuild caused by a forgotten scoring step (scoring is inside seed.py since 2026-07-11).
#
# Usage:
#   .\scripts\reseed-dev.ps1          # rebuild dev.db and restart servers
#   .\scripts\reseed-dev.ps1 -Demo    # same, demo pricing mode
# ASCII-only on purpose: PS 5.1 breaks on non-BOM cyrillic scripts (see CLAUDE.md).

param(
  [switch]$Demo
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root

# 1. Stop backend: the SQLite file is held open by the uvicorn process.
try {
  $c = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction Stop | Select-Object -First 1
  if ($c) {
    Write-Host "stopping backend PID $($c.OwningProcess)"
    Stop-Process -Id $c.OwningProcess -Force -Confirm:$false
    Start-Sleep -Seconds 1
  }
} catch { Write-Host 'backend :8000 not running' }

# 2. Drop dev.db.
if (Test-Path .\dev.db) { Remove-Item .\dev.db -Force -Confirm:$false; Write-Host 'dev.db removed' }

# 3. Seed (scoring included in seed.py itself).
$env:AIOS_DATABASE_URL = 'sqlite+aiosqlite:///./dev.db'
$env:AIOS_ENVIRONMENT = 'dev'
$env:PYTHONPATH = '.'
if ($Demo) { $env:AIOS_DEMO_PRICE_COST = '1' }
& .\.venv\Scripts\python.exe scripts\seed.py
if ($LASTEXITCODE -ne 0) { Write-Host 'reseed-dev: seed FAILED' -ForegroundColor Red; exit $LASTEXITCODE }

# 4. Restart servers (idempotent).
if ($Demo) { & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'dev-servers.ps1') -Demo }
else { & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'dev-servers.ps1') }
exit $LASTEXITCODE
