from decimal import Decimal
from types import SimpleNamespace

import pytest

from modules.logistics import events


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for index, obj in enumerate(self.added, start=1):
            if getattr(obj, "id", None) is None:
                obj.id = index


class FakeBus:
    def __init__(self):
        self.events = []

    def emit(self, session, event_type, payload):
        self.events.append((event_type, payload))


def _ctx():
    session = FakeSession()
    bus = FakeBus()
    return SimpleNamespace(session=session, services=SimpleNamespace(event_bus=bus)), session, bus


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, Decimal("0")), ("", Decimal("0")), ("2.50", Decimal("2.50")), ("bad", Decimal("0"))],
)
def test_logistics_decimal_parser_is_fail_soft(raw, expected):
    assert events._to_decimal(raw) == expected


@pytest.mark.parametrize(
    "payload",
    [{"origin": "import"}, {"origin": "IMPORT"}, {"incoterms": "FOB"}, {"country": "CN"}],
)
def test_import_marker_matrix(payload):
    assert events._looks_like_import(payload) is True


@pytest.mark.parametrize("country", ["РБ", "BY", "BLR", "Беларусь", "РФ", "RU", "RUSSIA", "Россия"])
def test_domestic_countries_do_not_create_import_marker(country):
    assert events._looks_like_import({"country": country}) is False


@pytest.mark.asyncio
async def test_document_posted_creates_planned_shipment_and_event():
    ctx, session, bus = _ctx()
    await events.on_document_posted({"kind": "order", "counterparty": "ООО Альфа", "deal_id": 7, "entity_ref": "order:7"}, ctx)
    shipment = session.added[0]
    assert shipment.customer == "ООО Альфа"
    assert shipment.status == "planned"
    assert bus.events == [("logistics.shipment.created", {"customer": "ООО Альфа", "deal_id": 7, "entity_ref": "order:7"})]
    await events.on_document_posted({"kind": "invoice"}, ctx)
    await events.on_document_posted({"kind": "order"}, None)
    assert len(session.added) == 1


@pytest.mark.asyncio
async def test_office_delivery_spot_and_contract_map_payload_to_real_models():
    ctx, session, bus = _ctx()
    await events.on_office_delivery_requested(
        {"log_ref": "LOG-1", "number": "OFF-1", "company": "Альфа", "title": "Коробки", "weight": "3.5", "region": "Минск", "carrier": "cdek", "carrier_name": "СДЭК", "deal_id": 11},
        ctx,
    )
    shipment = session.added[0]
    assert shipment.number == "LOG-1"
    assert shipment.weight_kg == Decimal("3.5")
    assert shipment.carrier_code == "cdek"
    assert bus.events[-1][0] == "logistics.shipment.created"

    await events.on_office_delivery_requested(
        {"mode": "contract", "number": "OFF-2", "title": "Паллеты", "weight": "bad", "amount": "250", "region": "Брест", "owner": "Оператор", "zone_code": "W"},
        ctx,
    )
    rfq = session.added[1]
    assert rfq.status == "draft"
    assert rfq.weight_kg == Decimal("0")
    assert rfq.declared_value == Decimal("250")
    assert rfq.number == "ТНД-2026-0002"
    assert bus.events[-1][0] == "logistics.rfq.created"
