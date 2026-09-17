from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from modules.procurement import routes as procurement
from modules.procurement.models import PurchaseRequest
from modules.procurement.schemas import (
    DeficitRequestIn,
    PurchaseRequestCreate,
)
from modules.procurement.schemas import (
    StageUpdate as ProcurementStage,
)
from modules.wms import routes as wms
from modules.wms.schemas import AdjustmentIn, LocationCreate, MovementOpIn, TransferIn


class Scalars:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def scalars(self):
        return Scalars(self.rows)


class Session:
    def __init__(self, *results, by_id=None):
        self.results = list(results)
        self.by_id = by_id or {}
        self.added = []
        self.commits = 0
        self.flushes = 0
        self.refreshed = []

    async def execute(self, _statement):
        return self.results.pop(0) if self.results else Result()

    async def get(self, _model, identity):
        return self.by_id.get(identity)

    def add(self, value):
        self.added.append(value)

    def add_all(self, values):
        self.added.extend(values)

    async def flush(self):
        self.flushes += 1
        for index, value in enumerate(self.added, start=1):
            if getattr(value, "id", None) is None:
                value.id = index

    async def commit(self):
        self.commits += 1

    async def refresh(self, value):
        self.refreshed.append(value)


class Bus:
    def __init__(self):
        self.events = []

    def emit(self, session, event_type, payload):
        self.events.append((session, event_type, payload))


@pytest.mark.asyncio
async def test_wms_receipt_and_adjustment_preserve_operation_semantics():
    session = Session()
    received = await wms.receipt(
        MovementOpIn(sku_code="SKU-1", qty=2.5, doc_ref="REC-1"), session
    )
    corrected = await wms.adjustment(
        AdjustmentIn(sku_code="SKU-1", qty=-3, location_id=4), session
    )

    assert (received.kind, received.reason, received.qty, received.doc_ref) == (
        "in",
        "receipt",
        Decimal("2.5"),
        "REC-1",
    )
    assert (corrected.kind, corrected.reason, corrected.qty, corrected.location_id) == (
        "out",
        "adjustment",
        Decimal("3"),
        4,
    )
    assert session.commits == 2


@pytest.mark.asyncio
async def test_wms_shipment_emits_matchable_event_only_when_doc_ref_exists():
    bus = Bus()
    core = SimpleNamespace(event_bus=bus)
    session = Session()
    shipped = await wms.shipment(MovementOpIn(sku_code="SKU-1", qty=1, doc_ref="D-1"), session, core)
    assert shipped.kind == "out"
    assert bus.events[0][1] == "wms.shipment.completed"
    assert bus.events[0][2]["shipment_ref"] == "D-1"

    bus = Bus()
    session = Session()
    await wms.shipment(MovementOpIn(sku_code="SKU-2", qty=1), session, SimpleNamespace(event_bus=bus))
    assert bus.events == []


@pytest.mark.asyncio
async def test_wms_transfer_validates_positive_qty_and_distinct_locations():
    with pytest.raises(HTTPException, match="больше нуля"):
        await wms.transfer(TransferIn(sku_code="SKU", qty=0, from_location_id=1, to_location_id=2), Session())
    with pytest.raises(HTTPException, match="совпадают"):
        await wms.transfer(TransferIn(sku_code="SKU", qty=1, from_location_id=1, to_location_id=1), Session())

    session = Session()
    rows = await wms.transfer(TransferIn(sku_code="SKU", qty=1.5, from_location_id=1, to_location_id=2), session)
    assert len(rows) == 2
    assert rows[0].kind == "out" and rows[1].kind == "in"
    assert rows[0].doc_ref == rows[1].doc_ref == "TRF-00001"


@pytest.mark.asyncio
async def test_wms_create_location_maps_payload_and_commits():
    session = Session()
    location = await wms.create_location(LocationCreate(code="A-01", zone="A", title="Полка"), session)
    assert (location.warehouse, location.zone, location.code, location.title) == (
        "Главный",
        "A",
        "A-01",
        "Полка",
    )
    assert session.commits == 1 and session.refreshed == [location]


def test_procurement_score_components_keep_honest_empty_and_weighted_score():
    assert procurement._score_components(0, 0, None)["score"] is None
    assert procurement._score_components(10, 2, 0.8) == {
        "components": {"quality": 0.8, "timeliness": 0.8, "price": None},
        "score": 8.0,
    }
    assert procurement._score_components(0, 2, None)["components"]["quality"] == 0.0


@pytest.mark.asyncio
async def test_procurement_create_request_assigns_number_and_decimal_amount():
    session = Session()
    request = await procurement.create_request(
        PurchaseRequestCreate(supplier="Supplier", item="SKU-1", qty=3, amount=12.5), session
    )
    assert isinstance(request, PurchaseRequest)
    assert (request.number, request.amount, request.qty, request.stage) == (
        "ЗАК-2026-0001",
        Decimal("12.5"),
        3,
        "need",
    )
    assert session.commits == 1


@pytest.mark.asyncio
async def test_procurement_update_request_emits_received_event():
    request = SimpleNamespace(id=4, item="SKU-1", qty=2, stage="ordered")
    bus = Bus()
    session = Session(by_id={4: request})
    updated = await procurement.update_request(
        4,
        ProcurementStage(stage="qc"),
        SimpleNamespace(event_bus=bus),
        session,
    )
    assert updated is request and request.stage == "qc"
    assert bus.events[0][1] == "procurement.received"
    assert bus.events[0][2]["entity_ref"] == "purchase:4"


@pytest.mark.asyncio
async def test_procurement_auto_request_is_idempotent_and_ceil_qty():
    existing = SimpleNamespace(id=9, origin="deficit", item="Battery", stage="need")
    reused = Session(Result([existing]))
    assert await procurement._request_from_deficit(
        reused, sku_code="BAT", sku_title="Battery", deficit=4.1, reorder_qty=0
    ) is existing
    assert reused.added == []

    fresh = Session(Result([]))
    created = await procurement._request_from_deficit(
        fresh, sku_code="BAT", sku_title="", deficit=1.1, reorder_qty=2.1, warehouse="Минск"
    )
    assert created.item == "BAT"
    assert (created.qty, created.origin, created.number) == (3, "deficit", "ЗАК-2026-0001")


@pytest.mark.asyncio
async def test_procurement_request_from_deficit_handler_commits_and_refreshes():
    session = Session(Result([]))
    result = await procurement.request_from_deficit(
        DeficitRequestIn(sku_code="BAT", deficit=2, reorder_qty=2), session
    )
    assert result.item == "BAT"
    assert session.commits == 1 and session.refreshed == [result]
