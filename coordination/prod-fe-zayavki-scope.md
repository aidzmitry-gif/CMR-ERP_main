# prod-fe-zayavki — scope

## Задача (уровень 2: касаемые файлы + верификация)

Страница **«Заявки на сборку»** `/erp/production/zayavki` (Next.js App Router) — реестр
производственных нарядов как заявок, ПОВЕРХ уже живых endpoint'ов `/production/orders`,
`/production/norms`, `/production/boms` (НОВЫЙ бэкенд НЕ создавать). Заявка = наряд
(`ProductionOrder`) в ранних этапах; экран — это представление-реестр над нарядами.
Чистую логику — в `frontend/src/lib/production-zayavki.ts` под vitest. Проверка:
`npx tsc --noEmit` + `npm --prefix frontend run test:run` (ESLint НЕТ — `next lint` не использовать).

## Backend-контракт (УЖЕ на main, НЕ менять — только потреблять)

SSR — на `BACKEND_URL`; клиент — через прокси `/api/production/*`.

- `GET /production/orders` → `[{id, number, product, qty, progress, priority, owner, stage, due_date, insight, nh_per_unit, made_qty}]`
  - `stage`: `queue`|`picking`|`assembly`|`qc`|`packing`|`done` (этап наряда = статус заявки).
- `PATCH /production/orders/{id}` `{stage}` → 200 (сменить этап; «запустить в работу» = перевод этапа).
- `POST /production/orders` `{product, qty?, priority?, owner?, due_date?, ...}` → 201 (создать наряд/заявку).
- `GET /production/norms?kind=product` → `[{id, kind, title, nh, status}]` — для привязки нормы по `title==product`.
- `GET /production/boms` → `[{id, product, version, status, item_count, coverage}]` — обеспеченность по `product`.

## Что построить

1. **lib `frontend/src/lib/production-zayavki.ts`** — чистые функции (без React), под vitest:
   - тип `Order` (как контракт выше), `Norm`, `Bom` (минимальные).
   - `stageLabel(stage)` → человекочитаемый статус: queue→«Новая/очередь», picking→«Комплектация»,
     assembly→«В работе», qc→«ОТК», packing→«Упаковка», done→«Готово».
   - `stageTone(stage)` → класс/тон бейджа.
   - `normForProduct(norms, product)` → утверждённая норма по точному названию (или null).
   - `coverageForProduct(boms, product)` → обеспеченность % из BOM по названию (или null).
   - `nhTotal(order)` → `nh_per_unit * qty` и его формат (реэкспорт `formatNh` из `production-norms`).
   - KPI-счётчики реестра: всего заявок, без нормы (нет approved-нормы), без BOM, по этапам.
   - API-обёртки (паттерн `frontend/src/lib/api.ts`/`production-norms.ts`): SSR `fetchOrdersServer`,
     `fetchNormsServer`, `fetchBomsServer`; клиентские `fetchOrders`, `createOrder`, `updateOrderStage`.
2. **страница `frontend/src/app/erp/production/zayavki/page.tsx`** (Server Component):
   - `<AppShell crumbs={["ERP","Производство","Заявки на сборку"]}>`; SSR-fetch orders+norms+boms (fallback пусто),
     передать в клиентский компонент.
3. **клиентский компонент** `frontend/src/components/erp/zayavki-table.tsx` (`"use client"`):
   - KPI-плитки (всего/без нормы/без BOM/в работе)
   - реестр заявок: №, изделие, кол-во, н.ч итого, ответственный, срок, приоритет-бейдж, статус-бейдж (по этапу),
     обеспеченность % (из BOM), значок «нет нормы» если нормы нет
   - фильтр по этапу (сегмент) + поиск по № и изделию (живой, с заглушкой пустого результата)
   - действие «Запустить в работу» (PATCH stage queue→assembly) — доступно при наличии нормы; перечитывание после
   - создание заявки (форма: изделие обязательно — валидация-подсветка var(--amber), кол-во, приоритет, срок).

Образцы стиля — `frontend/src/components/erp/norms-table.tsx`, `frontend/src/lib/production-norms.ts`,
`frontend/src/components/priority-badge.tsx` (бейдж приоритета можно переиспользовать), `frontend/src/lib/api.ts`.

## LOOP CONTRACT

```yaml
scope:
  include:
    - frontend/src/lib/production-zayavki.ts
    - frontend/src/lib/production-zayavki.test.ts
    - frontend/src/app/erp/production/zayavki/page.tsx
    - frontend/src/components/erp/zayavki-table.tsx
  exclude:
    - modules/**
    - migrations/**
    - tests/**
    - core/**
    - config/**
    - frontend/src/components/sidebar.tsx     # nav уже добавлен оркестратором
    - frontend/src/lib/production-norms.ts     # читать/импортировать formatNh, НЕ менять
    - frontend/src/lib/api.ts                  # читать как образец, НЕ менять
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
  destination: coordination/prod-fe-zayavki-status.md
```

## Команды (worktree БЕЗ node_modules — установить один раз)

```powershell
npm --prefix frontend install
npm --prefix frontend run test:run          # vitest однократно — зелёные
# типы: cd frontend; npx tsc --noEmit   (НЕ npm run lint — ESLint в проекте нет)
```

## Acceptance gate

- [ ] `production-zayavki.ts`: `stageLabel`, `normForProduct`, `coverageForProduct`, `nhTotal`, счётчики — покрыты `production-zayavki.test.ts`
- [ ] `npm --prefix frontend run test:run` → 0 фейлов (не сломать существующие)
- [ ] `npx tsc --noEmit` в frontend → 0 ошибок
- [ ] Страница `/erp/production/zayavki`: реестр с фильтром/поиском, обеспеченность из BOM, привязка нормы,
      «Запустить в работу» (PATCH stage), создание заявки — через `/api/production/...`
- [ ] Тронуты ТОЛЬКО файлы include; backend/pytest/sidebar не затронуты
- [ ] Six-layer в теле коммита; status-файл заканчивается `STATE: COMPLETE`

## Anticipated failure modes
- Соблазн создать НОВЫЙ backend под заявки → СТОП: заявки = view над `/production/orders`. Новый бэкенд не нужен.
- `npm install` в worktree долгий → дождаться.
- ru-RU `Intl` NBSP (U+00A0) в числах — в тестах нормализуй `.replace(/\s/g,"")`.
- Привязка нормы/BOM — по ТОЧНОМУ совпадению `product`/`title` (как на бэке). Не выдумывать fuzzy-match.
