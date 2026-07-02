# Активные сессии — журнал синхронизации

Несколько Claude-сессий работают параллельно в **одном** worktree `main`. Этот файл —
живой реестр «кто что держит», чтобы не делать двойную работу и не драться за файлы.
**Намеренно НЕ коммитится** (общий worktree → файл и так виден всем; коммит = append-конфликты).

> 🧭 **ЕДИНЫЙ ПИСАТЕЛЬ ЭТОГО ФАЙЛА — координационный чат (с 2026-06-27).** Чтобы убрать клоббер
> («изменён, пока читал» — реестр правили несколько чатов разом, поймано прямо при онбординге
> координатора), правки реестра идут **через координатора**: пингуй его за полосой / номером
> миграции / захватом хотспота / мержем / деплоем — он вносит. Фичечаты сами пишут **только** в
> `coordination/.activity.local.md` (авто, git-хуки) и `coordination/PUSH-LOG.md` (авто, push-хук).
> Этот реестр: читают все, пишет один. Устав — `coordination/COORDINATOR.md`.

## 🔧 Реконсиляция gitlink-ов ветки sales-2.0-redesign (координатор, 2026-07-01)
Свежий клон `--recurse-submodules` ветки ломался: 3 gitlink-а суперпроекта ссылались на
неопубликованные submodule-коммиты. Починено координатором — **ветка снова клон-консистентна**
(все 9 gitlink-ов резолвятся на remote). Суперпроект `origin/sales-2.0-redesign = 6b590b2`.
- **finance** `0227ecb` — был локальный, **запушен** в fin-7/main (FF). ✅
- **hr** `3b23a3f` — был локальный, **запушен** в HR-10/main (FF). ✅
- **production** — gitlink суперпроекта указывал на `6bfb7f7` (коммит prod-events из `0ee244f`),
  но submodule-коммит НЕ был запушен и **объект утрачен на всех клонах этой машины**. Миграция
  0080 висела без backing-кода, 5 тестов `test_prod_events.py` были RED. **Код восстановлен по
  тестам-оракулу** (5/5 GREEN, ruff, 67 prod-тестов без регрессий), запушен в PRO-4 как **`f53222d`**,
  gitlink забумплен `6bfb7f7→f53222d`.
  > **→ Сессии prod-events:** твой локальный `6bfb7f7` теперь ОРФАН. **НЕ пуш его** — прими
  > опубликованный `f53222d` (`git -C modules/production fetch && git checkout main`). Если в
  > твоём 6bfb7f7 было что-то сверх контракта 5 тестов — сверься дифом против f53222d и допиши.

## Правила
1. **Перед стартом** допиши свою строку в таблицу «Полосы» (зона + файлы + статус).
2. **Не лезь в чужие пути.** Совпали пути — пингуй оператора, не редактируй вслепую.
3. **Миграции Alembic** — бери номер из «Счётчик миграций» ниже и **сразу инкрементируй его здесь**,
   до написания файла. Цепочка линейная, два одинаковых номера = два head.
4. **Хотспот-файлы** (`sidebar.tsx`, `config/modules.py`, `config/settings.py`,
   `core/services/__init__.py`, `lib/api.ts`) — захватывай в «Хотспоты» на время правки, освобождай после коммита.
5. **Коммить мелко и часто** — чем меньше незакоммиченного, тем меньше пересечений.
6. **Submodule** правишь — bump указателя только в своей сессии; не bump-ай чужой модуль.

## Счётчик миграций
- `0033` — procurement supplier_claim.
- `0034` — sales loss_reasons_v2 · `0035` — sales plan_target (заняты sales-сессией, **счётчик не обновляли** — поймал коллизию).
- `0036` — production_plan + production_order.completed_at (эта сессия, бэкенд готов; фронт — Sonnet по контракту).
- `0037` — core reference-data (ref_unit/currency/currency_rate/country/bank/vat_rate + sku.attributes), сессия **Справочники** (коммит ec25803).
- `0038` — sales-2.0 миграция данных (стадии 6→9), sales-сессия (коммит 2ea3091).
- `0039` — core MDM контрагентов (counterparty.is_active/merged_into_id + counterparty_alias), сессия **Справочники**.
- `0040` — core группы номенклатуры (ref_nomenclature_category parent_id + sku.category_id), сессия **Справочники** (проверено на live PG: head 0040).
- `0041` — sales call_log (телефония, SALES-50).
- `0042` — sales invoice_reserve (резерв под счёт, SALES-51).
- `0043` — sales contract_template (договор по УНП, SALES-53). **← реальная голова на `sales-2.0-redesign`.**
- `0044` — **leads init** (схема `leads.*`, вынос вертикали лидов) — **резерв за leads-сессией** (`_sales_redo_wt`/`leads-extraction-redo`). Не брать.
- `0045` — **procurement landed_cost** (себестоимость по `sku_code`) — **резерв за закупочной сессией** (ZAK-3). `down_revision` = реальная голова на момент записи (`0044`, если leads уже лёг, иначе координировать). Модель в submodule, миграция в супер-проекте.
- `0046`–`0055` — заняты (Справочники: SCD2/категории/атрибуты группы; Закупки: lot/batch+landed; и др.). Счётчик отставал.
- `0056` — **procurement landed_cost per-SKU + purchase_order/line** (Закупки, `down_revision="0055"`). ✅ Взят **АТОМАРНО** через `scripts/next_migration.py` (`reservations.local`, 2026-06-27 22:42).
- `0080`–`0086` — заняты (production/marketing/service/scd2/office/knowledge, разные полосы). Счётчик отставал.
- `0087` — **leads_init** (было `0044`, перенумеровано координатором после дубля с `field_provenance`; **уже в origin/main**, деплой-цепочка). Не трогать.
- `0088` — **sales_tenders_funnel** (воронка «Тендеры», Слайс 3 ТЗ П5; было `0087` — перенумеровано координатором 2026-07-03 при реконсиляции локальной sales-2.0-redesign с origin, коллизия с leads_init).
- `0089` — **sales_deal_next_step_at** (Слайс 4 ТЗ П4; было `0088` — перенумеровано вместе с 0088 выше). **← реальная голова на `sales-2.0-redesign` (локально, после реконсиляции коммитами `ec6e62b`+`8e0d2ef`, ещё не запушено).**
- `0057` — **reference `ref_sku_version` SCD2-история SKU** (Справочники, `down_revision="0056"`, schema public). ✅ Взят АТОМАРНО 2026-06-27 22:5x. ⚠️ down=**0056** (не 0055 — иначе форк против procurement-0056).
- `0058` — **wms `wms_inventory`** (Склад, `down_revision="0057"`). ✅ Взят АТОМАРНО 2026-06-27. ⚠️ Склад изначально написал файл как `0056_wms_inventory.py` (дубль с procurement) → **переномеровать в `0058`** (арбитраж ниже).
- `0059` — **wms операционное ядро** (движения/остатки/ячейки/инвентаризация-коррекция) (Склад, `down_revision="0058"`). ✅ Атомарно 2026-06-28.
- `0060` — **sales `sales.stage` редактор стадий воронки** (Продажи, `down_revision="0059"`). ✅ Атомарно 2026-06-28.
- `0061` finance(lifecycle+allocations) · `0062` sales(multi-funnels) · `0063` finance(cost_center+currency) · `0064` wms(receipt+qc) · `0065` procurement(suppliers+rfq) · `0066` wms(task putaway/pick) · `0067` refs(account/region dating) · `0068` wms(stock_threshold) · `0069` wms(cycle_count) · `0070` refs(sku master fields). ✅ ВСЕ взяты АТОМАРНО через `next_migration.py` за 00:44–01:10 под 6 параллельными полосами — цепочка осталась ЛИНЕЙНОЙ (аллокатор выдержал concurrency, форка НЕ случилось).
- **Следующий свободный: `0071`** (`down_revision="0070"`). Голова цепочки = **0070** (проверено аллокатором 2026-06-28). Цепочка `0055→…→0070` линейна, без форков/дублей.
  🔴 **Номер брать ТОЛЬКО через `scripts/next_migration.py <lane> "<desc>"` + `--peek`** — аллокатор атомарен и есть **источник истины** (ручной список отстаёт).
- **КРУГ 3 (роздан 2026-06-28):** ожидается **ОДНА** миграция — **Закупки** (`purchase_request.origin` + `purchase_order.received_at`, ОДНА ревизия) — берут через аллокатор в момент работы (НЕ резервирую устно). **Справочники** SCD2 partial-unique индекс — ОТЛОЖЕН (общие таблицы currency/vat/tnved, координированная миграция). Sales/Finance/Logistics/WMS — без миграций (всё аддитивно к существующим таблицам/эндпоинтам).
  ⚠️ **АРБИТРАЖ дубля 0056 (2026-06-27):** на диске были два `revision=0056` — `0056_procurement_landed_cost.py` (Закупки, взят атомарно 22:42) и `0056_wms_inventory.py` (Склад, взял из устного пред-подтверждения координатора В ОБХОД аллокатора). **Решение:** procurement держит 0056, Склад переномеровывает `0056_wms_inventory.py → 0058_wms_inventory.py` (revision=0058, down=0057). Не повторять — номер ТОЛЬКО через аллокатор.

## ⚠️ Недавно влито в origin/sales-2.0-redesign — ВСЕМ сессиям знать (2026-06-27)

- **AuthN P1-1 (CRM-хаб, commits `9c4afbe`+`86ac2a6`).** Тронуты CORE-файлы, которые читают ВСЕ модули:
  `core/services/auth.py`, `core/runtime/access.py`, `config/settings.py`.
  - Новый флаг `auth_mode` — дефолт `dev` (доверие `X-User-Roles` как раньше) → **локально и в тестах НИЧЕГО не меняется**.
  - `roles_from_request` (middleware) теперь делегирует в `get_current_user` — единый резолвер identity (правишь auth/access — это один путь).
  - 🔴 **Прод-гард:** `environment≠dev` НЕ стартует без `AIOS_AUTH_MODE=oidc` + `AIOS_KEYCLOAK_ISSUER` + `AIOS_KEYCLOAK_AUDIENCE`.
    Кто деплоит/гоняет в prod-режиме — сперва завести realm в Keycloak (он уже в стеке) + задать env, иначе app не поднимется (by design, security #2).
  - Новая зависимость **`PyJWT[crypto]`** (`requirements.txt`/`pyproject`) — после pull: `pip install -r requirements.txt`.
  - **Защита роутов — канон:** `Depends(require_permission("<perm>"))` (для WMS и любого модуля без RBAC — навешивать права так).
  - Полный отчёт: `SECURITY.md` P1-1 (`[~]`). Дальше P1-2 (RBAC на ВСЕ ручки), P1-3 (ownership/IDOR).

## Полосы (зоны ответственности)

| Сессия | Зона | Основные пути | Migration | Статус |
|--------|------|---------------|-----------|--------|
| **Справочники (reference-data)** (Opus) | core/ shared-kernel: reference (+ группы номенклатуры, проводка 1С) | `core/domain/reference.py`, `core/domain/models.py` (Sku.category_id), `core/runtime/reference_registry.py`, `core/runtime/reference_routes.py`, `core/services/reference_query.py`, `core/reference/CLAUDE.md`, `frontend/src/lib/reference-data*`, `tests/test_reference_{registry,categories}.py` (+ аддитивно `core/runtime/{contract,core,system_routes,app}.py`), MDM-адаптер ядра `core/services/reference_import.py` (⚠️ `modules/integrations/{service,client}.py` + `tests/test_integrations.py` — территория СИНК по `mdm-data-class-seam.md §4`, refs НЕ трогает) | 0037,0040 заняты | активна — ⚠️ `core/domain/models.py::Sku` веду я (Sku.category_id); карточку SKU чат «Сделки» делает как UI |
| **Производство+поставки** (эта) | production, procurement, wms, logistics | `modules/{production,procurement,wms,logistics}/**`, `frontend/src/app/erp/{production,procurement,wms,logistics}/**`, `frontend/src/lib/production-*`, `frontend/src/components/erp/{bom-panel,zayavki-table,vyrabotka-table,otk-panel,norms-table,logistics-*}` | 0033 занят | активна — ⚠️ wms и logistics выделяются в отдельные чаты (строки ниже) |
| РОП *(предположит.)* | crm/rop | `frontend/src/app/crm/rop/**`, `frontend/src/lib/rop-data.ts` | — | uncommitted: `rop/pace/page.tsx`, `rop-data.ts` |
| CRM / sales *(предположит.)* | sales (Сделки 2.0, задачи) | `modules/sales/**`, `frontend/src/app/crm/deals/**`, `frontend/src/lib/api.ts` | 0031/0032 заняты | в работе |
| Офис-менеджер *(предположит.)* | office | `modules/office/**`, `frontend/src/app/erp/office/**`, `frontend/src/components/erp/office-*` | — | в работе |
| ~~Крипто~~ *(⏸ ПАУЗА — решение оператора 2026-06-27)* | crypto | `modules/crypto/**`, `config/modules.py`, `config/settings.py`, `core/services/__init__.py`, `tests/test_crypto.py` | — | **НЕ делаем пока.** ✅ Дерево чисто (проверено: config-хотспоты без незакоммиченных правок) → **3 config-хотспота ОСВОБОЖДЕНЫ** |
| **Лиды** (новый чат оператора, 2026-07-02, продолжает leads-extraction) | `modules/leads` (CRM-LID1.1.git) + фронт `/crm/leads` | **submodule `modules/leads`** (CRM-LID1.1.git), `frontend/src/app/crm/leads/**`, `frontend/src/lib/leads-*`, супер-проект обвязка: `.gitmodules`, `config/modules.py` (строка `"leads"`), `migrations/versions/0087_leads_init.py` (было 0044, перенумеровано после дубля) | 0087 занят (leads init) | **АКТИВНА**. Вынос из sales уже влит в main через PR #9 (submodule sales tip `5b8ee85`/мёрдж `162b4d1`). ⚠️ Известный долг (xfail в `tests/test_intake.py`): модуль `leads` НЕ подписан на событие `intake.lead.received` и не имеет UTM-полей → веб/email-лиды не создают Lead автоматически. Контрагент — только через MDM-фасад ядра, `modules/integrations/**` не трогать (территория синк-сессии). |
| **Маржа/ценообразование (методика)** (эта сессия) | spec/design: методика цены продажи (наценка от landed cost) — блокер маржинальных фич | `coordination/pricing-methodology.md` (новый). НЕ трогаю sales/leads/обвязку. | — | активна — design-only, нулевая коллизия |
| **Закупки — HTML-прототипы + методика landed** (Opus, эта сессия) | ZAK HTML-прототипы (корень, не submodule) + чистая методика landed в ядре | `zak-*.html` (корень: новый `zak-machine-editor-preview.html` + правки board/claims/shipment/cost-calc/index), `core/services/landed_cost.py` (чистая функция `allocate_landed_cost` — БЕЗ таблиц/миграции), `tests/test_landed_cost_alloc.py` | **НЕ брал 0045** (только сервис-слой) | запушено в `sales-2.0-redesign`: bb441bb/d871338/bd4e397/e0f9c6f |

| **Склад / WMS** *(🟢 ЗАНЯТА — сессия «Склад» `local_7bbaba52…`, 2026-06-27)* | wms — реальное ядро складского учёта | **submodule `modules/wms` (SKL-5)**, `frontend/src/app/erp/wms/**`, wms-компоненты | **0056 зарезервирован** (схема `wms`, down_revision=0055) | **АКТИВНА** — взята по засеву (сверен с кодом). Контракт остатков принят: 1С/integrations = истина, WMS только ДУБЛИРУЕТ движения (обработчики `on_goods_received`/`on_stock_reserved` уже есть в `modules/wms/events.py`). НЕ трогать `core.services.stock`, integrations, shared-kernel. Контракт «импорт→склад» — через `procurement.received` (от логистики ОТОЗВАН). Перед написанием миграции 0056 — пинг координатору |
| **Логистика** *(этот чат, активен 2026-06-27)* | logistics (фрахт/рейсы/тендер/импорт) + межмодульные эмиты логистики | **submodule `modules/logistics` (LOG-6)** `modules/logistics/**`; фронт `frontend/src/app/erp/logistics/**`, `frontend/src/components/erp/logistics-*.tsx`, `frontend/src/lib/logistics-*.ts`; проекция фрахта в finance (`modules/finance/events.py::on_freight_cost`, см. флаг ниже) | следующий: **0057** под импорт (схема logistics), сверить head перед взятием | **АКТИВНА**. Сделано+запушено: фрахт→finance (LOG-6 `50b9043`, fin-7 `278dadd`, супер PR #11 `freight-finance`). Дальше — контракт «импорт→WMS» (эмит из логистики, WMS-сторону пишет Склад-чат). НЕ трогаю: `core.services.*`, integrations, shared-kernel, чужие фронт-воркеры |
| **Финансы (fin-7)** *(этот чат, активен 2026-06-27)* | finance — **ЕДИНЫЙ писатель** проводок/платежей/маржи | **submodule `modules/finance` (fin-7)** `modules/finance/**`; фронт `frontend/src/app/erp/finance/**` | TBD (сверить head перед взятием) | **АКТИВНА** — принял владение fin-7 по хендоффу логистики (стр. 84-89). Логистика впредь только эмитит `logistics.freight.cost`. ⚠️ Учитываю `Payment.kind` (`receivable`/`freight`) — не ломать фрахт. Миграция `0053_finance_payment_kind` в main НЕ влита (ветка `freight-finance`/PR #11). НЕ трогаю shared-kernel, integrations, чужие submodules |
| **Безопасность / AuthN** (CRM-хаб) | core auth/authz | `core/services/auth.py`, `core/runtime/access.py`, `config/settings.py` (auth-блок) | — | P1-1 влито (`9c4afbe`/`86ac2a6`); дальше P1-2 |
| **Выкачка Bitrix24+1С → наполнение (ВСЕ модули)** *(чат «Bitrix24 and 1C data extraction for November 2024», зарегистрирован координатором 2026-07-02; расширено на остальные модули 2026-07-02)* | connectors + backfill нояб.2024: MDM, sales, finance, + SKU/цены/закупки/WMS-зеркало/маркетинг/сервис/HR/RAG (потоки 7–15) | `connectors/**`, `data/{inbox,media}/**`, `scripts/backfill_nov2024.py` (новый). **Карта — `coordination/spec-backfill-nov2024.md`** | номер — только через координатора (по карте новых таблиц НЕ нужно) | **АКТИВНА** (ведёт оператор). ⚠ Сделки — скриптом с ИСТОРИЧЕСКИМИ датами; 1С read-only; контрагенты/SKU через фасады (MDM/reference SCD2); остатки/отгрузки — ТОЛЬКО зеркало 1С (не первичка WMS); перед записью в модуль активной полосы (reference/procurement/WMS) — пинг её чату через координатора |
| **🧭 Координатор** (этот чат, с 2026-06-27) | НЕ фичекод: реестр + hook-инфра + арбитраж | **владеет**: `coordination/{ACTIVE-SESSIONS,DEPENDENCY-MAP,STATUS}.md`, счётчик миграций, `.claude/settings.json` (hooks-блок), `.githooks/`, `scripts/coordination_hook.py`, `claude_pushlog_hook.py` + read-сторона awareness | ведёт счётчик | **АКТИВНА** — единый писатель реестра/settings.json; read-сторона hooks live; карта 6 полос построена (см. COORDINATOR.md) |

### ⏳ Очередь полос (план оператора 2026-06-27) — открыть СЛЕДОМ, по одной под конкретную задачу
| Полоса | Модуль | Статус | Заметка |
|--------|--------|--------|---------|
| Офис-менеджер | `office` (реальный, 1 табл.) | ⏳ в очереди | изолирован, низкая коллизия; засев по запросу |
| HR | `hr` (HR-10, схема `hr`, `/hr`) | 🟡 засев готов 2026-06-28 | **`coordination/seed-hr.md`** (сверен по коду) — ждёт открытия чата оператором. Задача круга 4: payroll-события `hr.payroll.accrued/paid`→finance Р5. ⚠ развести с `production.payroll` (ФОТ цеха). next-мигр через аллокатор (head 0075) |
| Маркетинг | `marketing` (заглушка) | ⏳ в очереди | большая отдельная инициатива (агентная + pSEO, частично microchips.by); отдельный заход |

> Тендеры — НЕ полоса (фича Логистики/Закупок). Аналитика/Директор/IT — сквозные, НЕ параллелить рано (бьются обо всех + хотспоты). Производство (`production`/PRO-4) — реальный модуль с заделом, чат по готовности.

> Строки «предположит.» восстановлены из git-состояния — поправьте под себя.
> **⚠️ Закупочной сессии (Производство+поставки, резерв 0045):** методику разнесения landed cost
> я уже реализовал как ЧИСТУЮ функцию `allocate_landed_cost` в `core/services/landed_cost.py`
> (образец Odoo `stock_landed_costs`: фрахт/пошлина/брокер/НДС → позиции по весу/объёму/стоимости/
> кол-ву/equal; Decimal, 17 тестов, ревью). **Миграцию 0045 и таблицы я НЕ занимал** — реализация
> `LandedCostService` + таблицы расходов остаются за вами; зовите готовый движок, не пишите второй.
> Результат на единицу кладите в `Batch.unit_landed_cost` (миграция 0052 уже есть). Память [[zak-machine-editor]].

> **⚠️ Складу/WMS — контракт остатков.** Остатки/резервы — ОПЕРАЦИОННЫЕ данные (НЕ master, НЕ в справочники).
> Контракт — `core.services.stock` (`StockGateway`: `reserve`/`release`/`stock_by_sku`/`batches_by_sku`); реализация
> шлюза сейчас в `modules/integrations` (полоса СИНК-сессии). По конституции **1С = истина склада (фаза 1)**. Если
> строишь реальный учёт остатков в WMS — это меняет источник истины → согласуй с СИНК-сессией и владельцем (нельзя
> тихо разойтись с 1С-остатками). Номенклатуру (`Sku`) бери из MDM, НЕ дублируй. Канон: `coordination/mdm-data-class-seam.md`.

> **⚠️ Финансам — единый писатель.** В `modules/finance` пишет ОДИН владелец. Логистика (фрахт), закупки (landed),
> продажи (счета/оплаты) НЕ пишут в finance напрямую — **эмитят события**, finance подписывается и проецирует (outbox →
> проводка по документу). Регулируемый ledger/НДС/ЭСЧФ остаётся в 1С (стратегия `erp-replace-bitrix-1c-strategy.md` §1);
> finance тут = операционный слой (платежи/затраты/маржа). Сейчас фрахт→finance уже пишет логистика-чат (fin-7) — если
> писателей станет 2+, выделить владельца finance в отдельный чат.
>
> **→ Финансы-чату (хендофф 2026-06-27, логистика-чат).** Раз finance-чат открыт — забирай владение fin-7.
> Я залил в fin-7 `main` (`278dadd`) проекцию фрахта: колонка `Payment.kind` (`receivable`|`freight`),
> обработчик `on_freight_cost` (подписка `logistics.freight.cost`), миграция `0053_finance_payment_kind`
> (в супер-проекте, ветка `freight-finance`/PR #11 — **в main НЕ влита**, ждёт реконсиляции миграц. бэклога).
> Дальше **все правки fin-7 — за тобой**; логистика будет только **эмитить**, не писать в finance. Меняешь форму
> платежа — учти `kind`, не сломай фрахт.
>
> **→ Финансы-чату (новое событие 2026-06-27): `logistics.freight.audit_refund`.** Логистика теперь эмитит его при
> аудите счёта перевозчика с переплатой (`variance>0`), payload `{shipment_code, carrier, amount, entity_ref:"audit:<id>"}`.
> Это **деньги к возврату** (перевозчик переплатил счёт). **Проекцию в fin-7 пишешь ты** — предлагаю как корректировку
> расхода фрахта (напр. `Payment(kind="freight_refund")` или отрицательная строка к freight). Логистика-сторона + тест уже
> готовы (LOG-6, `tests/test_links.py::test_freight_audit_overbill_emits_refund`), ждёт твоей проекции.
>
> **✅ ПРИНЯТО (финансы-чат, 2026-06-27).** Владение fin-7 забрал. Понял: `Payment.kind` (`receivable`/`freight`),
> `on_freight_cost` на `logistics.freight.cost`, миграция `0053` в main НЕ влита (ветка `freight-finance`/PR #11).
> При любой смене формы платежа сохраню `kind` и подписку фрахта. Логистика — эмитит, я проецирую.
>
> **→ Складу/WMS-чату (ОТМЕНА контракта «импорт→склад», логистика-чат 2026-06-27).** ❌ НЕ подписывайся на
> `logistics.import.arrived`/`customs_cleared` для прихода на склад — это **двойной учёт**. По дизайну
> (`ImportShipment` docstring) физический приход импорта делает **procurement (QC) → `procurement.received` → wms**
> (уже в графе §2). События логистики `import.*` — **информационные** для панели владельца, не для остатков.

## Хотспоты (single-file, кто сейчас держит)

| Файл | Держит | До |
|------|--------|-----|
| ~~`frontend/src/components/sidebar.tsx`~~ | ~~оркестратор prod-fe~~ | **ГОТОВО** — коммит 506a87e |
| `config/modules.py` | 🟢 свободен *(крипто на паузе, дерево чисто 2026-06-27)* | — |
| `config/settings.py` | 🟢 свободен *(крипто на паузе, дерево чисто 2026-06-27)* | — |
| `core/services/__init__.py` | 🟢 свободен *(крипто на паузе, дерево чисто 2026-06-27)* | — |
| `.claude/settings.json` (Claude-Code hooks) | **🧭 координатор** *(единый писатель, 2026-06-27)* | постоянно — правки только через координатора (guard блокит прямой Write; путь сопровождения — `cp` поверх) |

> **→ Закупкам (координатор, 2026-06-27):** ваш `claude_pushlog_hook.py` **впитан и зарегистрирован**
> в `.claude/settings.json` (PostToolUse·Bash → пишет в `coordination/PUSH-LOG.md`). Добавлена read-сторона
> `claude_awareness_hook.py` (SessionStart + PreToolUse на push/commit → впрыск состояния флота). `settings.json`
> теперь ведёт ТОЛЬКО координатор — можете снять его со своего рабочего набора и не держать хотспот.

## Неинтегрированные воркеры (orchestrator)
- `chats-panel-fe`, `deals-board-fe` — COMPLETE, в main не влиты (worktrees `crm-worker-*`). Решить: integrate или stop+cleanup.

## Синхронизация выноса лидов (absorb-процедура)
Leads-сессия работает на уровне сабмодулей, поэтому супер-проект ничего у себя не ломает.
Когда она зальёт (PR в CRM.git мёрджнут → `modules/sales` имеет коммит `5b8ee85`/мёрдж «sales без Lead»;
`modules/leads` запушен в CRM-LID1.1.git), целевая ветка супер-проекта (`sales-2.0-redesign`) впитывает лиды так
(**проверено: ложится чисто** — `518495b`→`5b8ee85` это +1 коммит, миграция `0044` чейнится к голове `0043`, `core.on_tick` уже есть):
1. `modules/sales`: `git -C modules/sales fetch && git -C modules/sales checkout <tip>` → bump указателя.
2. `modules/leads`: добавить submodule (`.gitmodules` + `git submodule add … CRM-LID1.1.git modules/leads`), checkout на запушенный tip.
3. `config/modules.py`: `"leads"` в `ENABLED_MODULES` сразу после `"sales"` (хотспот — захватить на время правки).
4. Миграция `0044_leads_init.py` (`down_revision="0043"`).
5. Тесты+seed: `tests/test_leads.py` + правки `test_{telephony,edge_cases,links}.py`/`unit/test_engine.py` (лиды как отдельный модуль), лид-часть `scripts/seed.py`.
6. `pytest` → green, `ruff check .`.

> Готовый эталон обвязки лежит в worktree `_leads_wt` (ветка `leads-activation`), но его `core/` устарел (нет `on_tick`) —
> брать оттуда только обвязку (`.gitmodules`/config/migration/тесты), core не трогать.

## Деплой-состояние (хаб = чат CRM, 2026-06-24)
- **`origin/main` = `67aa06e`** = полная линия sales-2.0 (редизайн/коннекторы/фронт/SALES-50/51/53/security-P0) + впитаны лиды. **ЗАДЕПЛОЕНО на сервер** (`/opt/cmr-erp`): alembic head `0044`, схема `leads` создана, БД/Redis на `127.0.0.1` (P0-7 в проде), все контейнеры `Up`.
- Сборочная ветка: `deploy-consolidation` (worktree `_deploy_wt`) → пушится в `main`.
- gitlinks линии (все запушены): `sales→5b8ee85` (CRM/leads-extraction-redo), `leads→5d0d5f9` (CRM-LID1.1/main), `production→2ff2125` (PRO-4/main, доpush'ен FF), `procurement→f76a0def` (ZAK-3/**ветка deploy-pin** — расходится с ZAK-3 main `e30f379`, нужна реконсиляция владельцем).
- Серверные команды — **только вручную** (guard блокит `tailscale ssh` во всех Claude-сессиях). Деталь конвейера — в памяти [[server-deployment-belakb]].
- **Хвост (follow-up):** тесты/seed не реконсилены под вынос лидов (sales-тесты ссылаются на удалённый Lead → CI красит; не рантайм).

---
_Обновлено: 2026-06-27 (онбординг координатора: единый писатель реестра + settings.json; счётчик миграций перепроверен head 0055→next 0056). Не коммитить._
