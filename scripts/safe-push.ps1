# safe-push.ps1 -- safe push of OWN commits to a shared branch via a clean temp worktree.
# Replaces the manual 8-10 step ritual (fetch / worktree / cherry-pick / verify / push /
# cleanup) that caused the accidental merge commit bc10ff6: every step here is fail-fast
# and cleanup is guaranteed by try/finally. AIOS_ALLOW_PUSH is set ONLY after authorship
# verification, so the pre-push guard stays meaningful for manual pushes.
#
# Usage:
#   .\scripts\safe-push.ps1 -Branch sales-2.0-redesign                # all own commits ahead
#   .\scripts\safe-push.ps1 -Branch sales-2.0-redesign -Commits sha1,sha2
# ASCII-only on purpose: PS 5.1 breaks on non-BOM cyrillic scripts (see CLAUDE.md).

param(
  [Parameter(Mandatory=$true)][string]$Branch,
  [string[]]$Commits
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root

# `powershell -File script.ps1 -Commits a,b` передаёт "a,b" одной строкой (в отличие от
# вызова через call-оператор). Нормализуем: принимаем и массив, и строку с запятыми.
if ($Commits) { $Commits = @($Commits | ForEach-Object { $_ -split ',' } | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim() }) }

function Fail([string]$msg) { Write-Host "safe-push: $msg" -ForegroundColor Red; exit 1 }

git fetch origin
if ($LASTEXITCODE -ne 0) { Fail 'git fetch failed' }
$null = git rev-parse --verify --quiet "origin/$Branch"
if ($LASTEXITCODE -ne 0) { Fail "origin/$Branch not found" }

$me = (git config user.name)
if (-not $me) { Fail 'git config user.name is empty' }
$me = $me.Trim()

if (-not $Commits -or $Commits.Count -eq 0) {
  $Commits = @(git rev-list --reverse "origin/$Branch..HEAD" --author="$me")
}
if (-not $Commits -or $Commits.Count -eq 0) { Fail "no own commits ahead of origin/$Branch" }

$touchesSubmodule = $false
foreach ($c in $Commits) {
  $an = (git log -1 --format='%an' $c)
  if ($LASTEXITCODE -ne 0) { Fail "unknown commit: $c" }
  if ($an.Trim() -ne $me) { Fail "commit $c author '$($an.Trim())' is not '$me' -- refusing" }
  $files = @(git diff-tree --no-commit-id --name-only -r $c)
  if ($files | Where-Object { $_ -match '^modules/[^/]+$' }) { $touchesSubmodule = $true }
}
if ($touchesSubmodule) {
  Write-Host 'safe-push: WARNING - commits move submodule pointers; push the submodule repo FIRST (otherwise CI fails on gitlink)' -ForegroundColor Yellow
}

$wtPath = Join-Path (Split-Path $root -Parent) ("_push_" + (Get-Random -Maximum 99999))
if (Test-Path $wtPath) { Fail "worktree path already exists: $wtPath" }

git worktree add --detach $wtPath "origin/$Branch"
if ($LASTEXITCODE -ne 0) { Fail 'worktree add failed -- nothing pushed, main checkout untouched' }

try {
  foreach ($c in $Commits) {
    git -C $wtPath cherry-pick $c
    if ($LASTEXITCODE -ne 0) {
      git -C $wtPath cherry-pick --abort
      Fail "cherry-pick $c failed (conflict?) -- nothing pushed, main checkout untouched"
    }
  }
  $authors = @(git -C $wtPath log --format='%an' "origin/$Branch..HEAD")
  $foreign = @($authors | Where-Object { $_.Trim() -ne $me })
  if ($foreign.Count -gt 0) { Fail "foreign author in push set: $($foreign -join ', ') -- refusing" }

  $oldTip = (git rev-parse --short "origin/$Branch").Trim()
  $env:AIOS_ALLOW_PUSH = '1'
  git -C $wtPath push origin "HEAD:refs/heads/$Branch"
  if ($LASTEXITCODE -ne 0) { Fail 'push failed (diverged again? re-run safe-push)' }
  $newTip = (git -C $wtPath rev-parse --short HEAD).Trim()
  Write-Host "safe-push: OK $oldTip..$newTip -> $Branch ($($Commits.Count) commit(s))" -ForegroundColor Green
} finally {
  Remove-Item Env:AIOS_ALLOW_PUSH -ErrorAction SilentlyContinue
  git worktree remove --force $wtPath
  git worktree prune
}

git fetch origin
exit 0
