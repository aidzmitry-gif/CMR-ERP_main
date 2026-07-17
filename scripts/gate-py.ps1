# gate-py.ps1 -- python gate in one command: ruff + pytest (in-memory SQLite).
# Usage:
#   .\scripts\gate-py.ps1                       # ruff + full pytest
#   .\scripts\gate-py.ps1 tests/test_leads.py   # ruff + targeted tests (any pytest args)
# ASCII-only on purpose: PS 5.1 breaks on non-BOM cyrillic scripts (see CLAUDE.md).

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path $PSScriptRoot -Parent)

& .\.venv\Scripts\python.exe -m ruff check .
if ($LASTEXITCODE -ne 0) { Write-Host "gate-py: ruff FAILED" -ForegroundColor Red; exit $LASTEXITCODE }

if (-not $env:AIOS_DATABASE_URL) { $env:AIOS_DATABASE_URL = 'sqlite+aiosqlite:///:memory:' }
$env:PYTHONPATH = '.'

if ($args.Count -gt 0) {
  & .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider @args
} else {
  & .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
}
$code = $LASTEXITCODE
if ($code -ne 0) { Write-Host "gate-py: pytest FAILED ($code)" -ForegroundColor Red }
else { Write-Host "gate-py: OK (ruff + pytest green)" -ForegroundColor Green }
exit $code
