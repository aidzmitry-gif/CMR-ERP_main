# Хэндовер координатору — фикс CI PR #9 (sales-2.0-redesign)

**От:** сессия worktree `sweet-kalam-ab8156` · **Дата:** 2026-07-02 · **Статус:** готово, проверено, НЕ запушено.

Три пред-существующих провала CI PR #9 (не из Wave A/B) + бонус-провал (sidebar). Всё
починено и проверено в изолированном worktree — активный main-воркдир не трогался.

## Артефакты (локальные коммиты, без push)

| Репо | Ветка | Коммит | Родитель |
|------|-------|--------|----------|
| Суперпроект | `fix/pr9-ci` | `7b5da3a` | `8cef51d` (`sales-2.0-redesign` на момент ветвления) |
| Сабмодуль `modules/sales` (CRM.git) | `fix/pr9-rop-plan` | `951546d` | `aa9f7b6` (текущий gitlink PR) |

Изолированный worktree с применёнными правками: `D:/6 Проекты/CRM ERP/_pr9_ci_wt`
(node_modules — junction на main-воркдир; сабмодули populated офлайн; общий `.venv`).

## Что и почему

1. **frontend vitest** — `frontend/src/__tests__/pages.test.tsx`: устаревший тест после
   редизайна (НЕ баг в исходниках). `WmsPage`/`DealClient360` — валидные async **server**-
   компоненты, в проде корректны; ломались только под синхронным рендером vitest.
   Правка тест-онли: `DealsPage` получил arg `searchParams`; замоканы новые async/клиентские
   дети; `WmsPage`/`FinancePage` вынесены в отдельные await/mount-тесты.
2. **sales submodule** `modules/sales/routes.py::rop_plan_fact` (по решению владельца
   «править роут под тест»): фильтр won-сделок по `closed_date` (строка `"dd.mm.yyyy"` →
   `LIKE '%.MM.YYYY'`) вместо `stage_changed_at`; demo-дефолты `10 сделок / 150 000 BYN`
   (было 5 / 5 000 000); кривой `period` → `422` (было 400); убран unused `import calendar`.
3. **integration (Postgres-only)** — `tests/integration/conftest.py` (fixture `pg_app`) +
   `tests/integration/test_postgres.py` (клиент lifespan-relay-теста): добавлен заголовок
   `X-User-Roles: director` (как `AUTHED_HEADERS` в `tests/conftest.py`) — иначе
   `AccessControlMiddleware` fail-closed → 403 (причина всех трёх integration-падений).
4. **Бонус** — `frontend/src/components/sidebar.test.tsx`: 5-й, пред-существующий провал ВНЕ
   трёх кластеров (рельс по умолчанию свёрнут → прячет подписи). Правка тест-онли:
   `vi.stubGlobal("localStorage", …)` (в jsdom без document URL нет `localStorage`).

## Проверка (локально)

- **frontend vitest (полный):** 63 файла / 454 теста — все зелёные.
- **`pytest -m api` (полный):** 1119 passed, 98 deselected, **0 failed** (~15.5 мин).
- **`tests/test_rop_plan.py`:** 7/7. **ruff** по всем изменённым `.py`: чисто.
- Кластер 3 не гонялся (Postgres-only) — правка по инспекции + ruff.

## Интеграция (на твоё усмотрение — cherry-pick под норму проекта)

Сабмодуль-коммит `951546d` уже в общем object-store (`.git/modules/sales`) — доступен из
любого worktree этого репо. Порядок:

```bash
# 1) в modules/sales: влить/cherry-pick 951546d (или взять ветку fix/pr9-rop-plan), bump gitlink
# 2) в суперпроекте sales-2.0-redesign: cherry-pick 7b5da3a (несёт 4 файла + bump gitlink),
#    затем сверить, что gitlink modules/sales == 951546d
```

Файлы в `7b5da3a`: `pages.test.tsx`, `sidebar.test.tsx`, `tests/integration/conftest.py`,
`tests/integration/test_postgres.py`, gitlink `modules/sales`.

## Уборка

Когда заберёшь — можно снести: `git worktree remove --force "D:/6 Проекты/CRM ERP/_pr9_ci_wt"`
(там же junction `frontend/node_modules` — удалится вместе с worktree). Ветки `fix/pr9-ci`
(супер) и `fix/pr9-rop-plan` (сабмодуль) — по факту интеграции.
