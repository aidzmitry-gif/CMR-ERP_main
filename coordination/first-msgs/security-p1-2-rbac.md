# Воркер: security-p1-2-rbac — доказать write-RBAC инвариант свипом + закрыть дыры ядра

## Цель (Goal-Driven)
Построить **автоматический 403-свип** по всем зарегистрированным роутам приложения, который
доказывает инвариант безопасности (PLATFORM.md #2): **write-эндпоинт (POST/PUT/PATCH/DELETE) модуля,
к которому у роли нет доступа, обязан вернуть 403 ДО выполнения роута.** Если свип найдёт write-роут,
который текущий гейт НЕ ловит — закрыть дыру **на уровне ядра** (не по-модульно).
Готово, когда: `pytest -m api tests/test_security_rbac_sweep.py` зелёный · полный `pytest -m api` не сломан ·
`import main` ок · `ruff` чисто.

## Контекст
**РАБОЧАЯ ДИРЕКТОРИЯ: твой worktree** (spawn_workers уже поставил cwd в `crm-worker-security-p1-2-rbac`
на ветке `security-p1-2-rbac`). НЕ упоминай путь главного репо и НЕ делай `cd` в `…\Сlaude CRM - проект`
— иначе закоммитишь в общую ветку в обход изоляции. Все git-команды — в текущем worktree.

Это код **ЯДРА/суперпроекта** — коммит прямо в суперпроект, submodule-ей и миграций тут НЕТ.

Ключевые реальные символы (прочитай их первыми — НЕ выдумывай):
- **`core/runtime/access.py`** — `AccessControlMiddleware.dispatch`: уже режет 403 по префиксу модуля
  для ЛЮБОГО метода (в т.ч. write) до роута. `OPEN_PREFIXES` (health/system/approvals/telegram/docs/
  marketing seo webhook) — всегда открыты. `build_prefix_map(core)` даёт `[(prefix, package)]`.
  `roles_from_request` → `get_current_user(request).roles`.
- **`config/access.py`** — `ACCESS_MATRIX` (роль→UI-слаги), `PACKAGE_TO_SLUG` (+ обратно `PACKAGE_TO_SLUG`),
  `is_package_allowed(package, roles)`, `SUPER_ROLES` (admin/director/commercial), `USERS`/`ROLE_ORDER`.
  Роли приходят заголовком `X-User-Roles` (dev).
- **`core/services/auth.py`** — `get_current_user` (dev=заголовок, fail-closed → «Гость»). ТОЛЬКО читать.
- Как поднять app в тесте: `from main import app` (под `AIOS_AUTH_MODE=dev AIOS_ENVIRONMENT=dev`),
  ASGI через `httpx.AsyncClient(transport=ASGITransport(app=app))` — как в существующих `-m api` тестах
  (найди образец: `grep -rl "ASGITransport" tests/`).

## Шаг 1 — собрать карту write-роутов
Из `app.routes` (FastAPI) собери все пары `(path, method)` с методами POST/PUT/PATCH/DELETE.
Для каждого пути определи модуль-пакет по самому длинному подходящему префиксу из `build_prefix_map(core)`
(достань core тем же способом, что и middleware — посмотри `core/runtime/app.py`, как оно строит prefixes
и кладёт core в `app.state`). Пропусти пути под `OPEN_PREFIXES` и пакеты без слага.

## Шаг 2 — свип-тест `tests/test_security_rbac_sweep.py`
Параметризуй по write-роутам. Для каждого:
- **negative:** подбери роль, которой этот модуль НЕ доступен по `ACCESS_MATRIX` (напр. для `crm`
  подойдёт `warehouse`; проверь через `is_package_allowed`). Запрос с `X-User-Roles: <эта роль>` →
  **assert 403** (тело роута не должно исполниться; body-валидация НЕ важна — важен именно 403 гейта).
- **positive (sanity):** роль-владелец (или `director` из SUPER_ROLES) → статус **НЕ 403**
  (может быть 422/400/404 из-за пустого тела — это ок, главное не 403).
Тест должен САМ находить роуты (не хардкод списком) — тогда новый незащищённый роут его уронит.

## Шаг 3 — закрыть дыры ЯДРА (только если свип красный)
Если какой-то write-роут модуля не получает 403 от неавторизованной роли:
- пакет не в `PACKAGE_TO_SLUG` → добавь маппинг в `config/access.py` (НЕ трогая значения ACCESS_MATRIX);
- роут ошибочно под `OPEN_PREFIXES`, но state-changing → сузь `OPEN_PREFIXES` (осторожно: не сломай health/webhook);
- гейт не покрывает метод/путь → минимально поправь `core/runtime/access.py`.
НЕ добавляй `require_permission` в модули (это Wave F P1-3). НЕ ослабляй существующую защиту.

## Запуск
```powershell
$env:AIOS_AUTH_MODE="dev"; $env:AIOS_ENVIRONMENT="dev"; $env:PYTHONPATH="."
$env:AIOS_DATABASE_URL="sqlite+aiosqlite:///:memory:"
& ".\.venv\Scripts\python.exe" -m pytest -m api tests/test_security_rbac_sweep.py -q
& ".\.venv\Scripts\python.exe" -m pytest -m api -q          # полный слой не сломан
& ".\.venv\Scripts\python.exe" -c "import main; print('import OK')"
& ".\.venv\Scripts\python.exe" -m ruff check .
```

## DoD
- `pytest -m api tests/test_security_rbac_sweep.py` = 0 failed · полный `-m api` не сломан · `import main` ок · `ruff` чисто.
- Правки ТОЛЬКО в `tests/test_security_rbac_sweep.py` (+ при дыре: `config/access.py`/`core/runtime/access.py`).
- Коммит в суперпроект (submodule-ей/миграций нет). НЕ пушить.
- `STATE: COMPLETE` в `coordination/security-p1-2-rbac-status.md`. Упёрся → `STATE: NEEDS-ORCHESTRATOR-ANSWER` + вопрос.
