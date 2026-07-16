# Карта связей проекта (DEPENDENCY-MAP)

> Живой документ. Сверяйся ПЕРЕД работой, чтобы параллельные сессии и сотрудники
> не конфликтовали. Источник — автоскан кода на 2026-06-18 (ветка `sales-2.0-redesign`).
> Когда меняешь связи (новое событие, новый модуль, новый shared-FK) — обнови этот файл.
>
> ✅ **Верифицировано адверсариально (Opus, 2026-06-18):** изоляция модулей, граф событий,
> 2 мёртвые подписки, 3 денежные связи, отсутствие обратных FK ядро→модули — подтверждены
> по реальному коду. Расхождений карты с кодом не найдено.

## TL;DR для координации

- **13 модулей**, связаны ТОЛЬКО через ядро (`core`): события (outbox) + shared-kernel данные.
  Прямых импортов `modules.A` → `modules.B` **нет** (изоляция соблюдена) — не нарушай.
- **3 горячих файла-хотспота** (захвачены сессиями, не трогать без согласования):
  `config/settings.py`, `config/modules.py`, `core/services/__init__.py`.
- **Миграции Alembic — линейная цепочка**: двойной номер = два head = поломка.
  Брать следующий номер только сверившись с актуальным head.
- **shared-kernel данные** (`counterparty`, `sku`, `app_user`, `ref_*`) — общие для всех.
  Меняешь их схему → ломаешь всех. Только через согласование + миграцию.

---

## 1. Как устроена связь (единственные легальные каналы)

Модуль НЕ обращается к внутренностям другого. Только два канала:

### Канал A — события (transactional outbox)
1. `event_bus.emit(session, type, payload)` → пишет `OutboxEvent` в ТУ ЖЕ транзакцию.
2. Коммитит **вызывающий роут/workflow** (репозитории не коммитят).
3. Фоновый `_background_loop` (поллинг 2с) → `relay_once` → находит подписчиков →
   вызывает их + проецирует в `AuditLog`. Relay коммитит сам.
4. Обработчик: `handler(payload)` ИЛИ `handler(payload, ctx)` (ctx = session+services, для AI).

### Канал B — фасад Core (точки расширения при `register(core)`)
| Метод | Регистрирует |
|---|---|
| `include_router(router, prefix)` | роуты модуля |
| `subscribe(event_type, handler)` | подписку на событие |
| `register_workflow(name, wf)` | Temporal-процесс |
| `declare_permissions` / `declare_role` | RBAC модуля |
| `register_telegram` | команду TG-бота |
| `register_widget` | виджет панели владельца |
| `register_reference` / `register_owned_reference` | справочник в витрину |
| `on_startup` / `on_shutdown` | хуки жизненного цикла |

> ⚠️ Глобальные неявные связи (риск тихих конфликтов):
> - Общий реестр `Core`: два модуля могут зарегистрировать одинаковый `event_type` или
>   `Permission.code` — **не детектируется**, тихо уживутся. Не дублируй коды.
> - Общий `event_bus._handlers` (FIFO, изоляции нет). Обработчик пишет в relay-сессию —
>   его изменения попадут в тот же commit, что и пометка `processed_at`.
> - Общие `core.services` — ОДИН экземпляр на всех (полный состав — Канал B2 ниже).

### Канал B2 — шлюзы ядра: кто НАПОЛНЯЕТ → кто ЧИТАЕТ

`core/services/__init__.py::Services`. Контракт держит ядро, реализацию ставит **модуль-владелец**
в `register(core)`: `core.services.<имя> = <impl>`. `None` = владелец не подключён → потребитель
**честно деградирует** (503 / «нет данных»), НЕ подставляет 0 (PLATFORM #1 — фальшивые деньги хуже
пустоты). Модули в источник напрямую НЕ ходят, только через шлюз.

| Шлюз | Наполняет | Читают | Состояние (сверено с кодом 2026-07-16) |
|---|---|---|---|
| `onec` | integrations (`module.py:28`) | sales, finance | ✅ есть; сам клиент MOCK при пустом `onec_base_url` |
| `stock` | integrations (`module.py:29`) | sales, wms | ✅ есть; 1С = истина склада (фаза 1) |
| `registry` | integrations (`module.py:30`) | sales (ЕГР по УНП) | ✅ есть |
| `telephony` | integrations (`module.py:33`) | sales, leads | ✅ есть |
| `landed_cost` | procurement (`module.py:29`) | finance (`margin.py`), procurement | ✅ есть |
| **`price_cost`** (PC1-6) | **в `main`/`sales-2.0-redesign` — НИКТО**; только dev-фикстура `app.py:52` за `AIOS_DEMO_PRICE_COST=1` (+гейт `environment=dev`) | **sales** (`routes.py`: маржа сделки, дефолт цены КП, дефолт маржи конструктора плана) | 🟡 **потребители готовы, продовый наполнитель НЕ влит** — лежит на ветке `sales-1c-live` (`8aa5da7`: `modules/integrations/price_cost.py` + тесты). В проде всегда `None` → себес/цена не показываются, метка провенанса «демо»/«из 1С»/«из закупок». **Влитие = решение координатора** |
| `touch_history` | **НИКТО** (докстринг обещает `SalesTouchHistory()` из sales) | core, 360°-досье клиента | 🔴 объявлен, но не реализован → история касаний не отдаётся |
| `sku_master` | core-native (модуль, не Protocol — всегда доступен) | procurement, sales | ✅ REF3-1 |

> 🔴 **Правило для полос:** новый шлюз в `Services` = правка хотспота `core/services/__init__.py`
> → **через координатора** + строка в этой таблице. Шлюз без наполнителя — нормальное состояние
> (контракт-шов вперёд реализации), но он ОБЯЗАН честно деградировать у каждого потребителя.

---

## 2. Граф межмодульных событий (кто на кого влияет)

Только РЕАЛЬНЫЕ пары (emit есть И подписчик есть):

| От | Событие | К | Эффект |
|---|---|---|---|
| sales | `sales.deal.won` | office | создаёт пакет документов (on_deal_won) + внутри sales → handoff-пакет (on_deal_won_handoff) |
| sales | `sales.document.posted` (order) | logistics | планирует отгрузку |
| sales | `sales.document.posted` (invoice) | finance | создаёт платёж → `finance.payment.created` |
| sales | `sales.stock.reserved` | wms | списание под заказ |
| sales | `sales.stock.released` | wms | снятие резерва / возврат на склад |
| sales | `sales.message.sent` | sales (AI) | AI-агент на входящее |
| sales | `sales.plan.approved` | sales | (круг 3) план РОП → `KpiTarget` скорборда (on_plan_approved) |
| sales | `sales.deal.ship_deadline.set` | procurement | **(круг 4)** крайняя дата отгрузки + штраф → `on_ship_deadline_set` складывает `ShipRequirement` (сделка,sku) → план сбора машины к самому раннему сроку − буфер (мигр.0073 sales / 0074 procurement) |
| marketing | `marketing.campaign.launched` | leads | создаёт лиды (on_campaign_launched, до 10 шт/кампания) |
| finance | `finance.payment.paid` | sales | помечает счёт оплаченным |
| finance | `finance.payment.received` | office | **(круг 3)** поступление денег вкл. частичное → офис; ✅ закрыта мёртвая подписка |
| logistics | `logistics.shipment.delivered` | sales | сделка → won |
| logistics | `logistics.freight.cost` | finance | расход на фрахт (Payment kind=freight); **круг 3:** + импорт-плечо `leg:'import'`, БЕЗ deal_id |
| logistics | `logistics.freight.audit_refund` | finance | переплата перевозчику по аудиту (variance>0) → возврат |
| logistics | `logistics.delivery.delivered` | office | закрывает документ доставки |
| logistics | `logistics.delivery.tracking` | office | обновляет статус доставки |
| office | `logistics.delivery.requested` | logistics | создаёт Shipment / CarrierRfq |
| procurement | `procurement.received` | wms · sales · logistics | приход: wms→склад; sales→`supply.arrived` (круг 3); logistics→ImportShipment+`import.received` |
| procurement | `procurement.landed_cost.calculated` | finance | landed cost (payload `qty`+`total`) → факт-маржа; **круг 3:** `stage:'actual'` на реальной приёмке |
| procurement | `procurement.claim.resolved` | finance | **(круг 3)** рекламация (`amount_byn` уже BYN, +`order_id`) → проводка-компенсация (БЕЗ fx-конвертации!) |
| procurement | `procurement.po.drafted` | finance | **(круг 3)** черновик PO из RFQ-award → прогноз оттока в cashflow (kind=po_planned) |
| production | `production.completed` | wms | приход готовой продукции |
| production | `production.scrap` | procurement | авто-претензия поставщику |
| wms | `wms.stock.low` | procurement | **(круг 3)** дефицит склада → авто-черновик заявки (MRP-lite реактивный) |
| wms | `wms.shipment.completed` | office | **(круг 3)** отгрузка → документ «Отгружено»; ✅ закрыта мёртвая подписка |
| reference | `reference.{ref_tnved,sku,vat,currency}.changed` | finance · procurement | **(круг 4, B2 закрыт)** смена ставки ТН ВЭД/НДС/курса/мастер-полей SKU → **finance** (`7131bf1`): outbox `finance.landed.recompute_requested` (дедуп sku) → пересчёт landed через `sku_master.landed_inputs_batch`; **procurement** (`module.py:25-26` `on_reference_changed`): пересчёт cost_estimate/landed |
| hr | `hr.payroll.accrued` | finance | **(круг 5/Р5)** начисление ФОТ → `Payment(kind=payroll, status=pending)`; payload: `{employee_id, employee_name, period:"YYYY-MM", amount_byn:str, entity_ref:"payroll:<id>"}` |
| hr | `hr.payroll.paid` | finance | **(круг 5/Р5)** выплата ФОТ → settle Payment по `entity_ref` → `status=paid` |
| sales | `sales.deal.handoff` | finance | **(Р5 accrual)** признание выручки → `Payment(kind=receivable, status=recognized, amount=Decimal(str(payload.amount)))`; идемпотентно по deal_id |
| intake | `intake.lead.received` | leads | лид с сайта/email → воронка (`on_intake_lead`, `modules/leads/events.py`; чинено 2026-07-04 — до этого emit был без подписчика, xfail) |
| telephony | `telephony.call.*` | sales | screen-pop звонка (logged/answered/ended/transfer) |

**Центральные узлы графа:** `finance` — крупнейший приёмник (**6 подписок**: document.posted, freight.cost, freight.audit_refund, landed_cost.calculated, claim.resolved, po.drafted); `sales` (источник+приёмник); `office` (deal.won, delivery.delivered/tracking, shipment.completed, payment.received); `wms` (приёмник 4 + теперь **ЭМИТТЕР**: stock.low, shipment.completed). Менять контракт этих событий (поля/имя) = ломать цепочку — согласовывать.

### Висячие связи (технический долг, не баг — но знать)
- **emit без подписчиков** (только аудит, by design): `sales.deal.handoff` (⚠ office реагирует через `sales.deal.won`, НЕ через handoff — handoff висячий), `sales.supply.arrived` (круг 3, INFO), `sales.plan.rejected`, большинство `sales.*` (lost/document.created/rejected/task.*/item.changed/price.quoted/lead.*/invoice.*/call.*), все `ai.*`, `finance.payment.created`, `procurement.order.status_changed`, `procurement.rfq.awarded`, `logistics.import.received`(INFO)/shipment.created/carrier_order/import.customs_cleared/import.arrived/rfq.*/contract.signed, исходящие `office.*`, `approval.*`, `counterparty.merged/unmerged`, `integration.1c.synced`. Также без подписчика (leads-модуль, только аудит): `leads.lead.qualified`, `leads.lead.routed`, `leads.lead.rejected` (Слайс 4, 2026-07-04) — `leads.lead.converted` уже РАБОЧЕЕ ребро (sales создаёт Deal), но в таблице выше отсутствует — техдолг документации, не в скоупе кокпита лида.
- ~~**`reference.*.changed`** — подписчиков пока нет~~ → **✅ ЗАКРЫТО (круг 4 B2): finance И procurement подписаны** — перенесено в рабочую таблицу выше. Finance эмитит `finance.landed.recompute_requested` (внутр. outbox, дедуп sku).
- ~~**`sales.deal.ship_deadline.set`** — sales→procurement, подписчика нет~~ → **✅ ЗАМКНУТО в круге 4** (`76a293c`): procurement подписан (`on_ship_deadline_set`→`ShipRequirement`→план машины), ребро перенесено в таблицу выше как РАБОЧЕЕ.
- ~~**⚠ РАЗРЫВ КОНТРАКТА (найдено 2026-07-04)**~~ → **✅ ПОЧИНЕНО 2026-07-11 (лид-полоса, цикл 4):** миграция `0095` добавила `utm_source/utm_medium/utm_campaign` на `leads.lead`; UTM протянуты из `intake.lead.received` (`_extract_utm`) и `marketing.campaign.launched` в лид и в payload `leads.lead.received` (+`landing_url`); подписка marketing переименована `sales.lead.received`→`leads.lead.received` (submodule MAR-8, ветка `leads-attribution-fix`, `c0e8600`). Ребро `leads → marketing` (`leads.lead.received`, потребитель `on_lead_received` — UTM-атрибуция к кампании) — РАБОЧЕЕ. Также аддитивно: `items[]` в payload `leads.lead.converted` (цикл 3). Историческая запись: `modules/marketing/module.py` был подписан на `sales.lead.received` (`on_lead_received`, UTM-атрибуция лида к SEO-кампании), но модуль `leads` эмиттит `leads.lead.received`/`intake.lead.received` — других имён нет нигде. Атрибуция новых лидов к кампаниям НЕ срабатывает. Простое переименование строки подписки НЕ починит: `utm_campaign`/`utm_source`/`landing_url` из payload `intake.lead.received` (единственное место, где они реально есть — `_extract_utm` в `modules/integrations/routes.py`) никуда не долетают дальше — у `Lead` нет колонок под UTM, и `on_intake_lead`/`leads.lead.received` их не пробрасывает. Нужна миграция (UTM-поля на `Lead`) + решение, кто их передаёт дальше в `leads.lead.received`. Не в скоупе слайса intake-fix (`6a16ac0`/`0e400f6`).
- **подписка без emit: НЕТ ✅** — обе бывшие мёртвые подписки office (`wms.shipment.completed`, `finance.payment.received`) закрыты эмиттерами в круге 3.

### 2c. Планируемые связи ЗАКУПОК (S&OP / планирование спроса — ДИЗАЙН, в коде ещё НЕТ)

> Контекст для проработки **окон закупок** (отдельная сессия). Полный замысел и методики —
> в памяти проекта `demand-planning-sop-engine` и макетах `sales-profit-forecast.html` /
> `sales-regular-clients.html` (инструмент «подтверждённый объём»). Эти связи ещё **НЕ
> реализованы** (эмиттеров/подписчиков нет) — это контракт на будущее, чтобы окна закупок
> строились под него. Не считать их рабочими событиями §2.

**Закупки ПОТРЕБЛЯЮТ** (вход при планировании следующей машины, за ~30 дн до выезда):

| Источник | Что приходит | Зачем закупкам |
|---|---|---|
| sales (планирование спроса) | `sales.demand.requirement` — чистая потребность по SKU×период: **подтверждённый продавцом объём − остаток − в пути + страх. буфер** | список номенклатуры в следующую машину |
| sales (постоянные клиенты) | подтверждённый объём по клиенту/SKU + уверенность % (3 опоры: история · договорённость · план клиента) | гейт «заказывать / не заказывать» — не везти то, от чего клиент отказался |
| wms | остаток + в пути + оборачиваемость | нетто-вычитание: что уже есть/едет — не дозаказывать |
| reference (`sku`, `ref_currency_rate`) | номенклатура, курс НБ РБ | позиции и валюта закупки |

**Закупки ПРЕДОСТАВЛЯЮТ** (другие модули ждут этого ОТ закупок):

| Что отдают | Кому | Эффект |
|---|---|---|
| **landed cost** по SKU (закуп + фрахт + растаможка) | sales | маржа / профит-мост (`sales-margin-by-month`, `sales-profit-forecast`). ⚠ **блокер** — методика цены не готова ([[pricing-calculation-todo]]) |
| **открытый PO / in-transit** с ETA + статус (заказан/отгружен/таможня) | sales, logistics | вычитание «в пути» в нетто-расчёте + сквозной статус машины |
| **ETA / приход машины** | sales (`margin-by-month`) | месяц поставки = ETA рейса |
| `procurement.received` (**уже есть**, §2) | wms | приход товара на склад |

**Цикл:** машина планируется **~за 30 дней** до выезда; перед этим — **месячный цикл
подтверждения продавцов** (консенсус-гейт). Триггер заявки правильнее по состоянию буфера
(DDMRP Net Flow Position), не календарный «будильник».

⚠️ **Бэкенд-долг под эту петлю:** сейчас в коде `procurement` = 2 таблицы (воронка), **открытых
PO с ETA не ведёт** → «в пути» вычесть нечем, и `landed_cost` per-SKU наружу не отдаёт. Это
первое, что нужно для планирования машины. Окна закупок проектировать с этими полями заранее.

---

## 3. Shared kernel — общие данные (точки пересечения по БД)

Принадлежат ядру (`public`), модули хранят FK, **не копируют**. FK однонаправленны:
модули → ядро, ядро НЕ знает о модулях (проверено, обратных FK нет).

| Таблица | Кто ссылается | Менять схему = риск для |
|---|---|---|
| `counterparty` (+alias) | sales, procurement, finance, office | всех клиент/поставщик-потоков |
| `sku` | sales, procurement, wms, production | всей номенклатуры |
| `app_user` | все (менеджер/исполнитель/согласующий) | всех |
| `ref_currency` / `ref_currency_rate` (SCD2) | finance, procurement, sales | валютных цен |
| `ref_vat_rate` (SCD2) | finance, sales, procurement | НДС документов |
| `outbox_event` / `audit_log` | инфраструктура (все через шину) | всей событийки |

- **MDM/справочники**: мастер-данные (`counterparty`, `sku`) + стандарты (`ref_*`, версионные
  через SCD2 `[start_date,end_date)`) + registry-витрина (каталог для вкладки «Справочники»,
  НЕ второе хранилище). Пишут: `reference_import` (1С/Bitrix), `mdm` (merge), `scd2` (версии).
  Читает: `reference_query` (структурный lookup для AI).
- Атрибуты SKU — JSONB (не EAV).
- `Approval.entity_ref` / `AuditLog.entity_ref` — строковые ссылки (`"deal:7"`), не FK.

---

## 4. Паспорт модулей (статус наполнения)

| Модуль | Статус | Схема БД | Префикс | ~Таблиц |
|---|---|---|---|---|
| sales | **полноценный** (эталон) | `sales` | `/sales` | 12 |
| logistics | **полноценный** (самый разветвлённый) | `logistics` | `/logistics` | 12 |
| production | полноценный | `production` | `/production` | 7 |
| integrations | полноценный (шлюз 1С) | `integrations` | `/integrations` | 1 |
| procurement | полноценный | `procurement` | `/procurement` | 2 |
| wms | полноценный | `wms` | `/wms` | 2 |
| hr | полноценный | `hr` | `/hr` | 2 |
| office | полноценный | `office` | `/office` | 1 |
| finance | **заглушка** (1 Payment) | `finance` | `/finance` | 1 |
| marketing | **заглушка** (1 Campaign) | `marketing` | `/marketing` | 1 |
| service | **заглушка** (1 Ticket) | `service` | `/service` | 1 |
| legal | **заглушка** (1 LegalCase) | `legal` | `/legal` | 1 |
| knowledge | **заглушка** (1 Course) | `knowledge` | `/knowledge` | 1 |

> Заглушки безопасны для параллельной работы — там пока нечего ломать. Конфликты
> вероятнее всего в sales / logistics / production / ядре.

---

## 4b. Технический долг, подсвеченный картой (не баги — на упреждение)

- ~~**2 мёртвые подписки**~~ **✅ ЗАКРЫТЫ (круг 3):** `wms.shipment.completed` теперь эмитит
  wms (`wms/routes.py:182`, при наличии doc_ref); `finance.payment.received` теперь эмитит
  finance на каждом поступлении (`finance/routes.py:270`). office получает реальные сигналы.
- ~~**Деньги — латентный риск сериализации**~~ **✅ ИСПРАВЛЕНО (круг 3, FIN-A2):** payload
  `finance.payment.created` теперь шлёт `str(amount)` (Decimal-safe); logistics-деньги тоже
  переведены на `str()`. Приоритет №1 (деньги собственнику) — закрыт упреждающе.
- **Устаревший докстринг auth.** `core/services/auth.py:5` всё ещё пишет «по умолчанию —
  суперпользователь Админ», но КОД уже fail-closed → «Гость» (`auth.py:36-37`, `access.py:32-34`).
  Докстринг противоречит коду — ловушка для будущих сессий. Поправить текст докстринга.

## 5. Зоны параллельной работы и риски конфликтов

### Хотспоты (один файл — много доменов). НЕ трогать без согласования:
| Файл | Кто держит / почему опасно | Риск |
|---|---|---|
| `config/settings.py` | env/флаги — любая сессия | **ВЫСОКИЙ** |
| `config/modules.py` | добавление модуля в `ENABLED_MODULES` | **ВЫСОКИЙ** |
| `core/services/__init__.py` | `build_services()` + dataclass `Services` — новый общий сервис | **ВЫСОКИЙ** |
| `core/db/base.py` (`Base.metadata`, `NAMING_CONVENTION`) | общий metadata-реестр всех моделей; завязаны Alembic env + любая схемная операция | **ВЫСОКИЙ** |
| `core/domain/models.py` (`Sku`) | Справочники vs Sales (карточка SKU) | **ВЫСОКИЙ** |
| Миграции Alembic (head) | двойной номер = два head | **ВЫСОКИЙ** |
| `frontend/src/lib/api.ts` | универсальный API-клиент, все фронт-домены | СРЕДНИЙ |
| `tests/conftest.py` | общие фикстуры тестов | СРЕДНИЙ |
| `core/runtime/access.py`, `core/services/auth.py` | RBAC/безопасность | СРЕДНИЙ |

### Правило веток/пуша (из CLAUDE.md — соблюдать строго):
- Параллельные сессии пишут в локальный `main` → локальный обгоняет `origin/main`.
- **Пушить ТОЛЬКО свой коммит**: cherry-pick на чистую ветку от `origin/main` (worktree),
  не утаскивая чужие коммиты. Push/commit — только по явной просьбе пользователя.
- Правка submodule = коммит в его репо + обновление указателя в суперпроекте.

---

## 6. Что проверить перед запуском новой параллельной сессии (чек-лист)

1. Назвать СВОЮ полосу файлов (домен из §5) и записать в `coordination/ACTIVE-SESSIONS.md`.
2. Свериться: не пересекается ли полоса с хотспотами §5 и чужими активными сессиями.
3. Если нужна миграция — взять следующий номер ОТ актуального head (не угадывать).
4. Если меняешь shared-kernel (§3) или контракт центрального события (§2) — согласовать,
   это ломает других.
5. Не дублировать `event_type` / `Permission.code` (тихо конфликтуют, §1).
