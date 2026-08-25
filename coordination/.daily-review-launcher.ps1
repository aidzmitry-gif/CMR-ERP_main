$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = 'daily-review'
Set-Location -LiteralPath 'D:\6 Проекты\CRM ERP\Сlaude CRM - проект'
$prompt = Get-Content -Raw -Encoding UTF8 -LiteralPath 'D:\6 Проекты\CRM ERP\Сlaude CRM - проект\coordination\daily-review-prompt.md'
$date = Get-Date -Format 'yyyy-MM-dd'
$started = Get-Date
$report = Join-Path 'D:\6 Проекты\CRM ERP\Сlaude CRM - проект' ('coordination/daily-review/' + $date + '.md')
$log = Join-Path 'D:\6 Проекты\CRM ERP\Сlaude CRM - проект\coordination\.daily-review-data' 'last-run.log'
Write-Host '=== ретроспектива дня (read-only): claude стартует ===' -ForegroundColor Cyan
& 'C:\Users\aidzm\AppData\Roaming\npm\claude.CMD' --print --verbose --permission-mode acceptEdits --add-dir 'D:\6 Проекты\CRM ERP\Сlaude CRM - проект' --add-dir 'C:\Users\aidzm\.claude\projects' --model sonnet -- $prompt
$dir = Join-Path 'D:\6 Проекты\CRM ERP\Сlaude CRM - проект' 'coordination/daily-review'
$fresh = @(Get-ChildItem $dir -Filter '*.md' | Where-Object { $_.LastWriteTime -ge $started })
if ($fresh.Count -gt 0) {
  "$date OK - отчёт записан: $($fresh[0].Name) $(Get-Date -Format HH:mm)" | Out-File $log -Encoding utf8
  Write-Host '=== готово: отчёт в coordination/daily-review/ ===' -ForegroundColor Yellow
} else {
  "$date FAIL - claude завершился без отчёта (частая причина: headless-auth; проверь вручную: claude --print -- 'ping')" | Out-File $log -Encoding utf8
  Write-Host 'FAIL: отчёт НЕ записан — лог: coordination/.daily-review-data/last-run.log (утренний дайджест продублирует)' -ForegroundColor Red
  Start-Sleep -Seconds 300
}
