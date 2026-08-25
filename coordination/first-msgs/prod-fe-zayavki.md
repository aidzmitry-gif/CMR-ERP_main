# Задание: фронт-страница «Заявки на сборку» производства (Next.js)

Ты строишь экран `/erp/production/zayavki` как реестр-представление над УЖЕ живыми
наряд­ами `/production/orders` (+ `/norms`, `/boms`). НОВЫЙ backend создавать НЕ нужно —
заявка = наряд (`ProductionOrder`) в ранних этапах. Backend менять НЕЛЬЗЯ.

**Goal-Driven**: реестр заявок (статус по этапу наряда, привязка нормы по названию,
обеспеченность из BOM, «Запустить в работу» = PATCH stage, создание): чистая логика в
`frontend/src/lib/production-zayavki.ts` (под vitest) + Server-страница + клиентский
компонент → `npm --prefix frontend run test:run` = 0 и `npx tsc --noEmit` (в frontend) = 0.

**Читай первым** свой scope: `coordination/prod-fe-zayavki-scope.md` — полный backend-контракт
(какие живые endpoint'ы потреблять), файлы, acceptance gate, команды. Образцы стиля (на main):
`frontend/src/components/erp/norms-table.tsx`, `frontend/src/lib/production-norms.ts`,
`frontend/src/lib/api.ts`, `frontend/src/components/priority-badge.tsx`.

Жёстко: НЕ создавай backend и НЕ трогай `modules/**`, `migrations/**`, `tests/**`, `core/**`,
`sidebar.tsx` (nav готов), `production-norms.ts`/`api.ts` (только читать). Worktree без
node_modules — `npm --prefix frontend install` один раз. `npm run lint` НЕ запускать (ESLint
нет) — типы через `npx tsc --noEmit`. Нужна правка бэкенда — СТОП, `NEEDS-ORCHESTRATOR-ANSWER`.
