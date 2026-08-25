# prod-fe-bom — scope

## Задача (уровень 2: касаемые файлы + верификация)

Страница **«Спецификации · BOM»** `/erp/production/bom` (Next.js App Router) поверх
УЖЕ живого backend-API `/production/boms`. Чистую логику — в
`frontend/src/lib/production-bom.ts` под vitest. Проверка: `npx tsc --noEmit` +
`npm --prefix frontend run test:run` (ESLint в проекте НЕТ, `next lint` не использовать).

## Backend-контракт (УЖЕ на main, НЕ менять — только потреблять)

SSR — на `BACKEND_URL`; клиент — через прокси `/api/production/*`.

- `GET /production/boms` → `[{id, product, version, status, note, item_count, coverage}]`
  - `status`: `"draft"` | `"approved"`; `coverage`: % обеспеченных позиций (int).
- `GET /production/boms/{id}` → деталь: то же + `items: [{id, bom_id, component, norm_qty, unit, stock, reserved, status}]`
  - per-item `status`: `"ok"` | `"short"` (доступно = stock−reserved ≥ norm_qty).
- `POST /production/boms` `{product, version?, note?}` → 201 (draft)
- `PATCH /production/boms/{id}` `{product?, version?, note?}` → 200 (реквизиты, статус НЕ сбрасывает)
- `POST /production/boms/{id}/approve` → 200 (409, если состав пуст)
- `DELETE /production/boms/{id}` → 204 (каскадом по позициям)
- `POST /production/boms/{id}/items` `{component, norm_qty?, unit?, stock?, reserved?}` → 201 (BOM → draft)
- `PATCH /production/bom-items/{id}` `{...}` → 200 (BOM → draft)
- `DELETE /production/bom-items/{id}` → 204 (BOM → draft)

## Что построить

1. **lib `frontend/src/lib/production-bom.ts`** — чистые функции (без React), под vitest:
   - типы `Bom = {id; product; version; status: "draft"|"approved"; note; item_count; coverage}`,
     `BomItem = {id; bom_id; component; norm_qty; unit; stock; reserved; status: "ok"|"short"}`,
     `BomDetail = Bom & {items: BomItem[]}`
   - `bomStatusLabel(status)` → «Черновик» | «Утверждена»
   - `itemStatusLabel(status)` → «В наличии» | «Дефицит»
   - `available(item)` → `stock - reserved`; `coverageTone(pct)` → класс/тон по порогам (≥100 ok, ≥80 warn, иначе bad)
   - счётчики для KPI: всего спецификаций, утверждено, черновиков, дефицитных позиций (по детали)
   - API-обёртки (паттерн как в `frontend/src/lib/production-norms.ts`): SSR `fetchBomsServer(roles?)`,
     клиентские `fetchBoms`, `fetchBom(id)`, `createBom`, `updateBom`, `approveBom`, `deleteBom`,
     `addBomItem`, `updateBomItem`, `deleteBomItem` — каждая в try/catch с безопасным fallback.
2. **страница `frontend/src/app/erp/production/bom/page.tsx`** (Server Component):
   - `<AppShell crumbs={["ERP","Производство","Спецификации · BOM"]}>` (как в `norms/page.tsx`)
   - SSR-fetch списка BOM (fallback `[]`), передать в клиентский компонент.
3. **клиентский компонент** `frontend/src/components/erp/bom-panel.tsx` (`"use client"`):
   - KPI-плитки (всего/утверждено/черновики/дефицитных позиций)
   - список спецификаций: изделие, версия, статус-бейдж, позиций, обеспеченность % (с тоном)
   - выбор спецификации → раскрытие состава: таблица (комплектующее, норма расхода+ед., склад, резерв, статус ok/short)
   - создание BOM (форма: изделие обязательно — валидация-подсветка var(--amber)), утверждение (409 не роняет UI),
     удаление; добавление позиции в состав, удаление позиции; перечитывание после действий.

Образцы стиля — строго `frontend/src/lib/production-norms.ts`, `frontend/src/components/erp/norms-table.tsx`,
`frontend/src/app/erp/production/norms/page.tsx` (они уже на main).

## LOOP CONTRACT

```yaml
scope:
  include:
    - frontend/src/lib/production-bom.ts
    - frontend/src/lib/production-bom.test.ts
    - frontend/src/app/erp/production/bom/page.tsx
    - frontend/src/components/erp/bom-panel.tsx
  exclude:
    - modules/**
    - migrations/**
    - tests/**
    - core/**
    - config/**
    - frontend/src/components/sidebar.tsx     # nav уже добавлен оркестратором
    - frontend/src/lib/production-norms.ts     # читать как образец, НЕ менять
permissions:
  repo: write-branch
  db: read-only
  llm: enabled
budget:
  max_iterations: 6
  max_runtime_minutes: 40
  max_files_changed: 4
  max_consecutive_test_failures: 3
stop:
  - same_failure_seen_twice
  - acceptance_gate_red_after_3_iters
  - file_touched_outside_scope
  - backend_change_required
  - product_behavior_ambiguous
report:
  destination: coordination/prod-fe-bom-status.md
```

## Команды (worktree БЕЗ node_modules — установить один раз)

```powershell
npm --prefix frontend install
npx --prefix frontend tsc --noEmit          # ИЛИ: cd frontend; npx tsc --noEmit
npm --prefix frontend run test:run          # vitest однократно — зелёные
```
ВАЖНО: `npm run lint` НЕ запускать (ESLint в проекте не установлен, команда зависает интерактивно).
Проверка типов = `tsc --noEmit`. Бэкенд для unit-тестов не нужен.

## Acceptance gate

- [ ] `production-bom.ts`: статус-подписи, `available`, тоны обеспеченности, счётчики, API-обёртки — покрыты `production-bom.test.ts`
- [ ] `npm --prefix frontend run test:run` → 0 фейлов (не сломать существующие)
- [ ] `npx tsc --noEmit` в frontend → 0 ошибок
- [ ] Страница `/erp/production/bom` рендерит список + раскрытие состава, CRUD спецификаций и позиций через `/api/production/...`
- [ ] Тронуты ТОЛЬКО файлы include; backend/pytest/sidebar не затронуты
- [ ] Six-layer в теле коммита; status-файл заканчивается `STATE: COMPLETE`

## Anticipated failure modes
- `npm install` в worktree долгий → дождаться; не уходить в сеть за лишним.
- Захотелось менять backend → СТОП, `NEEDS-ORCHESTRATOR-ANSWER`: контракт выше полный.
- ru-RU `Intl` разделяет тысячи NBSP (U+00A0) — в тестах нормализуй `.replace(/\s/g,"")` (см. `production-vyrabotka.test.ts`).
- Серверный компонент с мутацией-хуком → ошибка App Router: мутации только в `"use client"`-компоненте.
