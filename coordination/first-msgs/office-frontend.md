# office-frontend — задание воркеру

## Цель (Goal-Driven)

Довести реальную страницу офис-менеджера `frontend/src/app/erp/office/page.tsx`
(сейчас — голая воронка `FunnelBoard`) до рабочего состояния по трём пунктам:
1) показывать **статус трекинга доставки** по документу (он приходит из логистики);
2) дать действие **«Заявка перевозчику»** (создаёт заявку на доставку по РБ);
3) исправить валюту: **BYN вместо ₽**.

Формулировка цели: **«напиши vitest на чистую логику (статус трекинга/гард тяжёлого
груза) → сделай зелёным → собери office-панель доставки + модалку заявки → lint»**.

## Что построить

На странице `erp/office` рядом с существующей воронкой добавить **office-специфичную
client-секцию «Доставка и документы»** (новый компонент `components/erp/office-*.tsx`),
которая:

- Фетчит `/office/docs` и показывает по каждому документу: компания, стадия,
  **перевозчик** (`delivery`), **статус трекинга** (`docs_status` — туда логистика пишет
  текст вида «Доставка: В пути · Минск → Гомель», а на финале «Доставлено, закрываем
  документы»). Подсвечивай трекинг-строку как живой статус.
- Для документов на ранней стадии (`ready`/`shipped`) — кнопка **«Заявка перевозчику»** →
  модалка: выбор перевозчика из `/office/carriers`, поля направление/дата забора/контакт/
  комментарий → `POST /office/docs/{id}/carrier-request` → показать выданный `log_ref`.
- **Гард тяжёлого груза:** у office-перевозчика есть флаг `heavy`. Если вес документа
  (`weight`, строка — распарсить в число) ≥ **300 кг**, а выбранный перевозчик не
  `heavy` — показать предупреждение и не давать отправить (зеркалит макет
  `modules/office/office-manager.html`).

### BYN вместо ₽
- В `office/page.tsx` лейбл поля сейчас «Сумма, ₽» → сделать «Сумма, BYN».
- В своей office-панели деньги форматируй через `formatByn` из `lib/format.ts`.
- ⚠️ Глобальный `formatMoney` (он в ₽) и общий `FunnelBoard` **НЕ трогай** — если кажется,
  что валюту надо чинить в общем компоненте/форматтере, это делает оркестратор:
  напиши `NEEDS-ORCHESTRATOR-ANSWER`, не лезь в shared-файлы.

### Важные детали
- **Клиентские вызовы — через прокси `/api/office/*`** (он добавит роль). Фетчи в try/catch
  с graceful-fallback на пустой список (как в `lib/api.ts`). Страница не падает при лежащем backend.
- Не ломай существующую воронку — добавляешь рядом, не переписываешь общий `FunnelBoard`.

## Эталон-паттерн (прочитай в worktree — in-tree)
- `frontend/src/app/erp/production/norms/page.tsx` + `components/erp/norms-table.tsx`
  + `lib/production-norms.ts` + `…norms.test.ts` — образец «SSR-страница → client-компонент
  → чистая lib + co-located vitest». Следуй ему.
- `frontend/src/app/erp/office/page.tsx` — текущая страница (её и дорабатываешь).
- `frontend/src/components/app-shell.tsx`, `lib/format.ts` (`formatByn`),
  `frontend/src/app/api/[...path]/route.ts` (прокси).
- `modules/office/office-manager.html` — **НЕДОСТУПЕН** в worktree (в сабмодуле нет, но
  office in-tree — попробуй прочитать; если нет — ориентируйся на это ТЗ): там эталон
  модалки заявки перевозчику и гард ≥300 кг.

## Чистая логика → `lib/office-*.ts` + vitest
- парсинг `weight` (строка → кг) и предикат «нужен тяжёлый перевозчик» (≥300 кг);
- классификация трекинг-статуса (в пути / доставлено / нет данных) по `docs_status`;
- проверка «можно ли отправить заявку» (перевозчик подходит под вес).
Покрой `*.test.ts` (vitest), держи свободной от React.

## Acceptance (LOOP CONTRACT — в scope)
- `npx vitest run src/lib/office-*.test.ts` → 0 фейлов (был RED→GREEN).
- `npm run lint` — без новых ошибок в тронутых файлах.
- `erp/office`: видна секция доставки с трекингом, работает модалка заявки, гард ≥300 кг,
  валюта BYN; при пустом backend не падает.
- ⚠️ **НЕ запускай `npm run build`** — он падает из-за чужой `crypto/page.tsx`. Проверка — vitest+lint.
- Тронуты только office-фронт файлы; shared `FunnelBoard`/`format.ts`/`api.ts`/бэкенд — НЕ тронуты.

## API-контракт `/office/*`
- `GET /office/docs` → `[{id,number,company,title,amount,delivery,docs_status,priority,owner,stage,next_step,op_date,region,weight,address,logistics_ref,overdue_days}]` (amount — BYN; `weight` — строка)
- `GET /office/board` → FunnelBoardOut (уже потребляется текущим `FunnelBoard`)
- `GET /office/carriers` → `[{id,name,type,rating,eta,price_from,zone,heavy}]` (heavy — берёт тяжёлый груз)
- `POST /office/docs/{id}/carrier-request` body `{carrier,region,pickup_date,contact,comment}` → `{ok,log_ref,carrier,region,doc}`
- `PATCH /office/docs/{id}` body `{stage}` → OfficeDocOut
- `POST /office/docs` body OfficeDocCreate → OfficeDocOut
- Стадии: `ready → shipped → docs → await_pay → paid`.
