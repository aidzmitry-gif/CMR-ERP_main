"""События модуля Office — связи с другими отделами.

Офис-менеджер сидит в центре постпродажного контура и связан с пятью отделами:

    CRM/Sales ──sales.deal.won──▶ ОФИС
                                    ├──office.reservation.requested──▶ Склад   (держать резерв под сделку)
                                    ├──office.shipment.requested─────▶ Склад   (собрать/подготовить к отгрузке)
                                    ├──logistics.delivery.requested──▶ Логистика  (заявка перевозчику)
                                    ├──office.docs.collected─────────▶ Финансы
                                    ├──office.payment.awaiting────────▶ Финансы    (+ кредитный риск при крупной сумме)
                                    └──лестница просрочки дебиторки (ТЗ §4.2):
                                          >5 дн  office.payment.reminder   (напоминание клиенту)
                                          >15 дн office.claim.requested    ──▶ Юрист (претензия)
                                          >30 дн office.lawsuit.requested  ──▶ Юрист (иск)
                                          >45 дн office.payment.escalated  ──▶ Владелец/РОП (эскалация)

    Склад ──wms.shipment.completed──▶ ОФИС   (двигаем в «Отгружено»)
    Логистика ──logistics.delivery.delivered──▶ ОФИС   (трекинг доставки)
    Финансы ──finance.payment.received──▶ ОФИС   (двигаем в «Оплачено»)

Шина — transactional outbox (``core/services/eventbus.py``): ``emit`` пишет событие
в той же транзакции, доставка подписчикам — relay (at-least-once). Обработчики с
двумя параметрами получают ``ctx`` (сессия + фасад сервисов), см. ``EventContext``.

AI-маршрутизация событий (приоритезация, авто-claims, прогноз оплаты) — Итерация 1.
Здесь — детерминированная проводка без AI.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.office.models import OfficeDoc

logger = logging.getLogger("aios.office")

# --- Пороги контроля дебиторской задолженности (ТЗ §4.2 · 5/15/30/45) ---
OVERDUE_REMINDER_DAYS = 5     # > 5 дн  — напоминание клиенту
OVERDUE_CLAIM_DAYS = 15       # > 15 дн — претензия (Юрист)
OVERDUE_LAWSUIT_DAYS = 30     # > 30 дн — исковое заявление (Юрист)
OVERDUE_ESCALATE_DAYS = 45    # > 45 дн — эскалация владельцу / РОП

# Сумма дебиторки (BYN), выше которой документ помечается как кредитный риск
# для Финансов/РОП. Это НЕ согласование исходящего платежа (та матрица —
# у казначейства, ТЗ §4.2 «платёж свыше 10 000»), а контроль входящей задолженности.
LARGE_RECEIVABLE_THRESHOLD = Decimal("10000")


# --------------------------------------------------------------------------- #
#  Исходящие события (emit-хелперы) — вызываются из routes.py и обработчиков.
# --------------------------------------------------------------------------- #
def _doc_payload(doc: OfficeDoc, **extra: Any) -> dict:
    """Единый снимок документа для события (то, что нужно соседним отделам)."""
    payload = {
        "doc_id": doc.id,
        "number": doc.number,
        "company": doc.company,
        "title": doc.title,
        "amount": float(doc.amount or 0),
        "stage": doc.stage,
        "owner": doc.owner,
        "region": doc.region,
        "weight": doc.weight,
        "address": doc.address,
        "sales_ref": doc.sales_ref,
        "entity_ref": doc.number or f"office:{doc.id}",
    }
    payload.update(extra)
    return payload


def emit_doc_created(bus, session: AsyncSession, doc: OfficeDoc) -> None:
    """Документ заведён в офисе (для аудита/дашборда владельца)."""
    bus.emit(session, "office.doc.created", _doc_payload(doc))


def emit_reservation_requested(bus, session: AsyncSession, doc: OfficeDoc) -> None:
    """→ Склад: поставить/держать резерв товара под выигранную сделку.

    Резерв должен подтверждаться ДО запроса отгрузки, иначе сборка может уйти
    в дефицит. В прототипе — событие-уведомление; подтверждение остатка из 1С/WMS
    приходит обратно и обновляет документ (см. on_shipment_completed).
    """
    bus.emit(session, "office.reservation.requested", _doc_payload(doc))


def emit_shipment_requested(bus, session: AsyncSession, doc: OfficeDoc) -> None:
    """→ Склад: собрать и подготовить заказ к отгрузке."""
    bus.emit(session, "office.shipment.requested", _doc_payload(doc))


def emit_carrier_request(
    bus,
    session: AsyncSession,
    doc: OfficeDoc,
    *,
    log_ref: str,
    carrier: str,
    carrier_name: str,
    region: str,
    pickup_date: str = "",
    contact: str = "",
    comment: str = "",
) -> None:
    """→ Логистика: заявка перевозчику на доставку по РБ (кнопка из карточки)."""
    bus.emit(
        session,
        "logistics.delivery.requested",
        _doc_payload(
            doc,
            log_ref=log_ref,
            carrier=carrier,
            carrier_name=carrier_name,
            region=region or doc.region,
            pickup_date=pickup_date,
            contact=contact,
            comment=comment,
            entity_ref=log_ref,
        ),
    )


def emit_docs_collected(bus, session: AsyncSession, doc: OfficeDoc) -> None:
    """→ Финансы: пакет документов собран, можно выставлять/ждать оплату."""
    bus.emit(session, "office.docs.collected", _doc_payload(doc))


def emit_payment_awaiting(bus, session: AsyncSession, doc: OfficeDoc) -> None:
    """→ Финансы: ожидаем оплату. Крупная дебиторка помечается как кредитный риск."""
    large_receivable = Decimal(str(doc.amount or 0)) > LARGE_RECEIVABLE_THRESHOLD
    bus.emit(
        session,
        "office.payment.awaiting",
        _doc_payload(
            doc,
            large_receivable=large_receivable,
            threshold=float(LARGE_RECEIVABLE_THRESHOLD),
        ),
    )


# --- Лестница эскалации просрочки дебиторки (ТЗ §4.2: 5 / 15 / 30 / 45) ---
def escalate_overdue(bus, session: AsyncSession, doc: OfficeDoc) -> str | None:
    """Подобрать ступень эскалации по числу дней просрочки и эмитнуть событие.

    В проде вызывается ежедневным планировщиком по всем неоплаченным документам;
    в прототипе — при переходе в «Ожидают оплаты» по текущему ``overdue_days``.
    Возвращает имя сработавшей ступени либо ``None``.

    Оплаченный документ не эскалируем: планировщик, идущий по всем строкам, не должен
    слать претензию/иск по уже закрытой оплате (деньги собственника, PLATFORM #1).
    """
    if doc.stage == "paid":
        return None
    days = int(doc.overdue_days or 0)
    if days > OVERDUE_ESCALATE_DAYS:
        bus.emit(session, "office.payment.escalated", _doc_payload(doc, overdue_days=days, step="escalation"))
        return "escalation"
    if days > OVERDUE_LAWSUIT_DAYS:
        bus.emit(session, "office.lawsuit.requested", _doc_payload(doc, overdue_days=days, step="lawsuit"))
        return "lawsuit"
    if days > OVERDUE_CLAIM_DAYS:
        bus.emit(session, "office.claim.requested", _doc_payload(doc, overdue_days=days, step="claim"))
        return "claim"
    if days > OVERDUE_REMINDER_DAYS:
        bus.emit(session, "office.payment.reminder", _doc_payload(doc, overdue_days=days, step="reminder"))
        return "reminder"
    return None


def emit_payment_overdue(bus, session: AsyncSession, doc: OfficeDoc) -> str | None:
    """Совместимость: делегирует в лестницу эскалации ``escalate_overdue``."""
    return escalate_overdue(bus, session, doc)


def is_ready_for_carrier(doc: OfficeDoc) -> bool:
    """Можно ли вызывать перевозчика: документ на стадии «Готово к отгрузке».

    Нельзя заказывать доставку для уже отгруженного/оплаченного документа —
    это защищает от ошибочных заявок и двойной логистики.
    """
    return doc.stage == "ready"


# --------------------------------------------------------------------------- #
#  Входящие события (обработчики) — регистрируются в module.register().
# --------------------------------------------------------------------------- #
def _first(payload: dict, *keys: str, default: str = "") -> str:
    """Достать первое непустое значение из payload по списку возможных ключей."""
    for k in keys:
        v = payload.get(k)
        if v not in (None, ""):
            return str(v)
    return default


def _deal_id(payload: dict) -> int | None:
    """Целочисленная ручка сделки из payload (``deal_id``) — общий ключ с финансами.

    Пусто/не-число → None (документ создан вне сделки/событие без ручки — join не сработает,
    но и падать не будем).
    """
    raw = payload.get("deal_id")
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _outstanding(payload: dict) -> Decimal:
    """Остаток к оплате из события (``outstanding``, строка BYN). Нет/мусор → 0 (=полная оплата).

    Событие без ``outstanding`` (напр. старый формат) трактуем как полную оплату — обратная
    совместимость: документ закрывается, как и прежде.
    """
    raw = payload.get("outstanding")
    if raw in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


async def _find_doc(session: AsyncSession, **by: Any) -> OfficeDoc | None:
    """Найти документ по любому из ref-полей (sales/wms/logistics/finance/number/deal_id).

    Значения — строки-ссылки либо целочисленный ``deal_id``; пустые (None/"" /0) пропускаем.
    Первое совпадение по порядку ключей (deal_id — самый надёжный, ставить первым).
    """
    for field, value in by.items():
        if not value:
            continue
        col = getattr(OfficeDoc, field, None)
        if col is None:
            continue
        row = (
            await session.execute(select(OfficeDoc).where(col == value).limit(1))
        ).scalars().first()
        if row is not None:
            return row
    return None


async def on_deal_won(payload: dict, ctx) -> None:
    """CRM: сделка выиграна → завести документ в стадии «Готово к отгрузке».

    Сразу ставим резерв на складе и просим собрать заказ — две разные команды
    Складу (держать остаток и физически собрать).
    """
    session: AsyncSession = ctx.session
    sales_ref = _first(payload, "deal_ref", "number", "deal_id", "entity_ref")

    existing = await _find_doc(session, sales_ref=sales_ref)
    if existing is not None:
        logger.info("office: deal %s уже заведён как %s", sales_ref, existing.number)
        return

    doc = OfficeDoc(
        deal_id=_deal_id(payload),                       # целочисленная ручка для join с финансами
        company=_first(payload, "company", "client", "counterparty"),
        title=_first(payload, "title", "subject", "product"),
        amount=Decimal(str(payload.get("amount") or 0)),
        owner=_first(payload, "owner", "manager", "by"),
        region=_first(payload, "region", "city"),
        weight=_first(payload, "weight"),
        address=_first(payload, "address"),
        sales_ref=sales_ref,
        stage="ready",
        docs_status="Ожидает отгрузки",
        next_step="Поставить резерв и передать на склад для сборки",
    )
    session.add(doc)
    await session.flush()
    if not doc.number:
        doc.number = f"ДОК-2026-{doc.id:04d}"

    bus = ctx.services.event_bus
    emit_doc_created(bus, session, doc)
    emit_reservation_requested(bus, session, doc)  # держим остаток под сделку
    emit_shipment_requested(bus, session, doc)      # просим Склад собрать заказ
    logger.info("office: создан %s по сделке %s", doc.number, sales_ref)


async def on_shipment_completed(payload: dict, ctx) -> None:
    """Склад: отгрузка собрана → двигаем документ в «Отгружено»."""
    session: AsyncSession = ctx.session
    doc = await _find_doc(
        session,
        wms_ref=_first(payload, "wms_ref", "shipment_ref"),
        sales_ref=_first(payload, "sales_ref", "deal_ref"),
        number=_first(payload, "doc_number", "number"),
    )
    if doc is None:
        logger.warning("office: wms.shipment.completed — документ не найден (%s)", payload)
        return
    doc.wms_ref = _first(payload, "wms_ref", "shipment_ref", default=doc.wms_ref)
    doc.stage = "shipped"
    doc.docs_status = "Отгружено, готовим документы"
    doc.next_step = "Собрать пакет документов (ТТН, счёт-фактура, ЭСЧФ, акт)"


async def on_delivery_delivered(payload: dict, ctx) -> None:
    """Логистика: перевозчик доставил груз → фиксируем трекинг в документе."""
    session: AsyncSession = ctx.session
    doc = await _find_doc(
        session,
        logistics_ref=_first(payload, "log_ref", "logistics_ref"),
        number=_first(payload, "doc_number", "number"),
    )
    if doc is None:
        logger.warning("office: logistics.delivery.delivered — документ не найден (%s)", payload)
        return
    doc.delivery = _first(payload, "carrier_name", "carrier", default=doc.delivery)
    doc.op_date = _first(payload, "delivered_at", "date", default=doc.op_date or "")
    doc.docs_status = "Доставлено, закрываем документы"


async def on_payment_received(payload: dict, ctx) -> None:
    """Финансы: оплата получена → двигаем документ в «Оплачено» и снимаем просрочку.

    Сопоставление с документом — по ``deal_id`` (у финансов нет номера офисного документа;
    единственный общий ключ — целочисленная ручка сделки). ``ref`` события = номер счёта 1С,
    сохраняем как ``finance_ref`` (провенанс связи).

    ⚠ Частичная оплата: ``finance.payment.received`` эмитится на КАЖДОЕ поступление, включая
    частичное (``outstanding`` > 0). Двигать в «Оплачено» при остатке — врать про деньги
    собственника (PLATFORM #1), поэтому закрываем документ ТОЛЬКО когда остаток = 0; при
    частичной оплате показываем остаток и оставляем стадию/просрочку как есть.
    """
    session: AsyncSession = ctx.session
    doc = await _find_doc(
        session,
        deal_id=_deal_id(payload),
        finance_ref=_first(payload, "finance_ref", "invoice_ref"),
        sales_ref=_first(payload, "sales_ref", "deal_ref"),
        number=_first(payload, "doc_number", "number"),
    )
    if doc is None:
        logger.warning("office: finance.payment.received — документ не найден (%s)", payload)
        return
    doc.finance_ref = _first(payload, "finance_ref", "invoice_ref", "ref", default=doc.finance_ref)

    if _outstanding(payload) > 0:  # частичная оплата — документ не закрываем
        doc.docs_status = f"Частичная оплата, остаток {_first(payload, 'outstanding', default='?')} BYN"
        return

    doc.stage = "paid"
    doc.docs_status = "Оплачено"
    doc.overdue_days = 0
    doc.next_step = "Сделка закрыта"


async def on_delivery_tracking(payload: dict, ctx) -> None:
    """Логистика: промежуточный статус перевозки → отражаем на карточке документа.

    Офис-менеджер «работает в логистике» — видит состояние перевозки прямо на
    документе. Сопоставление по ``logistics_ref`` (= номер отгрузки логистики).
    """
    session: AsyncSession = ctx.session
    doc = await _find_doc(
        session,
        logistics_ref=_first(payload, "log_ref", "logistics_ref", "number"),
        number=_first(payload, "doc_number"),
    )
    if doc is None:
        logger.info("office: logistics.delivery.tracking — документ не найден (%s)", payload)
        return
    status = _first(payload, "tracking_status")
    if status:
        doc.docs_status = f"Доставка: {status}"
    doc.delivery = _first(payload, "carrier_name", "carrier", default=doc.delivery)
