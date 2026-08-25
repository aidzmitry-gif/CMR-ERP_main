# Хэндофф: автоматизация флота (чек-лист продолжения после компакта)

> Полоса файлов: автоматизация/оркестратор. Снимок на 2026-06-14. Память:
> `automation-roadmap.md` (роадмап закрыт). Это — точка продолжения, читать первой.

## Сделано и УЖЕ в origin/main (push по `bbbfac4`)

- **Хуки качества:** `claude_quality_hook.py` (PostToolUse: ruff --fix + реестр тронутого),
  `claude_stop_hook.py` (Stop: ruff+tsc точечно по реестру), guard/notify — в
  `.claude/settings.json` (**этот файл НЕ коммичен** — пути хуков через `$CLAUDE_PROJECT_DIR/.venv`
  ломаются в worktree).
- **Гейт приёмки:** `acceptance_gate.py` (durable JSON, перезапускает cmd-критерии → ловит
  «галлюцинацию done»), вшит в `cmd_integrate` (merge только на зелёном). Контракт:
  `coordination/acceptance/README.md`.
- **spawn_workers.py:** тиринг моделей per-worker (`model:` в scope), per-worker MCP
  (`mcp: serena`), `integrate --all-complete`, `pitfalls-distill`, **deny-гард вшит в воркеры**
  (`--settings` на `.guard-settings.json` + STRICT, default-on, опт-аут `WORKER_GUARD=0`).
- **Наблюдаемость/утилиты:** `fleet_dashboard.py` (+ `coordination/FLEET.md`),
  `worktree_recover.py`, `scope_scaffold.py`, `readiness.py --write` (фенсед авто-блок в
  `coordination/STATUS.md`, курируемые % не трогает).
- **Ежедневно:** `tg_digest.py` (08:00: дашборд+готовность+CI → Telegram),
  `daily_review.py` (23:59: read-only `acceptEdits` сессия анализа дня →
  `coordination/daily-review/<дата>.md`; промпт `coordination/daily-review-prompt.md`),
  `register-daily-automation.ps1`, док `coordination/daily-automation.md`.
- Коммиты в origin/main: `7481a43` · `551e496` · `068af0b` · `fbcd596` · `bbbfac4`.

## ОТКРЫТО — продолжить отсюда

1. [x] **Патч гарда — ЗАКОММИЧЕН** (`d77dc03`: строка 136 = `\brm\b|\bdel\b`, активен сразу,
   бэкап `claude_guard_hook.py.bak`). Коммит делал пользователь рукой — гард самозащитой
   блокирует стейджинг себя даже у ассистента, обход не делали.
2. [x] **Ежедневные задачи — ЗАРЕГИСТРИРОВАНЫ** (`CRM-tg-digest` 08:00, `CRM-daily-review`
   23:59 — обе `State: Ready`). Было: скрипт падал на парсе (PS 5.1 читал `.ps1` без BOM как
   cp1251) → пофикшено BOM-ом, коммит `bb982b1`.
3. [x] **`.env` TG — ОК, дайджест реально отправлен** (`tg_digest.py` → «дайджест отправлен ✓»;
   `TG_BOT_TOKEN`/`TG_CHAT_ID` уже были от настройки моста).

## Долг безопасности (для порта прототипов в Next.js)

- **`sales-card-full.html`** (прототип, demo-данные) — хендлеры строятся интерполяцией
  `onclick="contactChat('${c.name}')"` / `docPreview('${dc.n}')`. На статике с захардкоженными
  данными не эксплуатируется, но при порте в React (данные с бэкенда) = XSS. При переносе —
  вешать через `addEventListener` по `dataset`-индексу, не интерполировать в `onclick`.
  Флаг от авто-security-review 2026-06-14.

## Гочи (не наступить повторно)

- Гард активен и на **интерактиве** (PreToolUse) → пиши commit-сообщения без его триггер-строк.
- `.claude/settings.json` **не коммитить** (worktree-venv).
- `bbbfac4` закрыл HIGH из push-review (воркеры под bypass шли без гарда).
