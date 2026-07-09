# CMR-ERP project audit

Дата среза: 2026-07-09.

## Что уже собрано

- Backend: FastAPI + SQLAlchemy async + Alembic, модульный монолит через `core.runtime` и `modules/*`.
- Frontend: Next/React, Vitest, Playwright, компонентная CRM/ERP-витрина.
- Активные домены: sales, leads, integrations, procurement, production, wms, logistics, finance, marketing, service, hr, office, legal, knowledge.
- Инфраструктура: Docker Compose, production host через Tailscale, авто-миграции при старте приложения.
- Контроль качества: pytest, ruff, Vitest, e2e Playwright; тестовая база в основном SQLite/in-memory.

## Сильные стороны

- Ядро отделено от бизнес-модулей: модули регистрируют роуты, события, права и виджеты через контракт.
- Есть явная матрица доступа и проверки на уровне роутов для чувствительных `/system` операций.
- Домен покрыт большим числом backend и frontend тестов, включая интеграционные сценарии модулей.
- Коннекторы вынесены отдельным слоем, есть state store, smoke-команды и тесты на атомарность/idempotency.
- Документация по серверу и deployment уже рядом с кодом, а не только в переписке.

## Основные риски

- Рабочее дерево перегружено артефактами: скриншоты, html-макеты, runtime logs и локальные temp/cache директории смешаны с кодом.
- Много незакоммиченных правок в разных подсистемах одновременно; трудно отделять готовый продуктовый код от экспериментов.
- Модули подключены как submodule/worktree, при этом `git status` показывает lock/permission warnings по `.git/modules/*`.
- Тесты зависят от файловых атомарных операций; в ограниченном sandbox они падают на `os.replace`, SQLite disk I/O и cleanup temp.
- Frontend tooling на Windows/sandbox может падать на `spawn EPERM` при загрузке Vite/Vitest config.

## Сделанные улучшения

- Убран неиспользуемый импорт в `tests/test_connectors_core.py`, после чего `ruff check core config connectors tests --no-cache` проходит чисто.
- Pytest cache provider отключен через `pyproject.toml`, чтобы проверки не падали на недоступных cache-директориях.
- Добавлена sandbox-friendly фикстура `tmp_path` в `tests/conftest.py`: тесты получают уникальную папку без teardown cleanup, что совместимо со средами без delete permissions.
- В `.gitignore` добавлены локальные временные директории `.tmp_pytest/` и `.tmp_ruff_cache/`.
- В `.gitignore` и `.dockerignore` добавлены runtime logs и локальная `dev_calls.db`, чтобы они не попадали в коммиты и Docker build context.
- В ignore добавлены `pytest-cache-files-*/`, чтобы `git status` не пытался обходить временные каталоги pytest с ограниченными правами.
- В `.dockerignore` добавлены frontend build/test artifacts (`coverage`, `test-results`, Playwright report, tsbuildinfo), чтобы backend image context не раздувался локальными проверками.

## Проверка

- Backend subset вне sandbox: `24 passed, 1 warning`.
- Frontend Vitest вне sandbox: `66 test files passed`, `503 tests passed`.
- Ruff вне sandbox/sandbox with `--no-cache`: `All checks passed`.

## Рекомендуемый следующий шаг

1. Разделить репозиторий на три зоны: product code, design/mockups, runtime artifacts.
2. Почистить git-status: отдельно закоммитить готовые фичи, отдельно оставить WIP, исключить generated assets/logs.
3. Добавить короткую CI-команду smoke: `ruff`, backend subset, frontend unit subset.
4. Проверить `.git/modules/*/index.lock` и права на submodules, чтобы Git не жил в состоянии постоянного lock warning.
5. После стабилизации дерева прогнать полный pytest и Playwright на dev host или CI, где нет sandbox-ограничений файловой системы.
