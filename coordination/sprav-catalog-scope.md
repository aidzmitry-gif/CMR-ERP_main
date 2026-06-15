# sprav-catalog — scope (экран 1: каталог справочников + дерево отделов + хаб)

Читай сначала: `coordination/sprav-fe-common.md` (общий контракт) + `coordination/reference-fe-scope.md`
(таблица экранов, строка 1). Визуальный эталон: `spravochniki-preview.html` (+ хаб `spravochniki-preview-index.html`).

## Задача (уровень 2: касаемые файлы + верификация)

Порт экрана «Справочники — каталог»: левое дерево по отделам (Система/Общие/Продажи/…), справа —
таблица строк выбранного справочника. Это **корень** `/erp/spravochniki` и одновременно **хаб**:
вверху/в шапке — ссылки-карточки на остальные 6 экранов (rates/merge/ai/counterparty/import/categories).

Данные (LIVE) через готовый клиент `reference-data.ts`:
- `fetchReferenceCatalog(role)` → дерево по отделам (SSR).
- При выборе справочника — строки: `fetchRefRowsByEndpoint(endpoint, role)` (generic по endpoint из
  метаданных) или `fetchSimpleRef(table, …)` для простых. Хелпер `flattenCatalog` — для плоского списка.

Верификация: `cd frontend && npx tsc --noEmit` чисто; если заведёшь чистую логику — `npx vitest run` зелено.

## LOOP CONTRACT

```yaml
scope:
  include:
    - frontend/src/app/erp/spravochniki/page.tsx
    - frontend/src/components/erp/spravochniki/sprav-catalog.tsx
    - frontend/src/lib/spravochniki-catalog.ts        # опционально (чистая логика дерева/группировки) + тест
    - frontend/src/lib/spravochniki-catalog.test.ts
  exclude:
    - frontend/src/lib/reference-data.ts              # ЗАМОРОЖЕН — только импорт
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
  destination: coordination/sprav-catalog-status.md
```

## Acceptance gate

- [ ] `/erp/spravochniki` рендерит дерево отделов (из `fetchReferenceCatalog`) + таблицу строк справочника.
- [ ] Шапка-хаб со ссылками на 6 остальных маршрутов (rates/merge/ai/counterparty/import/categories).
- [ ] SSR через `currentRole()` + готовый клиент; при недоступном бэке — пустое состояние, не падает.
- [ ] Вид соответствует `spravochniki-preview.html` (токены canvas/ink/muted/brand, shadow-card, lucide).
- [ ] `npx tsc --noEmit` чисто; новая чистая логика (если есть) — под vitest, зелено.
- [ ] Тронуты только файлы scope. Six-layer в коммите. `STATE: COMPLETE` в status-файле. Без push.

## Anticipated failure modes
- SSR-fetch уходит в fallback из-за `localhost` вместо `127.0.0.1` (Class D — env-гоча; см. common §Гоча).
- Несериализуемые поля протекают Server→Client (Class B) — пробрасывай только plain JSON через `initial`.
