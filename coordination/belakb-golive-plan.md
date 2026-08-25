# belakb.by go-live: все экраны работают + телефония (план)

> Цель: все закоммиченные экраны реально работают на belakb.by + телефония по-настоящему функционирует.
> Источник — многоагентный аудит 2026-06-24. Хаб = чат CRM. Claude НЕ может на сервер (guard) → серверные шаги делает пользователь.
> Вывод аудита: «не работает» = в основном ДЕПЛОЙ (пересборка фронта + BACKEND_URL) + ENV телефонии, **не дыры в коде**.

## Фаза 1 — экраны живые (деплой + диагностика)
1. **Пересобрать фронт** (systemd, отдельно от docker): `cd /opt/cmr-erp && git pull && cd frontend && npm ci && npm run build && systemctl restart cmr-frontend`. (tsc локально = 0 ошибок → сборка пройдёт.)
2. **BACKEND_URL = `http://127.0.0.1:8000`** (НЕ `localhost` — IPv6 ::1 → SSR-фетч молча в пусто). Проверить `systemctl cat cmr-frontend`; если `localhost` — `systemctl edit` + `Environment=BACKEND_URL=http://127.0.0.1:8000` + daemon-reload + restart.
3. **Бэкенд жив:** `docker compose ps` (aios-app-1 healthy), `docker logs aios-app-1 | grep -i alembic` (миграции).
4. **Проверить /board ВСЕХ ERP-досок** (пустой board = тихо пустой экран): curl-loop по procurement/wms/production/hr/legal/knowledge + ModuleBoard finance/marketing/service. 404/500/пусто → Claude чинит `modules/<name>/routes.py` + сид демо-строк.

## Фаза 2 — телефония вживую (входящий screen-pop — код готов end-to-end)
Реальный вебхук: **`POST/GET /integrations/telephony/zruchna?token=…`**; исходящий: **`/integrations/telephony/originate`**. Поток: webhook → outbox → relay → `modules/sales/calls.py` → SSE `/sales/calls/stream` → окно во фронте.
1. **2 ENV на app** (`.env`/compose): `AIOS_TELEPHONY_WEBHOOK_TOKEN=<openssl rand -hex 32>`, `AIOS_TELEPHONY_ORIGINATE_URL=https://<zruchna>/client_call_gen.php`. ⚠️ пустой токен на публичном домене = fail-open (webhook примет любого).
2. **Caddy:** исключить `/integrations/telephony/*` из Basic-Auth (zruchna должна стучать без 401).
3. **Caddy:** для `/sales/calls/stream` (SSE) — `flush_interval -1` (иначе окно не всплывёт).
4. **Один воркер uvicorn** (SSE-реестр in-process; >1 воркер → окно не у того продавца).
5. **zruchna кабинет:** webhook на `https://belakb.by/integrations/telephony/zruchna?token=<секрет>` на каждый этап (in/dial→answer→hangup) с одним uniqueid; формат GET-query или form-urlencoded/JSON (НЕ multipart).
6. **Данные:** у тестовых контактов заполнить `Contact.phone`, у сделок `Deal.owner` (иначе owner не резолвится → окно не покажется, только журнал).
7. **Проверка:** curl на zruchna-webhook (TEST1) → `{ok:true}` → звонок в `/sales/calls`; curl originate → ответ АТС (не 503/502).

## Правки кода (Claude, по приоритету)
- **P1** — по результатам Фазы-1.4: дочинить пустые `/board`/ModuleBoard-эндпоинты + сид демо.
- **P1** — UX-страховка: `funnel-board.tsx`/`module-board.tsx` — показывать «нет связи с модулем» вместо тихой пустой доски.
- **P2** — исходящий click-to-call: `channels.tsx` (кнопка «Позвонить» сейчас `tel:`) → `originateCall()` в `lib/api.ts` → прокси на `/integrations/telephony/originate`. **Блокер: нужен `vnut` (внутр. номер продавца)** — откуда фронт его берёт (профиль/cookie). Без маппинга originate из UI не запустить.
- **P3** — порт 2 макетов (`sales-invoice-template`, `sales-profit-forecast`) — оба на демо-данных до 1С-коннектора → вероятно отложить.

## Входы от пользователя
- zruchna: URL инсталляции (для originate `client_call_gen.php`), как настроить webhook, реальный формат полей (пример лога одного звонка), тестовый номер + внутр. номер сотрудника (vnut).
- Basic-Auth belakb.by (для моих браузер-проверок) + добро на исключение telephony-пути.
- Как идентифицируется продавец во фронте (для owner-резолва и vnut).
- Нужны ли сейчас 2 порта (демо-данные до 1С) или отложить.

## Критерий готово
- Экраны: `/crm/{deals,deals/[id],leads,calls,owner}` + ERP-доски/таблицы показывают реальные данные (не пусто/не mock); нет тихих пустых досок.
- Телефония: тестовый входящий → окно всплывает у продавца + в журнале; исходящий → АТС звонит (если делаем originate-UI).
