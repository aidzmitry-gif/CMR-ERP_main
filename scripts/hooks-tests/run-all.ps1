# run-all.ps1 -- run every hook regression suite.
#
#   powershell -ExecutionPolicy Bypass -File scripts\hooks-tests\run-all.ps1
#
# Takes 2-4 minutes (each suite spawns the hooks as separate processes), so it is NOT part of
# scripts\gate-py.ps1 and pytest does not collect it (testpaths = ["tests"]).
# Run it after ANY change to claude_*_hook.py, spawn_workers.py, tg_sessions.py or
# .claude/settings.json. Russian description of every suite -- see README.md next to this file.
#
# ASCII only, on purpose: Windows PowerShell 5.1 reads .ps1 in the system ANSI codepage unless
# the file has a BOM, and Cyrillic then breaks parsing. Same convention as the other project
# scripts (gate-py.ps1, dev-servers.ps1) -- none of them contain non-ASCII.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Error "venv not found: $py"; exit 1 }

$tests = @(
  @{ f = "test_guard.py";         d = "guard: 51 cases, incl. bypasses found by the 25.07 audit" },
  @{ f = "test_hooks_smoke.py";   d = "every hook answers all events without crashing" },
  @{ f = "test_parent_hooks.py";  d = "hooks behave the same from any launch directory" },
  @{ f = "test_ledger_owner.py";  d = "own vs foreign touched-ledger: who gets blocked" },
  @{ f = "test_subagent_stop.py"; d = "ledger cleanup: who deletes whose file" },
  @{ f = "test_loop_contract.py"; d = "model/effort/budget parsed from the worker scope" }
)

$failed = @()
foreach ($t in $tests) {
  Write-Host ""
  Write-Host "=== $($t.f) -- $($t.d)" -ForegroundColor Cyan
  & $py (Join-Path $PSScriptRoot $t.f)
  if ($LASTEXITCODE -ne 0) { $failed += $t.f }
}

Write-Host ""
if ($failed.Count) {
  Write-Host "FAILED: $($failed -join ', ')" -ForegroundColor Red
  exit 1
}
Write-Host "All suites passed." -ForegroundColor Green
