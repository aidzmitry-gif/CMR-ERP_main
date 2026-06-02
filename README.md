# AI-First Business OS — каркас

Модульный каркас системы: **тонкое ядро-платформа + модули-плагины** (модульный
монолит). Реализованы части 1–2 дорожной карты из
[`Архитектура_и_план_AI-First_OS.md`](../Архитектура_и_план_AI-First_OS.md):
фундамент, доменная модель в БД, миграции, локальная Docker-среда. AI-слой
подключается отдельным треком позже.

Сейчас активен один модуль — `sales` (CRM): показывает, как модуль подключается к
ядру (роут, событие, workflow, права, Telegram-команда, виджет) и работает с БД.

## Структура

```
core/
  runtime/    contract.py (ModuleContract), core.py (реестр), loader.py, app.py, deps.py
  services/   config, db (async SQLAlchemy), eventbus (outbox-заглушка), temporal, auth, litellm
  db/         base.py (DeclarativeBase), repository.py (базовый CRUD)
  domain/     shared kernel (ORM): контрагент, контакт, SKU, пользователь
modules/
  sales/      module.py, routes.py, models.py (ORM, схема sales.*), schemas.py,
              repository.py, events.py, workflows.py, permissions.py, telegram.py
config/       settings.py (env, префикс AIOS_), modules.py (ENABLED_MODULES)
migrations/   Alembic: env.py + versions/ (0001 core, 0002 sales)
scripts/      seed.py (тестовые данные)
tests/        дымовые тесты каркаса + БД-тесты (на SQLite)
docker-compose.yml, Dockerfile
```

## Запуск через Docker (рекомендуется)

```powershell
docker compose up --build
```
Поднимает Postgres 16 (+pgvector), Redis, Keycloak и приложение. Приложение при
старте само применяет миграции (`alembic upgrade head`).
- API: `http://127.0.0.1:8000` (Swagger — `/docs`)
- Keycloak: `http://127.0.0.1:8080` (admin / admin)

Заполнить тестовыми данными:
```powershell
docker compose exec app python scripts/seed.py
```

## Локальный запуск (без Docker)

Нужен доступный PostgreSQL. Затем:
```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
$env:AIOS_DATABASE_URL = "postgresql+psycopg://aios:aios@localhost:5432/aios"
alembic upgrade head
python scripts/seed.py
uvicorn main:app --reload
```

Проверка: `GET /health`, `GET /system/modules`, `GET /sales/deals`,
`POST /sales/deals` (создаёт сделку и публикует событие `sales.deal.created`).

## Тесты

```powershell
pytest          # БД-тесты идут на SQLite в памяти, Postgres не требуется
ruff check .    # линт
```

## Как добавить модуль

1. Пакет `modules/<name>/` с `module.py` (реализует `ModuleContract`, фабрика `get_module()`).
2. В `register(core)` зарегистрировать роут/события/workflow/права/виджеты.
3. ORM-модели — в схеме `<name>.*` (`__table_args__ = {"schema": "<name>"}`).
4. Добавить `"<name>"` в `ENABLED_MODULES` (`config/modules.py`).
5. Создать миграцию (`alembic revision -m "<name>: init"`) и описать таблицы.

## Что заглушено и где наполняется

| Компонент | Сейчас | Наполнение |
|---|---|---|
| БД | ✓ async SQLAlchemy 2 + Alembic (части 1–2) | репозитории расширяются по модулям |
| Шина событий | внутрипроцессная | Postgres outbox + Redis Streams — часть 3 |
| Процессы (Temporal) | базовый класс, без воркера | Temporal + согласования — часть 4 |
| Auth / RBAC / MFA | Keycloak поднят в compose | интеграция в коде — часть 5 |
| 1С | — | коннектор OData (чтение) — часть 6 |
| AI (LiteLLM/агенты) | выключено | отдельный трек, Итерация 1 |
