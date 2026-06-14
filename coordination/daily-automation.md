# Ежедневная автоматизация (Telegram-дайджест + ретроспектива)

Две локальные задачи Планировщика Windows. Локальные, а не облачный cron, — потому что им
нужны ваши воркеры/транскрипты/`.env`, доступные только на этой машине.

| Задача | Время | Скрипт | Что делает |
|---|---|---|---|
| `CRM-tg-digest` | 08:00 | `tg_digest.py` | дашборд флота + готовность модулей + статус CI → в Telegram |
| `CRM-daily-review` | 23:59 | `daily_review.py` | открывает видимую **read-only** Claude-сессию (`acceptEdits` — Bash/команды НЕ исполняются), анализирует день (мои/агентов паттерны, взаимодействия) → `coordination/daily-review/<дата>.md` |

## Включить

```powershell
powershell -ExecutionPolicy Bypass -File register-daily-automation.ps1
Get-ScheduledTask -TaskName 'CRM-*' | Format-Table TaskName,State    # проверка
```

> Регистрацию запускаешь **ты сам**: авто-классификатор безопасности (правильно) не даёт
> ассистенту регистрировать ночную автономную Claude-сессию. Скрипт безопасен — ретроспектива
> идёт в `acceptEdits` (только чтение + один отчёт, без выполнения команд), а не bypassPermissions.

## Проверить вручную (до наступления времени)

```powershell
& ".\.venv\Scripts\python.exe" tg_digest.py --dry-run     # превью дайджеста, без отправки
& ".\.venv\Scripts\python.exe" tg_digest.py               # реальная отправка (нужен .env)
& ".\.venv\Scripts\python.exe" daily_review.py --dry-run  # показать команду запуска
& ".\.venv\Scripts\python.exe" daily_review.py            # запустить ретроспективу сейчас
Start-ScheduledTask -TaskName 'CRM-tg-digest'             # прогнать задачу немедленно
```

## Предусловия / нюансы

- **Дайджест** шлёт через бота `tg_bridge` — нужен `.env` с `TG_BOT_TOKEN`/`TG_CHAT_ID`
  (см. `coordination/TG-BRIDGE.md`). Топик: по умолчанию General; задай `TG_DIGEST_TOPIC` в `.env`.
- **Задачи выполняются, когда вы вошли в систему** (под текущим пользователем). 23:59-окно
  ретроспективы для того и нужно — вы видите анализ. Если в это время вы не за ПК, задача
  всё равно отработает headless и положит отчёт; `-StartWhenAvailable` подхватит пропущенный
  08:00, если ПК был выключен.
- **Ретроспектива стоит токенов** (Opus, bypassPermissions, каждую ночь). Промпт правится в
  `coordination/daily-review-prompt.md` — туда добавляй/убирай, что анализировать.
- Хочешь без окна (headless-фон) — в `daily_review.py` замени запуск `wt.exe`/консоли на
  скрытый процесс; скажи — переключу.

## Убрать

```powershell
powershell -ExecutionPolicy Bypass -File register-daily-automation.ps1 -Remove
```
