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

## Команды

```powershell
npm install
npm run dev            # http://localhost:3000 (SSR ходит на backend :8000)
npm run lint           # next lint
npm test               # vitest (watch);  npm run test:run — однократно
npm run test:coverage  # vitest + coverage v8
npm run e2e            # playwright (каталог e2e/)
```

## Конвенции

- Тесты — co-located `*.test.ts` рядом с модулем в `src/lib/`; e2e — Playwright в `e2e/`.
- Чистая доменная логика (воронки, доска, форматирование) живёт в `src/lib/` и тестируется
  отдельно от React — держать её свободной от зависимостей фреймворка.