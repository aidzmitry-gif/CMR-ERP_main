# Scope: sales-e2e-board

## LOOP CONTRACT
- include: frontend/e2e/**, frontend/playwright.config.ts, frontend/src/components/kanban/deals-workspace.tsx (только data-testid атрибуты, без изменения логики/JSX-структуры)
- exclude: modules/sales/, modules/finance/, modules/procurement/, modules/wms/, modules/logistics/, modules/marketing/, modules/service/, modules/hr/, modules/production/, core/, config/, migrations/, scripts/seed.py, frontend/src/lib/**, frontend/src/components/kanban/deal-card.tsx, frontend/src/components/kanban/create-deal-modal.tsx, frontend/src/components/kanban/lose-deal-modal.tsx, frontend/src/components/kanban/deal-drawer-preview.tsx
model: sonnet
- max_iterations: 8
- max_files_changed: 14
- stop_conditions:
  - npm run e2e (frontend/, headless) = 0 failed
  - npx tsc --noEmit (frontend/) = OK

## Ограничения
- НЕ трогать backend/модули/миграции — это чисто frontend e2e-полоса
- data-testid можно добавлять ТОЛЬКО как точечные атрибуты в `deals-workspace.tsx`
  (`stage-column-*`, `deal-card-*`) — НЕ менять поведение доски, НЕ трогать drag-and-drop
  логику, НЕ переписывать фильтры/воронки под тесты
- НЕ трогать `e2e/auth.setup.ts` (общий dev-логин, от него зависят остальные specs) без
  крайней необходимости; если правка неизбежна — не ломать существующие
  `deal-card.spec.ts` / `leads.spec.ts` / `navigation.spec.ts`
- НЕ ставить новую зависимость — `@playwright/test` уже в devDependencies
  (`frontend/package.json`); `npx playwright install chromium` — установка браузера, не пакета
- НЕ использовать `waitForLoadState("networkidle")` — `/crm/*` держат постоянный SSE
  (EventSource в `app-shell.tsx`), networkidle никогда не наступит → зависание
- НЕ пушить (пуш делает координатор)
- Коммит — обычный коммит в суперпроекте (frontend НЕ submodule)
