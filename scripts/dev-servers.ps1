# dev-servers.ps1 -- idempotent dev environment bring-up (backend :8000 + frontend :3210).
# Fixes the audit finding: session-spawned processes die at turn boundary; 7+ manual
# PowerShell bring-ups per week. Detached processes survive the session.
#
# Usage:
#   .\scripts\dev-servers.ps1            # start whatever is not running, health-poll
#   .\scripts\dev-servers.ps1 -Restart   # kill both first, then start fresh
#   .\scripts\dev-servers.ps1 -Demo      # demo pricing mode (AIOS_DEMO_PRICE_COST=1)
# ASCII-only on purpose: PS 5.1 breaks on non-BOM cyrillic scripts (see CLAUDE.md).

param(
  [switch]$Demo,
  [switch]$Restart
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root

function Get-PortPid([int]$Port) {
  try {
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1
    return $c.OwningProcess
  } catch { return $null }
}

function Stop-Port([int]$Port) {
  $procId = Get-PortPid $Port
  if ($procId) {
    Write-Host "port ${Port}: stopping PID $procId"
    try { Stop-Process -Id $procId -Force -Confirm:$false -ErrorAction Stop } catch {}
    Start-Sleep -Milliseconds 500
  }
}

function Wait-Health([string]$Url, [int]$Seconds = 60) {
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    try {
      $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
      if ($r.StatusCode -lt 500) { return $true }
    } catch {}
    Start-Sleep -Seconds 2
  }
  return $false
}

if ($Restart) { Stop-Port 8000; Stop-Port 3210 }

$env:AIOS_DATABASE_URL = 'sqlite+aiosqlite:///./dev.db'
$env:AIOS_ENVIRONMENT = 'dev'
if ($Demo) { $env:AIOS_DEMO_PRICE_COST = '1' } else { Remove-Item Env:AIOS_DEMO_PRICE_COST -ErrorAction SilentlyContinue }

$backendPid = Get-PortPid 8000
if ($backendPid) {
  Write-Host "backend :8000 already up (PID $backendPid)"
} else {
  Start-Process -FilePath (Join-Path $root '.venv\Scripts\python.exe') -ArgumentList 'scripts\dev_backend.py' -WorkingDirectory $root -WindowStyle Hidden
  Write-Host 'backend :8000 starting...'
}

$frontendPid = Get-PortPid 3210
if ($frontendPid) {
  Write-Host "frontend :3210 already up (PID $frontendPid)"
} else {
  Start-Process -FilePath 'npm.cmd' -ArgumentList '--prefix', 'frontend', 'run', 'dev', '--', '-p', '3210' -WorkingDirectory $root -WindowStyle Hidden
  Write-Host 'frontend :3210 starting...'
}

$beOk = Wait-Health 'http://127.0.0.1:8000/docs' 60
$feOk = Wait-Health 'http://127.0.0.1:3210' 90
$backendPid = Get-PortPid 8000
$frontendPid = Get-PortPid 3210

Write-Host ("backend:  " + $(if ($beOk) { "OK (PID $backendPid)" } else { 'FAIL - no health in 60s' }))
Write-Host ("frontend: " + $(if ($feOk) { "OK (PID $frontendPid)" } else { 'FAIL - no health in 90s' }))
if (-not ($beOk -and $feOk)) { exit 1 }
exit 0
