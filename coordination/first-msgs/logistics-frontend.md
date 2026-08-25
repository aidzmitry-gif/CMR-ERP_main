# logistics-frontend — задание воркеру

## Цель (Goal-Driven)

Превратить страницу-заглушку `frontend/src/app/erp/logistics/page.tsx` (сейчас это
простая доска отгрузок на 4 колонки) в **рабочую страницу логистики с вкладками**,
которая показывает уже готовый backend (`/logistics/*` API): тарифы, парк машин,
тендер, scorecard, аудит счетов. Backend трогать НЕЛЬЗЯ (он в сабмодуле и в этом
worktree недоступен) — только фронт, поверх существующих эндпоинтов.

Формулировка цели: **«напиши vitest на чистую логику трансформов → сделай его зелёным →
собери вкладки UI поверх контракта → проверь lint»**.

## Что построить

Страница `erp/logistics` с верхними вкладками (client-компонент, переключение `useState`):

1. **Доставка** — оставить существующее поведение (доска отгрузок `/logistics/shipments`
   или воронка `/logistics/board`). Можно переиспользовать `components/erp/module-board.tsx`.
2. **Тарифы** — таблица тарифов `/logistics/carrier-tariffs` (+ фильтр по зоне),
   список зон `/logistics/zones`. Колонки: перевозчик, зона, цены ≤5/≤10/≤30 кг,
   сверх-30/кг, забор, наложка %, страховка %. Деньги — в **BYN** (`formatByn`).
3. **Парк** — по перевозчику (`/logistics/carriers` для списка кодов) показать машины
   `/logistics/carriers/{code}/vehicles` и допуски `/logistics/carriers/{code}/cargo-capabilities`.
   Плюс блок «Подбор под груз» → форма (вес/категория/темп/габарит/ADR) →
   `/logistics/carriers/eligible?...` → список пригодных перевозчиков.
4. **Тендер** — список тендеров `/logistics/rfqs` (или воронка `/logistics/rfqs/board`),
   карточка тендера: приглашения `/logistics/rfqs/{id}/invites`, предложения
   `/logistics/rfqs/{id}/bids` (пометка лучшего `is_best`), кнопки действий:
   **Рассылка** (`POST .../broadcast`), **Торг** (`POST .../negotiate` {carrier_code,new_price}),
   **Заключить** (`POST .../award` {carrier_code?}) → показать созданную отгрузку.
5. **Scorecard** — таблица `/logistics/carriers/scorecard` (+ фильтр период): OTD/брак/счета/
   претензии → балл и грейд **A/B/C** (грейд — цветным бейджем).
6. **Аудит** — сводка `/logistics/costs/audit`: проверено, расхождений, **к возврату (BYN)**,
   позиции (счёт vs ожидаемый тариф, variance). И общий отчёт расходов `/logistics/costs`.

### Важные детали
- **Сидирование.** В dev таблицы пустые. На каждой вкладке с данными добавь кнопку
  «Заполнить демо» → `POST /logistics/<...>/seed` (zones/seed, carrier-tariffs/seed,
  carriers/seed, carriers/scorecard/seed, fleet/seed, costs/audit/seed, rfqs/seed),
  затем перезапрос. Это делает страницу самодостаточной без ручного бэкенда.
- **Пустой/недоступный backend.** Фетчи — в try/catch с graceful-fallback на пустой
  список (как в `lib/api.ts`). Страница НЕ должна падать, если бэкенд лежит.
- **Клиентские вызовы — через прокси `/api/logistics/*`** (он сам добавит роль).
  SSR-фетчи (если используешь) — через `BACKEND_URL` + заголовок роли (см. `lib/api.ts`).
- **Деньги — BYN.** Используй `formatByn` из `lib/format.ts` (НЕ `formatMoney` — он в ₽).

## Эталон-паттерн (прочитай эти файлы в worktree — они in-tree)
- `frontend/src/app/erp/production/norms/page.tsx` + `frontend/src/components/erp/norms-table.tsx`
  + `frontend/src/lib/production-norms.ts` + `…norms.test.ts` — канонический образец
  «SSR-страница → client-компонент → чистая lib + co-located vitest». **Следуй ему.**
- `frontend/src/components/app-shell.tsx` — обёртка с хлебными крошками (`crumbs`).
- `frontend/src/components/erp/module-board.tsx` — готовая доска (для вкладки «Доставка»).
- `frontend/src/lib/format.ts` — `formatByn`.
- `frontend/src/app/api/[...path]/route.ts` — как работает прокси `/api/*`.

## Чистая логика → в `lib/logistics-*.ts` + vitest
Вынеси в `frontend/src/lib/` чистые трансформы и покрой их `*.test.ts` (vitest):
- грейд → цвет/тон бейджа (A/B/C);
- выбор лучшего предложения (min price) и пометка `is_best`;
- агрегаты аудита (сумма к возврату = Σ положительных variance);
- форматирование тарифной строки.
Держи lib свободной от React (конвенция проекта).

## Acceptance (см. scope для LOOP CONTRACT)
- Новая чистая логика покрыта vitest, был RED→GREEN: `npx vitest run src/lib/logistics-*.test.ts` → 0 фейлов.
- `npm run lint` — без новых ошибок в тронутых файлах.
- Страница `erp/logistics` рендерит вкладки и не падает при пустом backend.
- ⚠️ **НЕ запускай `npm run build`** — он сейчас падает из-за чужой `src/app/erp/crypto/page.tsx`
  (вне твоего скоупа). Проверяйся через `vitest` + `lint` + чтение типов, не через build.
- Тронуты только файлы из include-скоупа (логистика-фронт). Шина/бэкенд/миграции — НЕ трогать.
