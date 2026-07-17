# bootstrap-worktree.ps1 -- first step inside a spawned worktree session.
# Audit finding: harness creates worktrees off `main` (206 commits behind the working
# branch) and without node_modules; two background sessions independently spent time
# fixing the exact same pair of problems. Run this ONCE at the start of a worktree session.
#
# Usage (from inside the worktree):
#   powershell -ExecutionPolicy Bypass -File <main-checkout>\scripts\bootstrap-worktree.ps1
#   ... -Branch <target>   # override target branch (default: git config aios.defaultBranch)
# Safe by design: refuses to reset a dirty tree; main checkout is never touched.
# ASCII-only on purpose: PS 5.1 breaks on non-BOM cyrillic scripts (see CLAUDE.md).

param(
  [string]$Branch
)
$ErrorActionPreference = 'Stop'

$wt = (git rev-parse --show-toplevel)
if ($LASTEXITCODE -ne 0) { Write-Host 'bootstrap-worktree: not a git tree' -ForegroundColor Red; exit 1 }
$wt = $wt.Trim()

# Main checkout = first entry of `git worktree list`.
$mainLine = (git worktree list --porcelain | Select-Object -First 1)
$main = $mainLine -replace '^worktree ', ''
if ((Resolve-Path $wt).Path -eq (Resolve-Path $main).Path) {
  Write-Host 'bootstrap-worktree: this IS the main checkout - nothing to do'; exit 0
}

if (-not $Branch) {
  $Branch = (git config aios.defaultBranch)
  if (-not $Branch) { $Branch = 'sales-2.0-redesign' }
  $Branch = $Branch.Trim()
}

# 1. Rebase the worktree onto the target branch tip if it is behind (clean tree only).
$dirty = @(git -C $wt status --porcelain)
$behind = (git -C $wt rev-list --count "HEAD..$Branch")
if ([int]$behind -gt 0) {
  if ($dirty.Count -gt 0) {
    Write-Host "bootstrap-worktree: tree is $behind commits behind '$Branch' but DIRTY - not resetting. Commit/stash first, then re-run." -ForegroundColor Yellow
  } else {
    $cur = (git -C $wt branch --show-current).Trim()
    git -C $wt reset --hard $Branch
    if ($LASTEXITCODE -ne 0) { Write-Host 'bootstrap-worktree: reset failed' -ForegroundColor Red; exit 1 }
    Write-Host "bootstrap-worktree: branch '$cur' reset onto '$Branch' tip (was $behind behind)"
  }
} else {
  Write-Host "bootstrap-worktree: already at/ahead of '$Branch' tip"
}

# 2. node_modules junction from the main checkout (npm install is slow; junction is instant).
$src = Join-Path $main 'frontend\node_modules'
$dst = Join-Path $wt 'frontend\node_modules'
if ((Test-Path $src) -and (-not (Test-Path $dst))) {
  New-Item -ItemType Junction -Path $dst -Target $src | Out-Null
  Write-Host 'bootstrap-worktree: frontend/node_modules junction created'
} elseif (Test-Path $dst) {
  Write-Host 'bootstrap-worktree: frontend/node_modules already present'
}

# 3. Submodules.
git -C $wt submodule update --init
if ($LASTEXITCODE -ne 0) { Write-Host 'bootstrap-worktree: submodule update failed' -ForegroundColor Red; exit 1 }

Write-Host 'bootstrap-worktree: OK - tree is ready for tsc/vitest/pytest' -ForegroundColor Green
exit 0
