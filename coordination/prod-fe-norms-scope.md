# prod-fe-norms — scope

## Задача (уровень 2: касаемые файлы + верификация)

Сделать страницу **«Нормы и нормативы»** производства во фронте (Next.js App Router):
`/erp/production/norms` — справочник норм нормо-часов на изделия/операции, поверх уже
живого backend-API `/production/norms`. Чистую доменную логику вынести в
`frontend/src/lib/production-norms.ts` и покрыть vitest. Прогнать lint + `test:run`.

## Backend-контракт (УЖЕ на main, НЕ менять — только потреблять)

Базовый префикс `/production` (SSR — на `BACKEND_URL`, клиент — через прокси `/api/production/*`):

- `GET /production/norms?kind=product|operation` → `[{id, kind, title, nh, status, note}]`
  - `kind`: `"product"` | `"operation"`; `nh`: число (нормо-часы, float);
  - `status`: `"none"` (нет нормы, nh=0) | `"pending"` (на утверждении) | `"approved"` (утверждена)
- `POST /production/norms` `{title, kind?, nh?, note?}` → 201 `{...norm}` (nh>0 ⇒ pending, nh=0 ⇒ none)
- `PATCH /production/norms/{id}` `{title?, nh?, note?}` → 200 (смена nh возвращает в pending)
- `POST /production/norms/{id}/approve` → 200 (409, если nh≤0 — норму без значения утвердить нельзя)
- `DELETE /production/norms/{id}` → 204

## Что построить

1. **lib `frontend/src/lib/production-norms.ts`** — чистые функции (без React), под vitest:
   - тип `Norm = {id; kind: "product"|"operation"; title; nh; status: "none"|"pending"|"approved"; note}`
   - `normStatusLabel(status)` → «Нет нормы» | «На утверждении» | «Утверждена»
   - `formatNh(nh)` → русский формат: `10 → "10"`, `7.5 → "7,5"`, `0 → "—"` (как `_nh_fmt` в backend)
   - `filterByKind(norms, kind)` и счётчики (всего, на утверждении, без нормы) для KPI-плиток
   - API-обёртки (клиент, через `/api/production/...`, паттерн как в `frontend/src/lib/api.ts`):
     `fetchNorms(kind?)`, `createNorm(input)`, `updateNorm(id, patch)`, `approveNorm(id)`, `deleteNorm(id)`
     — каждая в try/catch с безопасным fallback, как соседи в `api.ts`.
2. **страница `frontend/src/app/erp/production/norms/page.tsx`** (Server Component):
   - обёртка `<AppShell crumbs={["ERP","Производство","Нормы и нормативы"]}>` (как в `production/page.tsx`)
   - SSR-fetch норм с бэка (BACKEND_URL) с fallback на `[]`; передать в клиентский компонент
   - таблица норм: вид (изделие/операция), название, н.ч (русский формат), статус (бейдж по статусу)
   - переключатель вида product/operation, KPI-плитки (всего / на утверждении / без нормы)
3. **клиентский компонент** `frontend/src/components/erp/norms-table.tsx` (`"use client"`):
   - действия через lib: создать (форма с валидацией непустого названия), правка nh inline,
     «Утвердить» (кнопка; для nh=0 backend вернёт 409 — показать аккуратно, не падать), удалить
   - перезагрузка списка после действий
4. **nav**: в `frontend/src/components/sidebar.tsx` в подменю `production` добавить пункт
   `{ label: "Нормы и нормативы", href: "/erp/production/norms" }` (1 строка).

Стиль и паттерны — строго как в существующем фронте (AppShell, серверный fetch на `BACKEND_URL`
с fallback, клиентские мутации через `/api/...`, бейджи/таблицы — как в `components/`).

## LOOP CONTRACT

```yaml
scope:
  include:
    - frontend/src/lib/production-norms.ts
    - frontend/src/lib/production-norms.test.ts
    - frontend/src/app/erp/production/norms/page.tsx
    - frontend/src/components/erp/norms-table.tsx
    - frontend/src/components/sidebar.tsx
  exclude:
    - modules/**
    - migrations/**
    - tests/**            # backend pytest — не твоё
    - core/**
    - config/**
    - frontend/src/app/erp/production/page.tsx   # канбан цеха — не трогать
    - frontend/src/lib/api.ts                    # читать как образец, НЕ менять
permissions:
  repo: write-branch
  db: read-only
  llm: enabled
budget:
  max_iterations: 6
  max_runtime_minutes: 40
  max_files_changed: 5
  max_consecutive_test_failures: 3
stop:
  - same_failure_seen_twice
  - acceptance_gate_red_after_3_iters
  - file_touched_outside_scope
  - backend_change_required
  - product_behavior_ambiguous
report:
  destination: coordination/prod-fe-norms-status.md
```

## Команда запуска (worktree БЕЗ node_modules — сначала установи зависимости)

```powershell
# из корня СВОЕГО worktree, один раз:
npm --prefix frontend install
# проверки:
npm --prefix frontend run test:run      # vitest однократно — твои тесты зелёные
npm --prefix frontend run lint          # next lint — без ошибок
```
Бэкенд для unit-тестов НЕ нужен (vitest гоняет чистую логику lib без сети). Страницу/компонент
build-ить не обязательно, но lint обязан проходить.

## Acceptance gate

- [ ] `production-norms.ts`: `normStatusLabel`, `formatNh` (10→«10», 7.5→«7,5», 0→«—»),
      `filterByKind`, счётчики и API-обёртки — покрыты `production-norms.test.ts`
- [ ] `npm --prefix frontend run test:run` → 0 фейлов (включая существующие тесты — не сломать)
- [ ] `npm --prefix frontend run lint` → без ошибок
- [ ] Страница `/erp/production/norms` рендерит таблицу норм (SSR-fetch с fallback на пусто),
      переключатель вида, KPI-плитки; клиентский компонент делает CRUD через `/api/production/...`
- [ ] Пункт «Нормы и нормативы» добавлен в подменю production в `sidebar.tsx`
- [ ] Тронуты ТОЛЬКО файлы из include; backend/pytest не затронут
- [ ] Six-layer в теле коммита; status-файл заканчивается `STATE: COMPLETE`

## Anticipated failure modes
- `npm install` в worktree долгий/падает по сети → повторить; не уходить в сеть за лишним.
- Захотелось менять backend (`modules/production` / роуты) → СТОП, `NEEDS-ORCHESTRATOR-ANSWER`:
  контракт API фиксирован выше, его достаточно.
- Серверный компонент тянет клиентский хук → ошибка App Router: мутации только в `"use client"`-компоненте.
- Несериализуемые пропсы Server→Client → держать данные простыми (массив Norm).
- Русский формат: `formatNh` — запятая как десятичный разделитель, целое без дробной части.
