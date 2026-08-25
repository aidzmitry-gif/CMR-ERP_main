# Задание: фронт-страница «Спецификации · BOM» производства (Next.js)

Ты строишь экран `/erp/production/bom` поверх УЖЕ живого backend-API `/production/boms`.
Backend менять НЕЛЬЗЯ — контракт зафиксирован в твоём scope.

**Goal-Driven**: справочник спецификаций (состав изделия, обеспеченность ok/short,
статусы draft/approved) во фронте: чистая логика в `frontend/src/lib/production-bom.ts`
(под vitest) + Server-страница + клиентский CRUD-компонент состава →
`npm --prefix frontend run test:run` = 0 и `npx tsc --noEmit` (в frontend) = 0.

**Читай первым** свой scope: `coordination/prod-fe-bom-scope.md` — полный backend-контракт,
файлы, acceptance gate, команды. Образцы стиля (уже на main): `frontend/src/lib/production-norms.ts`,
`frontend/src/components/erp/norms-table.tsx`, `frontend/src/app/erp/production/norms/page.tsx`.

Жёстко: НЕ трогай `modules/**`, `migrations/**`, `tests/**` (pytest), `core/**`, `sidebar.tsx`
(nav уже добавлен), `production-norms.ts` (только читать). Worktree без node_modules —
`npm --prefix frontend install` один раз. `npm run lint` НЕ запускать (ESLint нет, зависнет) —
проверка типов через `npx tsc --noEmit`. Нужна правка бэкенда — СТОП, `NEEDS-ORCHESTRATOR-ANSWER`.
