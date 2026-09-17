from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from modules.logistics import routes
from modules.logistics.models import CarrierRfq, ImportShipment, Shipment
from modules.logistics.schemas import (
    BidCreate,
    CarrierCreate,
    CarrierTariffUpdate,
    ImportShipmentCreate,
    ImportStageUpdate,
    RfqCreate,
    ShipmentCreate,
    StatusUpdate,
    VehicleCreate,
)


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return self


class Session:
    def __init__(self, *results, objects=None):
        self.results = list(results)
        self.objects = objects or {}
        self.added = []
        self.commits = 0
        self.refreshed = []

    async def execute(self, _statement):
        return self.results.pop(0)

    async def get(self, model, identity):
        return self.objects.get((model, identity))

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        for index, value in enumerate(self.added, start=1):
            if getattr(value, "id", None) is None:
                value.id = index

    async def commit(self):
        self.commits += 1

    async def refresh(self, value):
        if getattr(value, "id", None) is None:
            value.id = len(self.added)
        self.refreshed.append(value)


class Bus:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


def core_with(bus: Bus):
    return SimpleNamespace(event_bus=bus)


@pytest.mark.asyncio
async def test_create_shipment_import_and_rfq_generate_numbers_and_decimal_money():
    shipment_session = Session()
    shipment = await routes.create_shipment(
        ShipmentCreate(customer="ООО Альфа", weight_kg=12.5, amount=45.6), shipment_session
    )
    assert (shipment.id, shipment.number, shipment.weight_kg, shipment.amount) == (
        1,
        "ЛОГ-2026-0001",
        Decimal("12.5"),
        Decimal("45.6"),
    )

    import_session = Session()
    imported = await routes.create_import(
        ImportShipmentCreate(supplier="Shenzhen", amount=1500.25), import_session
    )
    assert (imported.id, imported.number, imported.amount) == (
        1,
        "ИМП-2026-0001",
        Decimal("1500.25"),
    )

    rfq_session = Session()
    rfq = await routes.create_rfq(RfqCreate(cargo="АКБ", weight_kg=250, declared_value=9000), rfq_session)
    assert (rfq.id, rfq.number, rfq.weight_kg, rfq.declared_value) == (
        1,
        "ТНД-2026-0001",
        Decimal("250.0"),
        Decimal("9000.0"),
    )
    assert all(session.commits == 1 and session.refreshed for session in (shipment_session, import_session, rfq_session))


@pytest.mark.asyncio
async def test_delivered_shipment_emits_sales_office_and_freight_events_and_handles_404():
    shipment = Shipment(
        id=7,
        number="ЛОГ-2026-0007",
        customer="ООО Альфа",
        carrier="DPD",
        amount=Decimal("12.50"),
        status="in_transit",
        eta="2026-09-18",
        deal_id=31,
    )
    session = Session(objects={(Shipment, 7): shipment})
    bus = Bus()

    out = await routes.update_shipment(7, StatusUpdate(status="delivered"), core_with(bus), session)

    assert out is shipment and shipment.status == "delivered"
    assert session.commits == 1 and session.refreshed == [shipment]
    assert [event for _, event, _ in bus.calls] == [
        "logistics.shipment.delivered",
        "logistics.delivery.delivered",
        "logistics.freight.cost",
    ]
    assert bus.calls[2][2] == {
        "deal_id": 31,
        "ref": "ЛОГ-2026-0007",
        "carrier": "DPD",
        "amount": "12.50",
        "leg": "domestic",
        "entity_ref": "shipment:7",
    }

    with pytest.raises(HTTPException, match="Отгрузка не найдена") as exc:
        await routes.update_shipment(404, StatusUpdate(status="delivered"), core_with(Bus()), Session())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_import_warehouse_transition_emits_clearance_arrival_and_idempotent_freight(monkeypatch):
    imported = ImportShipment(
        id=11,
        supplier="Shenzhen",
        container_no="CONT-11",
        cargo="контроллеры",
        qty=20,
        po_ref="PO-11",
        amount=Decimal("800"),
        stage="customs",
    )
    session = Session(objects={(ImportShipment, 11): imported})
    bus = Bus()
    monkeypatch.setattr(routes, "_import_freight_already_emitted", AsyncMock(return_value=False))

    out = await routes.update_import(
        11,
        ImportStageUpdate(stage="warehouse", customs_status="cleared"),
        core_with(bus),
        session,
    )

    assert out is imported and (imported.stage, imported.customs_status) == ("warehouse", "cleared")
    assert [event for _, event, _ in bus.calls] == [
        "logistics.import.customs_cleared",
        "logistics.import.arrived",
        "logistics.freight.cost",
    ]
    assert bus.calls[-1][2]["ref"] == "import:11"
    assert bus.calls[-1][2]["amount"] == "800"


@pytest.mark.asyncio
async def test_carrier_vehicle_zone_and_tariff_handlers_mutate_real_models_and_return_404():
    carrier_session = Session()
    carrier = await routes.create_carrier(CarrierCreate(name="Новый перевозчик", code="new"), carrier_session)
    assert carrier is carrier_session.added[0]
    assert (carrier.name, carrier.code, carrier.active) == ("Новый перевозчик", "new", True)

    vehicle_session = Session()
    vehicle = await routes.add_vehicle("new", VehicleCreate(vehicle_class="Тент", capacity_kg=5000), vehicle_session)
    assert vehicle is vehicle_session.added[0]
    assert (vehicle.carrier_code, vehicle.vehicle_class, vehicle.capacity_kg) == ("new", "Тент", 5000)

    zones = [SimpleNamespace(code="z1"), SimpleNamespace(code="z2")]
    assert await routes.list_zones(Session(Result(zones))) == zones

    tariff = SimpleNamespace(price_w5=Decimal("10"), pickup_fee=Decimal("0"))
    tariff_session = Session(Result([tariff]))
    updated = await routes.update_carrier_tariff(
        "new", "z1", CarrierTariffUpdate(price_w5=12.5, pickup_fee=3), tariff_session
    )
    assert updated is tariff
    assert (tariff.price_w5, tariff.pickup_fee) == (Decimal("12.5"), Decimal("3"))
    assert tariff_session.commits == 1 and tariff_session.refreshed == [tariff]

    with pytest.raises(HTTPException, match="Тариф не найден") as exc:
        await routes.update_carrier_tariff("new", "missing", CarrierTariffUpdate(price_w5=1), Session(Result()))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_add_bid_moves_rfq_to_collecting_marks_invite_and_returns_dto():
    rfq = CarrierRfq(id=21, status="sent")
    invite = SimpleNamespace(status="sent")
    session = Session(Result([invite]), objects={(CarrierRfq, 21): rfq})

    out = await routes.add_bid(
        21,
        BidCreate(carrier_code="dpd", price=99.5, eta_days=2, vehicle_class="Тент", comment="готовы"),
        session,
    )

    assert out.model_dump() == {
        "id": 1,
        "rfq_id": 21,
        "carrier_code": "dpd",
        "carrier": routes._carrier_name("dpd"),
        "price": 99.5,
        "eta_days": 2,
        "vehicle_class": "Тент",
        "valid_until": "",
        "comment": "готовы",
        "round": 1,
        "is_best": False,
        "is_best_value": False,
        "value_score": 0,
    }
    assert rfq.status == "collecting" and invite.status == "responded"
    assert session.commits == 1 and session.refreshed == [session.added[0]]


@pytest.mark.asyncio
async def test_get_rfq_exposes_not_found_boundary_without_query_execution():
    with pytest.raises(HTTPException, match="Тендер не найден") as exc:
        await routes.get_rfq(404, Session())
    assert exc.value.status_code == 404
