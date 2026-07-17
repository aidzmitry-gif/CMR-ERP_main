# AI-First Business OS — контекст для Claude

> **Приоритеты платформы (конституция — [PLATFORM.md](PLATFORM.md)):**
> 1) деньги собственнику (Харькович Д.С.) → 2) безопасность (сохранить деньги) →
> 3) функциональность → 4) эстетика. При конфликте — побеждает меньший номер.

Модульный монолит: **тонкое ядро-платформа + модули-плагины**. Backend — FastAPI +
async SQLAlchemy 2; frontend — Next.js (см. [frontend/CLAUDE.md](frontend/CLAUDE.md)).
Карта частей дорожной карты — `README.md` и `../Архитектура_и_план_AI-First_OS.md`.

## Архитектура (как устроено ядро)

- `core/runtime/` — `contract.py` (`ModuleContract`), `core.py` (реестр+фасад `Core`),
  `loader.py` (импорт по `ENABLED_MODULES`), `app.py` (фабрика `create_app`), `deps.py`.
- `core/services/` — общие сервисы (`db`, `eventbus`, `approvals`, `temporal`, `auth`,
  `litellm`, `onec`, `stock`). Многие — заглушки с устойчивым контрактом; их
  наполняют по частям дорожной карты, **вызывающий код не меняется**.
- `core/db/` — `base.py` (`DeclarativeBase`), `repository.py` (базовый CRUD).
- `core/domain/` — shared kernel ORM (контрагент, контакт, SKU, пользователь, outbox, audit).
- `modules/<name>/` — модули-плагины. `config/` — `settings.py`, `modules.py`.

## Как добавить/менять модуль (паттерн)

1. Пакет `modules/<name>/` с `module.py`: класс-наследник `ModuleContract` +
   фабрика `get_module() -> ModuleContract`. `name` = имя пакета.
2. В `register(core)` регистрировать возможности через фасад: `core.include_router`,
   `core.subscribe(event_type, handler)`, `core.register_workflow`, `core.declare_permissions`,
   `core.declare_role`, `core.register_telegram`, `core.register_widget`, `core.on_startup`.
3. ORM-модели — в схеме модуля: `__table_args__ = {"schema": "<name>"}`.
4. Добавить `"<name>"` в `ENABLED_MODULES` ([config/modules.py](config/modules.py)).
5. Миграция: `alembic revision -m "<name>: init"` и описать таблицы.
- **Эталон-образец** — модуль `sales` ([modules/sales/module.py](modules/sales/module.py)).
  Модули НЕ обращаются к внутренностям друг друга — только через `core`/события (§2.4).

## Данные и транзакции

- Репозитории (`core/db/repository.py`) **не коммитят** — границей транзакции владеет
  вызывающий код (роут/workflow). Сессия в роутах — через `Depends(get_session)` ([deps.py](core/runtime/deps.py)).
- События — **transactional outbox**: `event_bus.emit(session, type, payload)` пишет в
  `outbox_event` в той же транзакции. Доставку делает фоновый цикл (`_background_loop`,
  поллинг каждые 2с) → `relay_once` → подписчики + проекция в `AuditLog`.
- Обработчик события с 2 параметрами получает `(payload, ctx)` (ctx = сессия+сервисы,
  для AI-агентов), с 1 — только `payload`.

## Стиль кода — лестница лени (минимальный код по умолчанию)

Перед тем как писать код, остановись на первой подходящей ступени:
1. Нужно ли это вообще? (YAGNI) — спекулятивное пропусти, скажи одной строкой.
2. Есть в stdlib? — используй.
3. Покрывает нативная фича платформы (`<input type=date>`, CSS вместо JS, ограничение БД вместо app-кода)? — используй.
4. Решает уже стоящая зависимость? — используй; новую не добавляй ради пары строк.
5. Можно одной строкой? — одной строкой.
6. Только потом — минимум кода, который работает.

- Удаление важнее добавления; меньше файлов; без абстракций/конфигов/фабрик «про запас» (интерфейс с одной реализацией — заинлайнить, пока нет второй).
- НЕ упрощать: валидацию на границах доверия, обработку ошибок против потери данных, безопасность, доступность, явно запрошенное.
- Намеренное упрощение помечать `# ponytail:` с названным потолком и путём апгрейда (напр. `# ponytail: O(n²)-скан, индекс если вырастет`).
- **Исключение — платформенный каркас ядра.** `ModuleContract`, реестр/фасад `Core`, репозитории-не-коммитят, transactional outbox, Alembic как источник истины — это намеренные абстракции под 9 модулей, а не оверинжиниринг. Лестница их НЕ «упрощает».

## Команды

```powershell
# Dev без Docker (SQLite): таблицы создаются автоматически, минуя Alembic
.\.venv\Scripts\Activate.ps1
$env:AIOS_DATABASE_URL = "sqlite+aiosqlite:///./dev.db"; $env:PYTHONPATH = "."
python scripts/seed.py            # наполнить демо-данными
python -m uvicorn main:app --port 8000

# Postgres (источник истины схемы — Alembic)
$env:AIOS_DATABASE_URL = "postgresql+psycopg://aios:aios@localhost:5432/aios"
alembic upgrade head

docker compose up --build         # полный стек: Postgres+pgvector, Redis, Keycloak, app
pytest                            # БД-тесты на SQLite в памяти, Postgres не нужен
ruff check .                      # линт (line-length 100, py312, isort)
```

**Перед коммитом — стандарт ревью:** `/code-review` (баги/корректность) → `/simplify`
(чистка: reuse/упрощение/удаление, применяет правки). Эта связка закрывает и «ревью на
оверинжиниринг» — отдельный инструмент не нужен.

## Тиринг моделей и усилий (сабагенты — по умолчанию НЕ на дорогой)

Канон — [coordination/MODEL-TIERING.md](coordination/MODEL-TIERING.md). Коротко: сабагенты и
Workflow-стадии тирятся ПО ЗАДАЧЕ, не наследуют дорогую модель главного цикла вслепую.
- **Модель:** Haiku 4.5 (механика: поиск/чтение/скаффолд/форматирование) → Sonnet 5 (ревью/код/
  порт/тесты) → Opus 4.8 (деньги/безопасность/схема-миграции/контракты/судья). **Fable 5 — ВНЕ
  тиринга** (флагман $10/$50, 10× Haiku): не дефолт, звать точечно, только если Opus не тянет.
- **Effort (Faster↔Smarter) — ОРТОГОНАЛЕН модели:** `low` механика · `medium` фича · `high` ревью/
  деньги-логика · `xhigh`/`max` архитектура/судья. Дефолт: `Haiku+low` рутина, `Sonnet+medium` фича,
  `Opus+high..xhigh` T1-зона.
- Явно **понижать** тир/эффорт на механике (экономия), явно **повышать** на деньгах/безопасности/
  миграциях (там ошибка дороже токенов — PLATFORM.md #1–2). Качество на Sonnet держит ГЕЙТ
  (`lane_check.py`/`alembic heads==1`/adversarial-verify), не модель.

## Репозитории и ветки (навигация — ВАЖНО)

> Где что лежит и куда коммитить/пушить. Держать в актуальном состоянии при заведении веток.

- **Главный/суперпроект** — `origin` = `github.com/aidzmitry-gif/CMR-ERP_main.git`. Держит
  указатели на submodules. **Все HTML-макеты `sales-*.html`, `*-prototype/`, `frontend/`,
  `coordination/`, `config/`, `core/` — в КОРНЕ этого репо** (не в submodule). Сюда же —
  макеты закупок/маркетинга/контролёра/производства.
- **9 submodules** (`.gitmodules`): `modules/sales` = `CRM.git` (бэкенд Сделок, **без макетов**),
  procurement=`ZAK-3`, production=`PRO-4`, wms=`SKL-5`, logistics=`LOG-6`, finance=`fin-7`,
  marketing=`MAR-8`, service=`SER-POD-9`, hr=`HR-10`. Правка модуля = коммит в его репо +
  обновление указателя в суперпроекте. Клонирование/CI — с `--recurse-submodules`.
- **Ветки origin (суперпроект):** `main` (общая), `theme/dark-mode-cd` (дизайн-система C/D в коде),
  `ci/node24`, `sales-2.0-redesign-push` (редизайн HTML-макетов Sales 2.0 на 2 темы — макеты в корне).
- **⚠️ Параллельные сессии** пишут в локальный `main` (закупки, справочники, дизайн-система).
  Поэтому локальный `main` обгоняет `origin/main` на чужие незапушенные коммиты. **Правило пуша:**
  пушить ТОЛЬКО свой коммит — cherry-pick его на чистую ветку от `origin/main` (через временный
  worktree), не утаскивая чужие коммиты. Push/коммит — только по явной просьбе пользователя.
- **🔴 НИКАКОГО `git commit --amend` / `reset` / `rebase` на ОБЩЕЙ ветке** (`main`,
  `sales-2.0-redesign`, `theme/dark-mode-cd`). Несколько сессий коммитят в неё разом → HEAD
  дрейфует под тобой → amend затрёт ЧУЖОЙ коммит (так и случилось 2026-06-27: аменд снёс коммит
  CRM-сессии, чинил через `reset --soft` + reflog). Всегда делай **НОВЫЙ** коммит. Гард в
  `prepare-commit-msg`-хуке блокирует amend на общей ветке (обход, если HEAD точно твой:
  `AIOS_ALLOW_AMEND=1 git commit --amend`). **Лучше — своя ветка/worktree на сессию**
  (`git worktree add ../_wt_<полоса> -b sales-2.0-<полоса>`): HEAD не дрейфует, amend безопасен,
  пуш — cherry-pick своего на чистую ветку от origin (правило выше).
- **Git-хуки координации** (`.githooks/`, `core.hooksPath` уже настроен): `pre-commit`/`post-commit`/
  `pre-push` (advisory: журнал `coordination/.activity.local.md` + флаги хотспот/миграция/событие
  шины/субмодуль) и `prepare-commit-msg` (блок amend на общей ветке). Логика — `scripts/coordination_hook.py`.
  ПЕРЕД коммитом в общую ветку: `git status` — staged ТОЛЬКО свои файлы (`git add` по именам, НЕ `add .`);
  `git log -1` — HEAD твой? Сверься с `coordination/ACTIVE-SESSIONS.md` (полосы/хотспоты/счётчик миграций).
- **🗺️ Карта связей — [coordination/DEPENDENCY-MAP.md](coordination/DEPENDENCY-MAP.md).** Сверяться
  ПЕРЕД параллельной работой: граф межмодульных событий, shared-kernel данные, 4 файла-хотспота
  (`config/settings.py`, `config/modules.py`, `core/services/__init__.py`, `core/db/base.py`),
  чек-лист перед новой сессией. Верифицирована адверсариально (Opus). Обновлять при смене связей.

## Конвенции и подводные камни

- **9 модулей — git submodules** (`.gitmodules`: sales, procurement, production, wms,
  logistics, finance, marketing, service, hr → отдельные репозитории GitHub). Правка
  такого модуля = коммит в его репозиторий + обновление указателя в суперпроекте.
  Клонирование/CI — с `--recurse-submodules`.
- **Источник истины схемы PostgreSQL — миграции Alembic.** В SQLite-режиме таблицы
  создаются автоматически (в SQLite нет схем) — это только для dev. `create_all` **не мигрирует**
  существующий файл: если модели изменились, старая `dev.db` падает (напр. `no such column …`).
  Лечение — удалить `dev.db` и пересоздать (`Remove-Item .\dev.db; python scripts/seed.py`).
- Настройки — Pydantic Settings, env-префикс `AIOS_`, файл `.env` ([config/settings.py](config/settings.py)).
- **Браузер/скриншоты — только Playwright MCP.** Встроенный Browser pane ненадёжен для
  скриншотов (таймауты 30с на любых страницах) — годен лишь для навигации и чтения DOM-текста.
  HTML-макеты открывать ТОЛЬКО через http.server (launch.json `static-mockups`, :8791) —
  `file://` в Playwright заблокирован. Playwright настроен с `--isolated` (нет конфликта
  профиля между сессиями); если после обновления плагина вернулось «Browser is already in
  use» — заново добавить `--isolated` в args плагина playwright.
- **Импорт в .py — одним Edit вместе с использующим кодом** (или после него): ruff-хук
  откатывает неиспользованный импорт (F401), цикл «добавил → вырезало → добавил заново»
  повторялся 11 раз/нед.
- **Просмотр через Bash (sed/cat/grep) не заменяет Read.** Перед Edit — Read; для общих
  файлов флота (авто-память MEMORY.md, `coordination/*`) — Read непосредственно перед Edit
  в том же ходе (параллельные сессии/линтер меняют их под тобой).
- **Авто-память MEMORY.md — append-only:** новая заметка = отдельный файл + СТРОКА В КОНЕЦ
  индекса; не переписывать чужие записи — файл общий для параллельных сессий.
- **Однословная команда пользователя** («делай», «давай», «сделай») = «продолжай последний
  утверждённый пункт плана/PLAN.md», а НЕ повод заново анализировать модуль.
- **Гигиена сессий:** ≥2 компакций или ≥3 дня жизни сессии → закрыть на ближайшей вехе
  (пуш/отчёт) и начать новую от `coordination/COORDINATOR-RESUME.md`. Многодневные
  мега-сессии дали 91% всего расхода cache-read за неделю аудита.
- **Фоновые процессы убиваются на границе хода сессии** — dev-серверы поднимать только через
  launch.json / `scripts/dev-servers.ps1` (идемпотентный, health-poll; `-Restart`, `-Demo`);
  пересборка dev.db — `scripts/reseed-dev.ps1`. Гейты одной командой: `npm run gates`
  (typecheck+lint+vitest по изменённым; `gates:full` — весь сьют) и `scripts/gate-py.ps1`
  (ruff+pytest, аргументы пробрасываются в pytest).
- **`cmd /c` ест цепочки `&&` с кириллическими путями** — mklink/rmdir вызывать отдельными
  командами.
- AI-слой за feature-flag `AIOS_AI_ENABLED` (по умолчанию выкл, mock-режим).
- Путь проекта содержит пробелы и кириллическую «С» в «Сlaude» — **всегда заключать в кавычки**.
- Coverage гоняется с `concurrency = ["thread","greenlet"]` (async-мост SQLAlchemy) — не трогать.
- Тест-маркеры: `unit` (без I/O), `api` (httpx ASGI на SQLite), `integration` (Postgres через testcontainers).
