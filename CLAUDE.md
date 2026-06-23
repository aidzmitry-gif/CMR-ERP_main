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
- AI-слой за feature-flag `AIOS_AI_ENABLED` (по умолчанию выкл, mock-режим).
- Путь проекта содержит пробелы и кириллическую «С» в «Сlaude» — **всегда заключать в кавычки**.
- Coverage гоняется с `concurrency = ["thread","greenlet"]` (async-мост SQLAlchemy) — не трогать.
- Тест-маркеры: `unit` (без I/O), `api` (httpx ASGI на SQLite), `integration` (Postgres через testcontainers).


<!-- cloude-code-toolbox:mcp-skills-awareness-begin -->

### MCP & Skills awareness (Cloude Code ToolBox)

_Last synced: 2026-06-11T17:06:06.355Z._

- **Full report:** `.claude/cloude-code-toolbox-mcp-skills-awareness.md` in this workspace (auto-overwritten on each scan). Use it as ground truth for configured servers and skill folders.
- **MCP:** For **live tools** in Claude Code, enable the matching server via `/mcp`. Servers are configured in `~/.claude.json` (user) and `.mcp.json` (project).
- **When the user’s task matches a server** (e.g. Confluence work and a **Confluence** / **Atlassian** MCP is listed), **prefer that server id** and plan on tool use—not only file search.
- **Skills:** Folders below contain `SKILL.md`; attach or cite paths in chat when relevant.

#### Workspace MCP

- `d:\6 Проекты\CRM ERP\Сlaude CRM - проект\.mcp.json` _(workspace: Сlaude CRM - проект)_ — _file missing_

_No active workspace servers in mcp.json._

#### User MCP

- `C:\Users\aidzm\.claude.json` — _no servers defined_

_No active user-scoped servers in mcp.json._

#### Project skills

- **orkestrator-lead** — `d:\6 Проекты\CRM ERP\Сlaude CRM - проект\.claude\skills\orkestrator-lead` — OrkestratorLEAD — оркестратор параллельных Claude-воркеров для этого проекта (CRM ERP, Windows). Используй, когда пользователь хочет распараллелить большую задачу, разбить её на подзадачи и гонять несколько воркеров; зап

#### User skills

- **algorithmic-art** — `C:\Users\aidzm\.claude\skills\algorithmic-art` — Creating algorithmic art using p5.js with seeded randomness and interactive parameter exploration. Use this when users request creating art using code, generative art, algorithmic art, flow fields, or particle systems. C

- **brand-guidelines** — `C:\Users\aidzm\.claude\skills\brand-guidelines` — Applies Anthropic's official brand colors and typography to any sort of artifact that may benefit from having Anthropic's look-and-feel. Use it when brand colors or style guidelines, visual formatting, or company design 

- **canvas-design** — `C:\Users\aidzm\.claude\skills\canvas-design` — Create beautiful visual art in .png and .pdf documents using design philosophy. You should use this skill when the user asks to create a poster, piece of art, design, or other static piece. Create original visual designs

- **claude-api** — `C:\Users\aidzm\.claude\skills\claude-api` — |-

- **doc-coauthoring** — `C:\Users\aidzm\.claude\skills\doc-coauthoring` — Guide users through a structured workflow for co-authoring documentation. Use when user wants to write documentation, proposals, technical specs, decision docs, or similar structured content. This workflow helps users ef

- **docx** — `C:\Users\aidzm\.claude\skills\docx` — Use this skill whenever the user wants to create, read, edit, or manipulate Word documents (.docx files). Triggers include: any mention of 'Word doc', 'word document', '.docx', or requests to produce professional documen

- **frontend-design** — `C:\Users\aidzm\.claude\skills\frontend-design` — Guidance for distinctive, intentional visual design when building new UI or reshaping an existing one. Helps with aesthetic direction, typography, and making choices that don't read as templated defaults.

- **internal-comms** — `C:\Users\aidzm\.claude\skills\internal-comms` — A set of resources to help me write all kinds of internal communications, using the formats that my company likes to use. Claude should use this skill whenever asked to write some sort of internal communications (status 

- **karpathy-guidelines** — `C:\Users\aidzm\.claude\skills\karpathy-guidelines` — Behavioral guidelines to reduce common LLM coding mistakes. Use when writing, reviewing, or refactoring code to avoid overcomplication, make surgical changes, surface assumptions, and define verifiable success criteria.

- **mcp-builder** — `C:\Users\aidzm\.claude\skills\mcp-builder` — Guide for creating high-quality MCP (Model Context Protocol) servers that enable LLMs to interact with external services through well-designed tools. Use when building MCP servers to integrate external APIs or services, 

- **pdf** — `C:\Users\aidzm\.claude\skills\pdf` — Use this skill whenever the user wants to do anything with PDF files. This includes reading or extracting text/tables from PDFs, combining or merging multiple PDFs into one, splitting PDFs apart, rotating pages, adding w

- **pptx** — `C:\Users\aidzm\.claude\skills\pptx` — Use this skill any time a .pptx file is involved in any way — as input, output, or both. This includes: creating slide decks, pitch decks, or presentations; reading, parsing, or extracting text from any .pptx file (even 

- **skill-creator** — `C:\Users\aidzm\.claude\skills\skill-creator` — Create new skills, modify and improve existing skills, and measure skill performance. Use when users want to create a skill from scratch, edit, or optimize an existing skill, run evals to test a skill, benchmark skill pe

- **slack-gif-creator** — `C:\Users\aidzm\.claude\skills\slack-gif-creator` — Knowledge and utilities for creating animated GIFs optimized for Slack. Provides constraints, validation tools, and animation concepts. Use when users request animated GIFs for Slack like "make me a GIF of X doing Y for 

- **theme-factory** — `C:\Users\aidzm\.claude\skills\theme-factory` — Toolkit for styling artifacts with a theme. These artifacts can be slides, docs, reportings, HTML landing pages, etc. There are 10 pre-set themes with colors/fonts that you can apply to any artifact that has been creatin

- **web-artifacts-builder** — `C:\Users\aidzm\.claude\skills\web-artifacts-builder` — Suite of tools for creating elaborate, multi-component claude.ai HTML artifacts using modern frontend web technologies (React, Tailwind CSS, shadcn/ui). Use for complex artifacts requiring state management, routing, or s

- **webapp-testing** — `C:\Users\aidzm\.claude\skills\webapp-testing` — Toolkit for interacting with and testing local web applications using Playwright. Supports verifying frontend functionality, debugging UI behavior, capturing browser screenshots, and viewing browser logs.

- **xlsx** — `C:\Users\aidzm\.claude\skills\xlsx` — Use this skill any time a spreadsheet file is the primary input or output. This means any task where the user wants to: open, read, edit, or fix an existing .xlsx, .xlsm, .csv, or .tsv file (e.g., adding columns, computi

<!-- cloude-code-toolbox:mcp-skills-awareness-end -->
