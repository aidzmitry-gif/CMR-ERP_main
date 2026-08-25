# prod-fe-analytics — scope

## Задача

Фронтенд экрана «Аналитика производства»: lib + vitest + Server-page + "use client" компонент.
Бэкенд готов (GET /production/analytics уже работает). Паттерн: как BOM.

⚠️ Компонент называется `production-analytics-view.tsx` (не `analytics-view.tsx` — то имя занято).

## LOOP CONTRACT

```yaml
scope:
  include:
    - frontend/src/lib/production-analytics.ts
    - frontend/src/lib/production-analytics.test.ts
    - frontend/src/app/erp/production/analytics/page.tsx
    - frontend/src/components/erp/production-analytics-view.tsx
  exclude:
    - frontend/src/components/sidebar.tsx
    - frontend/src/components/erp/analytics-view.tsx
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
  destination: coordination/prod-fe-analytics-status.md
```

## Acceptance gate

- [ ] `frontend/src/lib/production-analytics.ts` — типы AnalyticsData/MonthPlanFact/ScrapReason/TeamMember/TopProduct, хелперы fmtByn/fmtNh/fmtPct/kpiTone, API fetchAnalyticsServer/fetchAnalytics
- [ ] `frontend/src/lib/production-analytics.test.ts` — fmtNh/fmtPct/kpiTone граничные значения
- [ ] `frontend/src/app/erp/production/analytics/page.tsx` — Server Component, crumbs ["ERP","Производство","Аналитика производства"]
- [ ] `frontend/src/components/erp/production-analytics-view.tsx` — НЕ `analytics-view.tsx`; "use client", KPI-карточки, план/факт по месяцам, причины брака, вклад сборщиков, топ изделий
- [ ] `npx tsc --noEmit` → 0 ошибок
- [ ] `npm --prefix frontend run test:run` → 0 провалов
- [ ] sidebar.tsx НЕ тронут
- [ ] Коммит в ветке prod-fe-analytics
- [ ] STATUS завершается `STATE: COMPLETE`

## Anticipated failure modes

- Имя файла: НЕ называть `analytics-view.tsx` (занят erp/analytics) — строго `production-analytics-view.tsx`
- TypeScript: `initial: AnalyticsData | null` — компонент показывает заглушку при null
- TypeScript: `toLocaleString` в vitest может работать иначе — тест fmtByn проверяй на наличие "," и 2 знаков, не на точную строку
- Граничный тест kpiTone: 60 → amber (≥60), 59 → red (<60)
