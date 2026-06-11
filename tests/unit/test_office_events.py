"""Unit-тесты событийной логики office (без I/O) — лестница эскалации, emit-хелперы, гард.

Эмиссию проверяем через ``FakeBus`` (записывает вызовы ``emit``), документ —
транзиентный ORM-объект. БД не нужна: ``_doc_payload`` и лестница ``escalate_overdue``
работают только с атрибутами объекта и шиной.
"""
from decimal import Decimal

from modules.office import events
from modules.office.models import OfficeDoc


class FakeBus:
    """Заглушка шины: вместо outbox копит (event_type, payload) в список."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def emit(self, session, event_type: str, payload: dict, version: int = 1) -> None:
        self.events.append((event_type, payload))

    def types(self) -> list[str]:
        return [t for t, _ in self.events]


def _doc(**kw) -> OfficeDoc:
    return OfficeDoc(**kw)


# --- Лестница эскалации просрочки дебиторки (ТЗ §4.2 · 5/15/30/45) --------- #
def test_escalation_ladder_steps():
    cases = {
        5: (None, None),                       # ровно порог — ещё ничего
        10: ("reminder", "office.payment.reminder"),
        15: ("reminder", "office.payment.reminder"),   # «> 15» строго — 15 ещё reminder
        16: ("claim", "office.claim.requested"),
        30: ("claim", "office.claim.requested"),
        31: ("lawsuit", "office.lawsuit.requested"),
        45: ("lawsuit", "office.lawsuit.requested"),
        46: ("escalation", "office.payment.escalated"),
    }
    for days, (step, event_type) in cases.items():
        bus = FakeBus()
        result = events.escalate_overdue(bus, None, _doc(overdue_days=days))
        assert result == step, f"days={days}: ожидали ступень {step}, получили {result}"
        if event_type is None:
            assert bus.events == [], f"days={days}: не должно быть события"
        else:
            assert bus.types() == [event_type], f"days={days}: ждали {event_type}"
            assert bus.events[0][1]["step"] == step
            assert bus.events[0][1]["overdue_days"] == days


def test_escalation_zero_and_none_overdue():
    # overdue_days = 0 и None → ниже первого порога, ничего не эмитим
    bus = FakeBus()
    assert events.escalate_overdue(bus, None, _doc(overdue_days=0)) is None
    assert events.escalate_overdue(bus, None, _doc()) is None  # overdue_days не задан
    assert bus.events == []


def test_emit_payment_overdue_delegates_to_ladder():
    bus = FakeBus()
    step = events.emit_payment_overdue(bus, None, _doc(overdue_days=40))
    assert step == "lawsuit"
    assert bus.types() == ["office.lawsuit.requested"]


# --- Гард готовности к заявке перевозчику --------------------------------- #
def test_is_ready_for_carrier_only_ready_stage():
    assert events.is_ready_for_carrier(_doc(stage="ready")) is True
    for stage in ("shipped", "docs", "await_pay", "paid"):
        assert events.is_ready_for_carrier(_doc(stage=stage)) is False


# --- Исходящие emit-хелперы ----------------------------------------------- #
def test_emit_payment_awaiting_marks_large_receivable():
    bus = FakeBus()
    events.emit_payment_awaiting(bus, None, _doc(amount=Decimal("15000")))
    events.emit_payment_awaiting(bus, None, _doc(amount=Decimal("5000")))
    assert bus.types() == ["office.payment.awaiting", "office.payment.awaiting"]
    assert bus.events[0][1]["large_receivable"] is True    # 15000 > порог 10000
    assert bus.events[1][1]["large_receivable"] is False   # 5000 ≤ порог
    assert bus.events[0][1]["threshold"] == 10000.0


def test_emit_simple_outgoing_helpers():
    doc = _doc(number="ДОК-2026-0007", company="ООО Альфа", amount=Decimal("100"))
    bus = FakeBus()
    events.emit_doc_created(bus, None, doc)
    events.emit_reservation_requested(bus, None, doc)
    events.emit_shipment_requested(bus, None, doc)
    events.emit_docs_collected(bus, None, doc)
    assert bus.types() == [
        "office.doc.created",
        "office.reservation.requested",
        "office.shipment.requested",
        "office.docs.collected",
    ]
    # снимок документа в payload: номер прокинут как entity_ref
    assert bus.events[0][1]["entity_ref"] == "ДОК-2026-0007"
    assert bus.events[0][1]["company"] == "ООО Альфа"


def test_emit_carrier_request_payload():
    doc = _doc(number="ДОК-2026-0009", region="Минск")
    bus = FakeBus()
    events.emit_carrier_request(
        bus, None, doc,
        log_ref="ЛОГ-2026-0009", carrier="cdek", carrier_name="СДЭК",
        region="Гомель", pickup_date="2026-06-15", contact="Склад", comment="до 12:00",
    )
    assert bus.types() == ["logistics.delivery.requested"]
    p = bus.events[0][1]
    assert p["log_ref"] == "ЛОГ-2026-0009"
    assert p["carrier"] == "cdek" and p["carrier_name"] == "СДЭК"
    assert p["region"] == "Гомель"            # переданное направление перекрывает doc.region
    assert p["entity_ref"] == "ЛОГ-2026-0009"  # entity_ref = номер заявки логистики


def test_first_picks_first_non_empty():
    assert events._first({"a": "", "b": None, "c": "X"}, "a", "b", "c") == "X"
    assert events._first({}, "a", "b", default="def") == "def"


# --- Справочник перевозчиков ---------------------------------------------- #
def test_get_carrier_lookup():
    from modules.office.carriers import CARRIERS, get_carrier

    assert get_carrier("cdek")["name"] == "СДЭК"
    assert get_carrier("nope") is None
    # тяжёлый груз доступен у LTL/паллетных перевозчиков
    assert {c["id"] for c in CARRIERS if c["heavy"]} == {"dellin", "dpd", "own"}
