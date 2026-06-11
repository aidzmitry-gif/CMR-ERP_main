# Frontend — контекст для Claude

Next.js (App Router) + TypeScript + Tailwind. UI для CRM/ERP поверх backend FastAPI.

## Структура

- `src/app/` — маршруты App Router: `crm/` (deals, leads, owner), `erp/` (analytics,
  crypto, finance, hr, …). Серверные компоненты ходят в backend на SSR.
- `src/lib/` — API-клиент и доменная логика: `api.ts`, `board.ts`, `funnel.ts`,
  `funnel-api.ts`, `funnel-configs.ts`, `format.ts`, `types.ts`, `mock-data.ts`.
  У каждого модуля рядом лежит `*.test.ts` (vitest).
- `src/components/` — переиспользуемые компоненты (канбан на `@dnd-kit/core`, иконки `lucide-react`).

## Backend wiring

- Базовый URL backend — `process.env.BACKEND_URL ?? "http://localhost:8000"` ([src/lib/api.ts](src/lib/api.ts)).
- SSR-компоненты обращаются к API сервера; данные сериализуемы (Server→Client) —
  следить, чтобы в пропсы клиентских компонентов не утекали несериализуемые поля.
- **Локально вне Docker** запускать с `BACKEND_URL=http://127.0.0.1:8000`: Node (SSR-fetch)
  резолвит `localhost` в IPv6 `::1`, а uvicorn слушает IPv4 → без этого SSR-фетчи (доска/KPI/
  матрица доступа) молча уходят в fallback. В Docker-стеке адрес сервиса задан явно — неактуально.
- **Доступ по ролям:** матрица «роль→модули» — единый источник на backend (`config/access.py`,
  эндпоинт `/system/access`). Текущая dev-роль хранится в cookie `aios_role` (переключатель в
  подвале сайдбара); SSR-фетчи шлют её через [src/lib/role-server.ts](src/lib/role-server.ts),
  клиентские вызовы — через прокси [src/app/api/[...path]/route.ts](src/app/api/[...path]/route.ts).

## Команды

```powershell
npm install
$env:BACKEND_URL="http://127.0.0.1:8000"; npm run dev   # :3000; 127.0.0.1, не localhost (IPv6) — см. Backend wiring
npm run lint           # next lint
npm test               # vitest (watch);  npm run test:run — однократно
npm run test:coverage  # vitest + coverage v8
npm run e2e            # playwright (каталог e2e/)
```

## Конвенции

- Тесты — co-located `*.test.ts` рядом с модулем в `src/lib/`; e2e — Playwright в `e2e/`.
- Чистая доменная логика (воронки, доска, форматирование) живёт в `src/lib/` и тестируется
  отдельно от React — держать её свободной от зависимостей фреймворка.