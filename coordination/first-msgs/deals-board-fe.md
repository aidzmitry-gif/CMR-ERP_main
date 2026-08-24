Реализуй на канбан-доске сделок CRM три блока ТЗ «Сделки 2.0» — **только фронтенд**.

Эталон вёрстки — `mockup_Сделки_2.0.html` в корне репо (открой и смотри; тумблер «Подсветить
новое» подсвечивает добавляемое). Полное ТЗ блоков — `ТЗ_Блок_Сделки_2.0.md` (разделы SALES-40/43/44).
Границы, контракт API и acceptance gate — в `coordination/deals-board-fe-scope.md`.

Цель (Goal-Driven, TDD):
1. Сначала напиши/расширь co-located тесты `frontend/src/lib/board.test.ts` на чистую логику:
   - список стадий включает терминальную `lost` («Закрыто: Отказ»);
   - расчёт «взвешенной суммы» колонки = Σ(amount*probability/100);
   - фильтр «висяки» по `stage_changed_at` (старше N дней, кроме won/lost).
   Убедись, что они RED. Затем сделай зелёными минимальной реализацией в `lib/board.ts`.
2. UI по макету:
   - **SALES-40** — колонка «Закрыто: Отказ» (красная); перевод карточки в отказ → модалка
     `LoseDealModal` с обязательным выбором причины (`GET /sales/loss-reasons` + fallback-список)
     и необязательным комментом → клиент `loseDeal(id, reason_code, comment)` (`POST /sales/deals/{id}/lose`);
     кнопка/действие «выиграть» → `winDeal(id)`; на проигранной карточке плашка причины.
   - **SALES-43** — бейдж «🕒 N дн. в стадии» на карточке (из `stage_changed_at`), подсветка висяков,
     фильтр «Только висяки» в тулбаре `deals-workspace.tsx`.
   - **SALES-44** — бейдж вероятности и «≈ X ₽» взвешенно на карточке; «взвешенно: X» в шапке колонки;
     поля `probability`/`expected_close_date`/`stage_changed_at`/`lost_reason_code` в типе `Deal`
     (`lib/types.ts`) и в `mapDeal` (`lib/api.ts`).
3. Клиентские вызовы — в стиле существующего `lib/api.ts` (try/catch + fallback, `roleHeaders`,
   `cache:"no-store"`). Бэкенда может не быть (404) — UI обязан не падать (как `fetchBoardStages`).

Верификация (без живого backend):
- если нет `frontend/node_modules` — один раз `npm install` в `frontend/`;
- `npx vitest run src/lib/board.test.ts` → 0; добавь рендер-тест карточки/доски, если уместно;
- `npm run lint` — чисто по тронутым файлам;
- НЕ запускай `npm run build` (сломан на чужом `crypto/page.tsx`).

Жёсткие границы: НЕ трогай `chats-panel.tsx` (чужой воркер), `funnel/**`, `sidebar.tsx`,
`format.ts`, `app/erp/**`, `app/crm/owner/**`, `modules/**`, `*.py`. Нужен общий файл вне скоупа —
STOP и `STATE: NEEDS-ORCHESTRATOR-ANSWER` в status-файле.

Деньги — `formatMoney` (₽). Финальный баннер `STATE: COMPLETE` — только когда vitest=0 и lint чист.
