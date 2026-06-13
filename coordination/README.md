# coordination/ — оркестрация воркеров

Рабочая папка для `spawn_workers.py` (Windows). Оркестратор дробит большую
задачу на маленькие подзадачи и под каждую запускает воркера (`claude` в своём
окне Windows Terminal) в отдельном git-worktree.

## Поток

1. **Оркестратор пишет под каждую подзадачу два файла:**
   - `first-msgs/<name>.md` — первое сообщение воркеру (что сделать, цель).
   - `<name>-scope.md` — ТЗ с блоком `LOOP CONTRACT` (границы, budget, stop-условия).
2. **Спавн:** `python spawn_workers.py spawn <name>` — создаёт worktree
   `../crm-worker-<name>` + ветку `<name>` от `main`, копирует стандарты + scope,
   пишет skeleton-status, гасит trust-модал и запускает окно с claude. В промпт
   автоматически вшивается контракт (`worker-engineering-standards.md` +
   принципы `karpathy-guidelines`).
3. **Наблюдение:** `status` (таблица), `tail <name>` (хвост транскрипта).
   Воркер пишет прогресс в `<name>-status.md`, заканчивая баннером
   `STATE: COMPLETE` / `BLOCKED` / `NEEDS-ORCHESTRATOR-ANSWER`.
4. **Интеграция:** `integrate <name>` — мёрж ветки в `main` + boot-smoke + отчёт.
5. **Уборка:** `cleanup <name>` — снос worktree + ветки (только если всё влито).

## Память флота (грабли)

Чтобы воркеры не наступали по очереди на одни и те же грабли, есть курируемый файл
`memory/pitfalls.md`:

- **RETRIEVE** — на `spawn` его содержимое автоматически вшивается в промпт каждого
  воркера (между контрактом и задачей). В консоли: `memory: pitfalls injected (N chars)`.
- **DISTILL** — воркер сам репортит неочевидные грабли в секции `## PITFALLS-DISCOVERED`
  своего status-файла; `integrate` их авто-собирает сюда (дедуп + авто-коммит). В консоли:
  `memory: +N pitfall(s) harvested`. Ручных действий не требует.

Файл плоский и без ранжирования (Crawl-уровень) — он вшивается в КАЖДЫЙ промпт, поэтому держи
его коротким: `integrate` предупредит ⚠, если разрастётся — тогда подчисти дубли/мусор.
Пустой/удалённый файл = фича просто выключена (graceful no-op).

## Команды

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py spawn_workers.py health                 # проверка готовности
& $py spawn_workers.py list                   # известные воркеры
& $py spawn_workers.py spawn foo bar          # запустить foo и bar
& $py spawn_workers.py spawn foo --dry-run     # показать, ничего не делая
& $py spawn_workers.py status                  # статус по всем
& $py spawn_workers.py tail foo -n 30          # хвост транскрипта foo
& $py spawn_workers.py integrate foo           # влить ветку foo в main
& $py spawn_workers.py cleanup foo             # убрать worktree+ветку foo
```

## Файлы здесь

- `worker-engineering-standards.md` — контракт воркера (копируется в каждый worktree).
- `memory/pitfalls.md` — **память флота**: грабли, на которых горели прошлые воркеры;
  `spawn` вшивает их в промпт КАЖДОГО воркера (см. ниже).
- `first-msgs/<name>.md` — задания (вход оркестратора).
- `<name>-scope.md` — скоупы (вход оркестратора).
- `<name>-status.md` — статусы (пишет воркер).
- `integration-reports/` — отчёты интеграций.
- `.workers-state.json`, `.worker-*` — runtime (в `.gitignore`).

`example-healthcheck*` — демо-воркер для иллюстрации; можно удалить.

## Настройки (env, необязательно)

- `CLAUDE_CLI` — путь к claude.exe (иначе автодетект из VSCode-расширения).
- `WORKER_BASE_BRANCH` — базовая ветка (по умолчанию `main`).
- `WORKER_PERMISSION_MODE` — `bypassPermissions` (деф.) / `acceptEdits` / `default` / `auto`.
- `WORKER_MAX_CONCURRENT` — лимит одновременных воркеров (деф. 5).

## ⚠️ Безопасность (осознанное решение оператора)

Воркеры по умолчанию запускаются с `--permission-mode bypassPermissions`, потому что
они **headless** (`claude --print`) — подтвердить команду в окне некому, и любой другой
режим завис бы на первой же `pytest`/`git`/`bash`. Это значит: воркер выполняет **любую**
команду без спроса. **Git-worktree — НЕ песочница**: та же файловая система, те же креды,
та же сеть (воркер может прочитать `.env`, ходить в интернет, пушить в remote).

Security-review (2026-06-10) пометил это как HIGH; оператор сознательно принял риск —
машина и проект свои, нужен полный автоном. Снизить риск без потери автонома можно
позже через `--perm default` + allowlist инструментов или Docker-песочницу.
Понизить разово: `spawn ... --perm acceptEdits`.
