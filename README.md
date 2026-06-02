# AI-First Business OS — каркас

Исполняемый скелет системы: **тонкое ядро-платформа + модули-плагины**. Соответствует
части 1 дорожной карты (минимум) и §6 «следующий шаг» из
[`Архитектура_и_план_AI-First_OS.md`](../Архитектура_и_план_AI-First_OS.md).

Сейчас в системе один модуль-заглушка — `sales` (CRM), который на живом примере
показывает, как модуль подключается к ядру: регистрирует роут, событие, пустой
workflow, права, Telegram-команду и виджет.

## Структура

```
core/
  runtime/    contract.py (ModuleContract), core.py (реестр), loader.py, app.py
  services/   config, eventbus (outbox-заглушка), temporal, db, auth, litellm
  domain/     shared kernel: контрагент, контакт, SKU, пользователь
modules/
  sales/      module.py, routes.py, models.py, events.py, workflows.py,
              permissions.py, telegram.py, migrations/
config/
  settings.py     настройки (env, префикс AIOS_)
  modules.py      ENABLED_MODULES — реестр включённых модулей
main.py           точка входа (uvicorn main:app)
tests/            дымовые тесты каркаса
```

## Запуск

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
uvicorn main:app --reload
```

Проверка:
- `GET /health` → `{"status":"ok"}`
- `GET /system/modules` → что зарегистрировали загруженные модули
- `GET /sales/ping`, `GET /sales/deals`
- `POST /sales/deals` (JSON со сделкой) → создаёт сделку и публикует событие
  `sales.deal.created` (видно в логах)
- Swagger UI: `http://127.0.0.1:8000/docs`

Тесты:

```powershell
pytest
```

Через Docker:

```powershell
docker compose up --build
```

## Как добавить модуль

1. Создать пакет `modules/<name>/` с `module.py`, реализующим `ModuleContract`,
   и фабрикой `get_module()`.
2. В `register(core)` зарегистрировать нужное: роут, события, workflow, права,
   Telegram, виджеты, хуки.
3. Добавить `"<name>"` в `ENABLED_MODULES` (`config/modules.py`).

Границы модулей (см. §2.4 архитектуры): модуль владеет своими таблицами
(схема `<name>.*`), межмодульное общение — только через события или
зарегистрированные интерфейсы, общие сущности берутся из `core/domain`.

## Что заглушено и где наполняется

| Компонент | Сейчас | Наполнение |
|---|---|---|
| Шина событий | внутрипроцессная | Postgres outbox + Redis Streams — часть 3 |
| Процессы (Temporal) | базовый класс, без воркера | Temporal + согласования — часть 4 |
| БД | URL в настройках | SQLAlchemy 2, миграции — часть 2 |
| Auth / RBAC / MFA | заглушка | Keycloak — часть 5 |
| 1С | — | коннектор OData (чтение) — часть 6 |
| AI (LiteLLM/агенты) | выключено | отдельный трек, Итерация 1 |

AI-слой навешивается позже за feature-flag и не требует переписывания ядра.
