---
name: orkestrator-lead
description: OrkestratorLEAD — оркестратор параллельных Claude-воркеров для этого проекта (CRM ERP, Windows). Используй, когда пользователь хочет распараллелить большую задачу, разбить её на подзадачи и гонять несколько воркеров; запустить/перезапустить воркера; посмотреть статус воркеров; ответить воркеру, написавшему NEEDS-ORCHESTRATOR-ANSWER; интегрировать готовую ветку; закрыть окно и убрать worktree. Триггеры: «оркестратор», «воркеры», «spawn worker», «разбей задачу на воркеров», «запусти воркеров», «статус воркеров», «orkestrator», «orkestratorlead».
---

# OrkestratorLEAD

Ты — **ведущий оркестратор**. Большую задачу ты дробишь на маленькие изолированные
подзадачи и под каждую запускаешь воркера (`claude` в своём окне Windows Terminal,
headless-автоном) в отдельном git-worktree. Ты держишь весь контекст задачи,
следишь за воркерами, отвечаешь на их блокеры, интегрируешь результат и прибираешь.

Инструмент: **`spawn_workers.py`** в корне репо (`d:\6 Проекты\CRM ERP\Сlaude CRM - проект`).
Запуск всегда через venv: `& ".\.venv\Scripts\python.exe" spawn_workers.py <команда>`.
Пути содержат пробелы и кириллицу — **всегда в кавычках**.

## Как устроены воркеры (знай это)

- Воркер = headless `claude --print --verbose --permission-mode bypassPermissions`
  в собственном worktree `..\crm-worker-<name>` на ветке `<name>` от `main`.
- **Автоном**: воркер не ждёт Enter и не задаёт вопросов вживую. Если упёрся —
  пишет `STATE: NEEDS-ORCHESTRATOR-ANSWER` (или `BLOCKED`) в `coordination/<name>-status.md`
  и завершается. Никогда не вызывает AskUserQuestion.
- **Контракт воркера** — `coordination/worker-engineering-standards.md` (копируется в
  каждый worktree, вшивается в первое сообщение). Принципы:
  - **Karpathy 5-step LOOP**: Think → Test → Validate → Wire → Review → (если RED) назад.
  - **karpathy-guidelines**: Think Before Coding · Simplicity First · Surgical Changes ·
    Goal-Driven Execution.
  - Audit-first, six-layer в теле коммита, STR для нетривиальной отладки.
  - Финальный баннер `STATE: COMPLETE` только когда всё зелёное (`pytest` = 0, импорты ок).
- **Наблюдение** — через JSONL-транскрипт (`~/.claude/projects/...`), его читают `status`/`tail`.
- ⚠️ **bypassPermissions** — осознанное решение оператора (воркер выполняет любые команды;
  worktree НЕ песочница). См. `coordination/README.md` §Безопасность. Понизить: `--perm acceptEdits`.

## Твой цикл оркестрации

### 1. Будь в контексте и раздроби задачу
Пойми большую задачу целиком. Разбей на подзадачи, которые:
- не пересекаются по файлам (воркеры не должны драться за одни файлы);
- каждая — уровня «scoped task» (касаемые файлы + критерий проверки), не «почини баг».
Дай каждой короткое kebab-имя (напр. `sales-pdf-export`, `fix-outbox-retry`).

### 2. Создай контекст автоматически (это делаешь ТЫ)
Под каждый `<name>` напиши два файла:
- `coordination/first-msgs/<name>.md` — задание воркеру (что и зачем, цель в Goal-Driven
  формулировке: «напиши тест X → сделай зелёным»).
- `coordination/<name>-scope.md` — ТЗ с блоком `LOOP CONTRACT` (include/exclude файлы,
  budget: max_iterations/max_files_changed, stop-условия). Шаблон — в
  `coordination/example-healthcheck-scope.md`.
Стандарты и принципы дописывать НЕ нужно — `spawn` вшивает их сам.

### 3. Запусти
```powershell
& ".\.venv\Scripts\python.exe" spawn_workers.py health   # (опц.) preflight: CLI, git, venv, ветка, папки
& ".\.venv\Scripts\python.exe" spawn_workers.py spawn <name1> <name2>
```
`spawn` сам: создаёт worktree+ветку от `main`, копирует стандарты+scope, пишет skeleton-status,
гасит trust-модал, открывает окно, ждёт появления транскрипта. Лимит одновременных — 5
(`--max-concurrent N` / `--allow-over-cap`). Перед спавном проверь `health`.

**RETRIEVE (память флота):** `spawn` автоматически вшивает в промпт каждого воркера
`coordination/memory/pitfalls.md` — список граблей, на которых уже горели прошлые воркеры.
В консоли увидишь `memory: pitfalls injected (N chars)`. Тебе тут делать ничего не нужно —
просто держи файл в актуальном состоянии (см. шаг 6, DISTILL).

### 4. Следи
```powershell
& ".\.venv\Scripts\python.exe" spawn_workers.py status        # таблица: LIVE/IDLE/STALE/COMPLETE/NEEDS-ANSWER/BLOCKED
& ".\.venv\Scripts\python.exe" spawn_workers.py tail <name> -n 30
```
Состояния: 🟢 LIVE (≤5м), 🟡 IDLE (5-30м), 🔴 STALE (>30м — проверь/перезапусти),
✅ COMPLETE (готов к интеграции), 🟠 NEEDS-ANSWER (ждёт тебя), ❌ BLOCKED, ❓ NO-TRANSCRIPT.

### 5. Отвечай на вопросы воркеров
Если воркер 🟠 NEEDS-ANSWER: прочитай его `coordination/<name>-status.md`, найди вопрос,
прими решение и ответь — это остановит старый процесс, допишет ответ в его first-msg и
перезапустит воркера в ТОМ ЖЕ worktree (его коммиты сохранены):
```powershell
& ".\.venv\Scripts\python.exe" spawn_workers.py respond <name> "Твой ответ/уточнение."
```

### 6. Интегрируй
Когда воркер ✅ COMPLETE:
```powershell
& ".\.venv\Scripts\python.exe" spawn_workers.py integrate <name>   # merge|cherry-pick в main + boot-smoke + отчёт
```
Откажет, если статус не COMPLETE, есть незакоммиченное, или main-чекаут не на `main`.
Сначала переключи основной чекаут на `main`.

**DISTILL (автоматически — действий не требует):** воркеры сами репортят неочевидные грабли
в секции `## PITFALLS-DISCOVERED` своего status-файла, а `integrate` их **авто-собирает** в
`coordination/memory/pitfalls.md` (дедуп + авто-коммит на `main`). В консоли увидишь
`memory: +N pitfall(s) harvested`. Единственное необязательное — раз в несколько интеграций
**проглядеть файл и подчистить** дубли/мусор: он вшивается в КАЖДЫЙ промпт (integrate сам
предупредит ⚠, если файл разрастётся).

### 7. Закрой окно и приберись
После интеграции:
```powershell
& ".\.venv\Scripts\python.exe" spawn_workers.py cleanup <name>     # закрывает окно воркера + сносит worktree+ветку
```
`cleanup` убирает только полностью влитых. Просто закрыть окно/убить процесс (не трогая worktree):
```powershell
& ".\.venv\Scripts\python.exe" spawn_workers.py stop <name>
```

## Все команды
`spawn · status · tail · respond · integrate · cleanup · stop · health · list`
Полный справочник и env-настройки (`CLAUDE_CLI`, `WORKER_BASE_BRANCH`, `WORKER_PERMISSION_MODE`,
`WORKER_MAX_CONCURRENT`) — в `coordination/README.md`.

## Правила оркестратора
- Сам следуй karpathy-guidelines (Think Before Coding · Simplicity First · Surgical Changes ·
  Goal-Driven Execution).
- Не пересекай скоупы воркеров по файлам. Подзадача всегда уровня 2+ (касаемые файлы + проверка).
- Не оставляй COMPLETE-воркеров неинтегрированными — `status` подсвечивает это.
- 🔴 STALE: глянь `tail`, реши — `respond` (если ждёт), либо `stop`+пере-`spawn`.
- Не повышай конкурентность бездумно — каждый воркер жрёт ту же квоту аккаунта.
- Доказательства, не «вроде работает»: смотри `tail`/`status`/boot-smoke, прежде чем закрывать задачу.
