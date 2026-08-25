# prod-fe-planning — scope

## Задача

Фронтенд экрана «Планирование · план/факт» производства: lib + vitest + Server-page + "use client" матрица.
Бэкенд готов (миграция 0036). Paттерн: как BOM (`production-bom.ts` + `bom-panel.tsx`).

## LOOP CONTRACT

```yaml
scope:
  include:
    - frontend/src/lib/production-plan.ts
    - frontend/src/lib/production-plan.test.ts
    - frontend/src/app/erp/production/planning/page.tsx
    - frontend/src/components/erp/plan-matrix.tsx
  exclude:
    - frontend/src/components/sidebar.tsx
    - modules/**
    - migrations/**
    - tests/**
    - coordination/**
permissions:
  repo: write-branch
  db: none
  llm: enabled
budget:
  max_iterations: 5
  max_runtime_minutes: 25
  max_files_changed: 4
  max_consecutive_test_failures: 3
stop:
  - same_failure_seen_twice
  - acceptance_gate_red_after_3_iters
  - file_touched_outside_scope
  - product_behavior_ambiguous
report:
  destination: coordination/prod-fe-planning-status.md
```

## Acceptance gate

- [ ] `frontend/src/lib/production-plan.ts` существует: типы PlanBoard/PlanRow/PlanCell/PlanTotals, хелперы loadTone/fmtNh, API fetchPlanServer/fetchPlan/putPlanCell/upsertPosition/deletePosition
- [ ] `frontend/src/lib/production-plan.test.ts` существует: loadTone(70/100/101) + fmtNh граничные
- [ ] `frontend/src/app/erp/production/planning/page.tsx` — Server Component, crumbs ["ERP","Производство","Планирование · план/факт"]
- [ ] `frontend/src/components/erp/plan-matrix.tsx` — "use client", матрица план/факт, редактируемые ячейки, KPI, CSS-бары мощности, добавление/удаление позиции
- [ ] `npx tsc --noEmit` → 0 ошибок TypeScript
- [ ] `npm --prefix frontend run test:run` → 0 провалов (production-plan.test.ts зелёный)
- [ ] sidebar.tsx НЕ тронут
- [ ] Коммит в ветке prod-fe-planning
- [ ] STATUS завершается `STATE: COMPLETE`

## Anticipated failure modes

- TypeScript: импорт `currentRole` из `@/lib/role-server` — этот файл существует, проверь путь
- TypeScript: PlanBoard может прийти как `null` от SSR (бэк недоступен) — PlanMatrix должен обрабатывать `initial: PlanBoard | null`
- Компонент: input в ячейке матрицы — не забудь `type="number"` и `min={0}`; blur → PUT; не дублировать запросы
- Тест: `fmtNh(0)` → "0,0" (не "0") — проверить `.toFixed(1).replace(".", ",")`
