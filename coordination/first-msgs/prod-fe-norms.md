# Задание: фронт-страница «Нормы и нормативы» производства (Next.js)

Ты строишь экран `/erp/production/norms` поверх УЖЕ живого backend-API `/production/norms`.
Backend менять НЕЛЬЗЯ — контракт зафиксирован в твоём scope.

**Goal-Driven**: справочник норм нормо-часов (изделия/операции, статусы
none → pending → approved) во фронте: чистая логика в `frontend/src/lib/production-norms.ts`
(под vitest) + Server-страница + клиентский CRUD-компонент + пункт в сайдбаре →
`npm --prefix frontend run test:run` = 0 и `npm --prefix frontend run lint` без ошибок.

**Читай первым** свой scope: `coordination/prod-fe-norms-scope.md` — там полный
backend-контракт API (что потреблять), список файлов, acceptance gate, команды.
Затем как образцы стиля: `frontend/src/app/erp/production/page.tsx` (AppShell + SSR),
`frontend/src/lib/api.ts` (паттерн серверного fetch на `BACKEND_URL` + клиентских мутаций
через `/api/...` с try/catch-fallback), `frontend/CLAUDE.md` (команды и конвенции).

Жёстко: НЕ трогай `modules/**`, `migrations/**`, `tests/**` (backend pytest), `core/**`,
канбан `production/page.tsx` и `lib/api.ts` (только читать). Worktree без node_modules —
сделай `npm --prefix frontend install` один раз перед тестами. Нужна правка бэкенда для
зелёного — СТОП, `NEEDS-ORCHESTRATOR-ANSWER` (контракт API уже полный).
