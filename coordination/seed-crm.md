<!-- Транзитный засев для переоткрытия полосы. Не коммитить. Сгенерирован координатором 2026-06-27, сверен адверсариально. -->
# CRM / Сделки (sales-2.0) — переоткрытие

Ты — полоса **CRM / Сделки**, модуль `sales` (submodule `modules/sales` → CRM.git). Ветка суперпроекта: `sales-2.0-redesign`. Запускайся из корня суперпроекта; правки субмодуля — через `git -C modules/sales`.

## Зона
- Бэк `modules/sales/**`; фронт `frontend/src/app/crm/deals/**`, `frontend/src/components/deal-*`, доска в `frontend/src/components/kanban/**`, `frontend/src/lib/api.ts` (**ХОТСПОТ** — захват у координатора).

## Состояние (проверено в коде/git)
- Сабмодуль `modules/sales` HEAD `518495b` (всё закоммичено): SALES-50 (телефония/журнал звонков/резолв продавца/SSE), SALES-51 (резерв под счёт, миграция 0042), SALES-53 (договор по шаблону+УНП, миграция 0043).
- Фронт-доска уже сделана и в main: SALES-40/43/44 (взвешенный прогноз, бейдж стадии, колонки вероятн./взвешенно), CurrencyProvider (валюта/ЮЛ), маржа из 1С. **Эти блоки НЕ переделывать — только доводка/верификация** (`board.ts` уже содержит пороги, weightedAmount, стадии вкл. `cond_lost`).
- ⚠️ Деньги — **BYN через CurrencyProvider** (`components/kanban/currency-context.tsx`), НЕ ₽. `formatMoney` отдаёт BYN. Не хардкодь символ валюты, бейдж пиши «≈ X» через текущую валюту провайдера.
- Эндпоинты уже есть: `/loss-reasons`, `/deals/{id}/lose`, `/deals/{id}/win`; поля Deal: probability/expected_close_date/stage_changed_at/lost_reason_code. graceful-fallback в UI оставить, но бэк НЕ называть отсутствующим.

## Незакоммичено (кто где грязный — точно)
- В рабочем дереве **САБМОДУЛЯ** `modules/sales`: `CLAUDE.md, ai.py, routes.py, schemas.py` — черновики security-review. В суперпроекте видно как `m modules/sales`.
- В **СУПЕРПРОЕКТЕ** фронт полосы: `M frontend/src/app/crm/deals/[id]/page.tsx`, `?? frontend/src/components/deal-linked-deals.tsx` — твои.
- ⚠️ `M frontend/src/components/source-tag.tsx` и `funnel-board.tsx` могут пересекаться с чатом **Справочники** (провенанс MDM/SourceTag) — перед коммитом проверь авторство, `git add` по именам, не утащи чужое.

## ⚠️ Уязвимости (security-review, незакоммиченные черновики) — решить с оператором
1. **IDOR `/calls/stream`** (HIGH): SSE не проверяет `owner` → читаешь чужие звонки. Фикс: игнорировать `owner` или гейт `sales.calls.read_all`.
2. **Untrusted `/telephony/incoming`** (HIGH): принимает dict без валидации → фабрикация CallLog/recording_url. Фикс: Pydantic-схема, reject unknown keys.
3. **Authz `/calls/{cid}/link-deal`** (MED): нет `call.owner==user`. Фикс: проверка владельца + set owner при создании сделки.

## Координация (канон)
- Миграции: **общая alembic-голова = 0055** (`migrations/versions/0044…0055`). `0043` — это твоя SALES-53, но поверх легли 0044…0055 — **0043 НЕ голова**. Свою миграцию НЕ нумеруй сам — пинг координатору (он впишет номер и down_revision = реальная голова на момент). 0056 за Складом/WMS.
- Реестр (ACTIVE-SESSIONS/DEPENDENCY-MAP/STATUS), счётчик, `.claude/settings.json` — только координатор. Писать МОЖНО только в `.activity.local.md`/`PUSH-LOG.md` (авто).
- Не трогать: `modules/leads/**` (лиды вынесены в отдельный чат), `core/domain/models.py::Sku` + `core/domain/reference.py` (Справочники), `core/services/stock` (1С=истина), `core/services/landed_cost.py` (Закупки), `modules/finance/**` (fin-7), хотспоты config/* и `frontend/src/lib/api.ts` (захват у координатора).
- Хэндоффы: эмитишь `sales.document.posted` (invoice→finance, order→logistics), `sales.deal.won`, `sales.stock.reserved` (→wms); ждёшь `finance.payment.paid`, `logistics.shipment.delivered`.
- Push: `git add` ТОЛЬКО свои файлы по именам (НЕ `add .`); перед коммитом `git log -1` — HEAD твой?; никакого amend/reset/rebase на общей ветке; cherry-pick своего на чистую ветку от origin; правка субмодуля = коммит + bump указателя. Push/commit — по явной просьбе.

## Следующий шаг (выбор с оператором)
- A: пофиксить 3 уязвимости (фиксы выше) → коммит в субмодуль + bump.
- B: принять риск как техдолг (отбросить/закоммитить черновики по решению).
- C: доводка фронта Сделок 2.0, если есть хвосты.

В конце доложи координатору: что закоммичено, состояние super/submodule, техдолг/уязвимости, нужен ли номер миграции.
