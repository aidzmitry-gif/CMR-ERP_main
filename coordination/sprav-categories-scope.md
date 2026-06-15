# sprav-categories — scope (экран 7: иерархия групп номенклатуры — parent_id дерево)

Читай сначала: `coordination/sprav-fe-common.md` + `coordination/reference-fe-scope.md` (строка 7).
Визуальный эталон: `spravochniki-hierarchy-preview.html`.

## Задача (уровень 2)

Порт экрана иерархии групп номенклатуры (adjacency list по parent_id). Маршрут
`/erp/spravochniki/categories`. **Гэп B закрыт** — это LIVE-экран (бэкенд категорий есть,
seed засевает демо-дерево).

Данные (LIVE) через готовый клиент:
- `fetchNomenclatureGroups(role)` → плоский список групп (SSR): `{id, code, name, parent_id, is_active}`.
- `buildCategoryTree(groups)` → дерево из плоского списка (хелпер уже есть, покрыт тестом).
- CRUD: `createNomenclatureGroup(...)`, `patchNomenclatureGroup(...)`, `archiveNomenclatureGroup(code)`
  (мутации → /api).

ltree-путь из макета — это БУДУЩАЯ Postgres-оптимизация, для UI НЕ нужен (дерево строится из
parent_id). Не пытайся его реализовать.

Верификация: `cd frontend && npx tsc --noEmit` чисто; чистая логика — под vitest.

## LOOP CONTRACT

```yaml
scope:
  include:
    - frontend/src/app/erp/spravochniki/categories/page.tsx
    - frontend/src/components/erp/spravochniki/sprav-categories.tsx
    - frontend/src/lib/spravochniki-categories.ts
    - frontend/src/lib/spravochniki-categories.test.ts
  exclude:
    - frontend/src/lib/reference-data.ts
    - frontend/src/lib/api.ts
    - frontend/src/components/sidebar.tsx
    - core/**
    - modules/**
    - migrations/**
permissions:
  repo: write-branch
  db: read-only
  llm: enabled
budget:
  max_iterations: 5
  max_runtime_minutes: 30
  max_files_changed: 4
  max_consecutive_test_failures: 3
stop:
  - same_failure_seen_twice
  - acceptance_gate_red_after_5_iters
  - file_touched_outside_scope
  - product_behavior_ambiguous
report:
  destination: coordination/sprav-categories-status.md
```

## Acceptance gate

- [ ] `/erp/spravochniki/categories` рендерит ДЕРЕВО групп (`fetchNomenclatureGroups` + `buildCategoryTree`).
- [ ] CRUD: добавить группу (`createNomenclatureGroup`), переименовать/сменить родителя (`patchNomenclatureGroup`),
      архивировать (`archiveNomenclatureGroup`) — мутации через /api, дерево обновляется.
- [ ] Graceful degrade без бэка (пусто). Вид как `spravochniki-hierarchy-preview.html`.
- [ ] `npx tsc --noEmit` чисто; vitest зелено. Только файлы scope. Six-layer. `STATE: COMPLETE`. Без push.

## Anticipated failure modes
- `buildCategoryTree` уже есть в reference-data.ts — ИСПОЛЬЗУЙ его, не пиши свой (сирота→корень уже учтён).
- Циклы/самоссылка при смене parent_id — UI должен не дать выбрать потомка родителем (мягко, не критично для демо).
