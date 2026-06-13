# Грабли проекта (PITFALLS) — курируемый список

> Этот файл **вшивается в первое сообщение КАЖДОГО воркера** автоматически
> (`spawn_workers.py`). Здесь — острые края, на которых уже горели прошлые
> воркеры. Прочитай ПЕРЕД работой и не наступай повторно.
>
> **Пополняется автоматически:** воркеры репортят грабли в секции `## PITFALLS-DISCOVERED`
> своего status-файла, а `integrate` их сюда авто-собирает (дедуп + коммит). Ручные правки
> тоже можно. Держи список коротким — каждая строка вшивается в КАЖДЫЙ промпт; раздуется —
> `integrate` предупредит, тогда подчисти.
>
> Формат записи: **СИМПТОМ** → причина → **ЛЕЧЕНИЕ**.

---

## Общее

1. **Путь проекта с пробелами и кириллицей** (`…\Сlaude CRM - проект`). Незакавыченный
   путь рвёт команды и `Set-Location`. → **Всегда заключай пути в кавычки** (PowerShell: `'…'`).

2. **Python — только через venv.** Запускай `& ".\.venv\Scripts\python.exe" …`,
   а не голый `python` (его может не быть в PATH / быть не тот).

## Backend (FastAPI · async SQLAlchemy 2 · Alembic)

3. **`no such column …` на старте или в тестах** — `create_all` НЕ мигрирует уже
   существующий `dev.db` (SQLite-режим). → Пересоздай:
   `Remove-Item .\dev.db; & ".\.venv\Scripts\python.exe" scripts/seed.py`.
   (Источник истины схемы Postgres — миграции Alembic; SQLite-автосоздание — только dev.)

4. **Репозитории НЕ коммитят.** `core/db/repository.py` не делает `commit` — границей
   транзакции владеет вызывающий код (роут/workflow). Не добавляй `commit`/`flush` в репозиторий.

5. **Новый/правленый модуль — строго по образцу `sales`** (`modules/sales/module.py`):
   наследник `ModuleContract` + фабрика `get_module()`, регистрация через фасад `core`
   (`include_router`/`subscribe`/…), ORM-схема в `__table_args__ = {"schema": "<name>"}`,
   имя пакета в `ENABLED_MODULES` (`config/modules.py`). Модули НЕ лезут во внутренности
   друг друга — только через `core`/события.

6. **9 модулей — git submodules** (sales, procurement, production, wms, logistics, finance,
   marketing, service, hr). Правка такого модуля = коммит в ЕГО репозиторий + обновление
   указателя в суперпроекте. Обычный коммит в корне НЕ подхватит изменения внутри сабмодуля.

7. **Тесты идут на SQLite в памяти, Postgres не нужен:** `pytest`. Маркеры: `unit` / `api` /
   `integration`. Coverage гоняется с `concurrency = ["thread","greenlet"]` (async-мост
   SQLAlchemy) — **не трогай** эту настройку.

## Frontend (Next.js App Router · TS · Tailwind · vitest)

8. **`npm run lint` НЕ отработает** — `eslint`/`eslint-config-next` НЕ в зависимостях и
   нет конфига (`next lint` свалится/попросит доустановить). → Проверяй типы
   `npx tsc --noEmit` и тесты `npm run test:run` (vitest), а не lint.

9. **В свежем worktree НЕТ `frontend/node_modules`** (воркер на ветке от `main`, а
   `node_modules` в `.gitignore`) → `tsc`/`vitest`/`build` упадут. → Подними junction на
   главный репозиторий (быстро, без `npm install`):
   ```powershell
   cmd /c mklink /J "frontend\node_modules" "d:\6 Проекты\CRM ERP\Сlaude CRM - проект\frontend\node_modules"
   ```

10. **SSR-фетчи молча уходят в fallback при локальном запуске** (доска/KPI/матрица доступа
    пустые) — Node резолвит `localhost` в IPv6 `::1`, а uvicorn слушает IPv4. → Запускай фронт
    с `$env:BACKEND_URL="http://127.0.0.1:8000"` (именно `127.0.0.1`, не `localhost`).
    В Docker-стеке адрес задан явно — там неактуально.

## AI-слой

11. **AI за feature-flag `AIOS_AI_ENABLED`** (по умолчанию OFF → mock-режим). Не считай
    LLM-вызовы боевыми; тесты не должны зависеть от живого AI.
