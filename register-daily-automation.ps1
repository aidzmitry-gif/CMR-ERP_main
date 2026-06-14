# register-daily-automation.ps1 — две задачи Планировщика Windows:
#   CRM-tg-digest     ежедневно 08:00 → tg_digest.py   (дашборд+готовность+CI → Telegram)
#   CRM-daily-review  ежедневно 23:59 → daily_review.py (авто-сессия ретроспективы дня)
#
# Локальные задачи (не облачный cron): им нужны ваши воркеры/транскрипты/.env, доступные
# только на этой машине. Регистрируются под текущим пользователем, выполняются когда вы
# вошли в систему (видимое окно ретроспективы в 23:59 для этого и нужно).
#
#   powershell -ExecutionPolicy Bypass -File register-daily-automation.ps1          # включить
#   powershell -ExecutionPolicy Bypass -File register-daily-automation.ps1 -Remove  # убрать
#
# Проверка:  Get-ScheduledTask -TaskName 'CRM-*' | Format-Table TaskName,State

param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$py = Join-Path $root '.venv\Scripts\python.exe'

$tasks = @(
  @{ Name = 'CRM-tg-digest';    Script = 'tg_digest.py';   Time = '08:00' },
  @{ Name = 'CRM-daily-review'; Script = 'daily_review.py'; Time = '23:59' }
)

if ($Remove) {
  foreach ($t in $tasks) {
    try {
      Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false -ErrorAction Stop
      Write-Host "удалено: $($t.Name)"
    } catch { Write-Host "нет задачи: $($t.Name)" }
  }
  return
}

if (-not (Test-Path $py)) { throw "не найден venv python: $py" }

foreach ($t in $tasks) {
  $scriptPath = Join-Path $root $t.Script
  if (-not (Test-Path $scriptPath)) { throw "нет скрипта: $scriptPath" }
  $action  = New-ScheduledTaskAction -Execute $py -Argument ('"{0}"' -f $scriptPath) -WorkingDirectory $root
  $trigger = New-ScheduledTaskTrigger -Daily -At $t.Time
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
              -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)
  Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger -Settings $settings `
    -Description 'CRM ERP — ежедневная автоматизация' -Force | Out-Null
  Write-Host "зарегистрировано: $($t.Name) @ $($t.Time) -> $($t.Script)"
}

Write-Host ""
Write-Host "Готово. Проверка:  Get-ScheduledTask -TaskName 'CRM-*' | Format-Table TaskName,State"
Write-Host "Тест сейчас:       Start-ScheduledTask -TaskName 'CRM-tg-digest'"
Write-Host "Убрать:            powershell -File register-daily-automation.ps1 -Remove"
