# Модуль office — контекст для Claude

**Тип:** in-tree папка основного репозитория (не submodule)
**API-префикс:** `/office`
**Схема БД:** `office`
**Статус:** рабочий модуль — CRUD + канбан + **связи с отделами (события)** + **заявка перевозчику по РБ** + RBAC
**Итоговый репозиторий:** https://github.com/aidzmitry-gif/OF-11

## Назначение
Офис-менеджер: документооборот по сделкам после продажи — отгрузка → сбор документов →
оплата, в виде канбан-воронки. Постпродажный документальный конвейер, связанный с
соседними отделами через событийную шину.

## Файлы
- `module.py` — `OfficeModule`; в `register`: роутер + виджет + права/роль RBAC + **подписки на 4 события отделов**.
- `events.py` — обработчики входящих событий (on_deal_won / on_shipment_completed / on_delivery_delivered / on_delivery_tracking / on_payment_received) + emit-хелперы исходящих событий.
- `models.py` — ORM `OfficeDoc` (схема `office`), + поля связей `*_ref`, доставка (`region/weight/address`), `overdue_days`.
- `carriers.py` — справочник перевозчиков по РБ (`CARRIERS`) + `get_carrier`.
- `schemas.py` — `OfficeDocCreate/Out`, `StageUpdate`, `CarrierOut`, `CarrierRequest`, `CarrierRequestOut`.
- `routes.py` — эндпоинты `/office` (вкл. `/carriers` и `/docs/{id}/carrier-request`).
- `stages.py` — 5 стадий: `ready → shipped → docs → await_pay → paid` (без изменений).
- `office-manager.html` — самодостаточный макет UI (превью без бэкенда).

## Что регистрирует в ядре (register())
- Роуты `/office` + виджет `Widget("office","Офис-менеджер",source="office.docs")`.
- **Права RBAC:** `office.doc.read`, `office.doc.write`, `office.stage.move`, `office.carrier.request`.
- **Роль:** «Офис-менеджер» (все 4 права).
- **Подписки (входящие связи):** `sales.deal.won`, `wms.shipment.completed`, `logistics.delivery.delivered`, `logistics.delivery.tracking` (статус перевозки на карточке), `finance.payment.received`.

## Связи с отделами (события)
**Входящие** (подписки): `sales.deal.won` (CRM → завести документ), `wms.shipment.completed`
(Склад → «Отгружено»), `logistics.delivery.delivered` (Логистика → трекинг),
`finance.payment.received` (Финансы → «Оплачено»).
- **Сопоставление с финансами — по `deal_id`** (мигр. 0105): документ хранит `sales_ref` =
  НОМЕР сделки (строка, эхо-ключ Склада/Логистики), а `finance.payment.received` несёт
  целочисленный `deal_id` — это единственный общий ключ. До 0105 их сравнивали строкой →
  никогда не совпадало, оплата не двигала документ (мёртвый шов; тест был зелен на
  синтетическом `{finance_ref}`, которого в событии финансов нет).
- **Частичная оплата:** `finance.payment.received` эмитится на КАЖДОЕ поступление; документ
  закрываем в «Оплачено» ТОЛЬКО при `outstanding == 0`, иначе показываем остаток и оставляем
  стадию/просрочку (не врём про деньги, PLATFORM #1). Оплаченный документ лестница эскалации
  не трогает (гард `stage == "paid"`).
**Исходящие** (emit): `office.doc.created`, `office.shipment.requested` (→Склад),
`logistics.delivery.requested` (→Логистика, заявка перевозчику), `office.docs.collected`
(→Финансы), `office.payment.awaiting` (→Финансы, флаг `needs_approval` при сумме > 10 000 BYN),
`office.payment.overdue` (→Юрист, претензия при просрочке > 15 дней).
Шина — transactional outbox (`core/services/eventbus.py`), доставка через relay (at-least-once).

## Модель данных (схема `office`)
- `office_doc` (`OfficeDoc`): number, company, title, amount(Numeric), delivery, docs_status,
  priority(`Средний`), owner, **stage**(`ready`), next_step, op_date, created_at;
  **+ доставка:** region, weight, address;
  **+ следы связей:** deal_id (int, ручка сделки — join с финансами), sales_ref, wms_ref,
  logistics_ref, finance_ref, legal_ref, overdue_days.
  Все новые колонки — аддитивные, с `server_default` (миграция безопасна).

## API-эндпоинты
- `GET /office/docs`, `POST /office/docs` (201, авто-номер `ДОК-2026-NNNN`, эмитит `office.doc.created`).
- `GET /office/board` — воронка через `core/runtime/funnel.build_board(STAGES, rows, _to_card)`.
- `GET /office/carriers` — справочник перевозчиков по РБ.
- `PATCH /office/docs/{id}` — смена стадии (валидируется против `STAGES`); переход эмитит событие отделу.
- `POST /office/docs/{id}/carrier-request` — заявка перевозчику: генерит `ЛОГ-2026-NNNN`, фиксирует перевозчика, эмитит `logistics.delivery.requested`.

## Заявка перевозчику на доставку по РБ
Кнопка «Создать заявку перевозчику» на карточке стадии `ready` → модалка с выбором из
справочника (СДЭК / Европочта / Белпочта / Деловые Линии / DPD / Свой транспорт; тип,
рейтинг, срок, цена от, зона, флаг тяжёлого груза). AI-подбор перевозчика — **Итерация 1**
(ghost-плейсхолдер в прототипе).

## Подводные камни / детали
- Роуты сами `commit` (как и другие канбан-модули); событие эмитится в той же транзакции через `core.event_bus.emit`.
- Обработчики событий принимают `(payload, ctx)`: `ctx.session` — сессия БД, `ctx.services.event_bus` — шина для повторного emit.
- Сопоставление входящих событий с документом — по `*_ref` полям (sales/wms/logistics/finance) либо по номеру; обработчики defensive (несколько возможных ключей payload).
- Новые колонки требуют Alembic-миграции (`--autogenerate`), хоть и аддитивной.
- Канбан — общий механизм `core/runtime/funnel.py` (см. также hr/legal/knowledge/procurement/production).
- AI-элементы во всём модуле — Итерация 1, в прототипе только дашед-плейсхолдеры.
