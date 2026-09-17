from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.logistics import events as logistics_events
from modules.procurement import events as procurement_events
from modules.production import events as production_events
from modules.wms import events as wms_events


class Result:
    def __init__(self, rows=(), scalar=None):
        self.rows = list(rows)
        self.scalar = scalar

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return self


class Bus:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class Session:
    def __init__(self, *results):
        self.results = list(results)
        self.added = []
        self.deleted = []
        self._next_id = 10

    async def execute(self, _statement):
        return self.results.pop(0)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = self._next_id
                self._next_id += 1

    async def delete(self, value):
        self.deleted.append(value)


def context(session, bus=None):
    return SimpleNamespace(session=session, services=SimpleNamespace(event_bus=bus or Bus()))


@pytest.mark.asyncio
async def test_procurement_event_handlers_create_claims_requests_and_requirements(monkeypatch):
    session = Session()
    ctx = context(session)
    await procurement_events.on_production_scrap({"item": "Bolt", "reason": "defect"}, ctx)
    assert session.added[-1].source == "production"

    request = AsyncMock()
    monkeypatch.setattr("modules.procurement.routes._request_from_deficit", request)
    await procurement_events.on_stock_low({"sku_code": "S-1", "deficit": 3}, ctx)
    request.assert_awaited_once()
    await procurement_events.on_stock_low({}, ctx)

    existing = SimpleNamespace(sku_code="OLD")
    session = Session(Result([existing]))
    ctx = context(session)
    await procurement_events.on_ship_deadline_set(
        {
            "deal_id": 7, "number": "D-7", "ship_deadline": "2026-10-01", "items": [
                {"sku_code": "NEW", "qty": "2"}, {"sku_code": "NEW", "qty": "3"}
            ],
        },
        ctx,
    )
    assert any(getattr(row, "sku_code", None) == "NEW" for row in session.added)
    assert session.deleted == [existing]
    await procurement_events.on_ship_deadline_set({"items": []}, ctx)


@pytest.mark.asyncio
async def test_procurement_reference_recompute_is_deduplicated(monkeypatch):
    recompute = AsyncMock()
    monkeypatch.setattr("modules.procurement.routes._recompute_estimated_landed", recompute)
    session = Session(Result(["S-2", "S-1"]))
    ctx = context(session)
    await procurement_events.on_reference_changed(
        {"ref_key": "core.tnved", "entity_ref": "tnved:8507"}, ctx
    )
    assert recompute.await_count == 2
    assert ctx._procurement_ref_recomputed == {"S-1", "S-2"}
    session.results.append(Result(["S-1", "S-3"]))
    await procurement_events.on_reference_changed(
        {"ref_key": "core.tnved", "entity_ref": "tnved:8507"}, ctx
    )
    assert recompute.await_count == 3
    assert await procurement_events._affected_skus(Session(), "other", "x") == []


@pytest.mark.asyncio
async def test_logistics_event_handlers_cover_spot_contract_and_import_markers():
    assert logistics_events._to_decimal("bad") == Decimal("0")
    assert logistics_events._looks_like_import({"origin": "import"}) is True
    assert logistics_events._looks_like_import({"country": "BY"}) is False
    assert logistics_events._looks_like_import({"country": "CN"}) is True

    bus = Bus()
    session = Session()
    ctx = context(session, bus)
    await logistics_events.on_document_posted({"kind": "order", "counterparty": "ACME", "deal_id": 2}, ctx)
    assert session.added[-1].status == "planned"
    assert bus.calls[-1][1] == "logistics.shipment.created"

    await logistics_events.on_office_delivery_requested(
        {"mode": "spot", "log_ref": "OFF-1", "company": "ACME", "weight": "2"}, ctx
    )
    assert session.added[-1].number == "OFF-1"

    contract_session = Session()
    contract_ctx = context(contract_session, bus)
    await logistics_events.on_office_delivery_requested(
        {"mode": "contract", "title": "Cargo", "weight": "3", "amount": "10", "region": "Minsk"}, contract_ctx
    )
    assert contract_session.added[-1].status == "draft"
    assert bus.calls[-1][1] == "logistics.rfq.created"


@pytest.mark.asyncio
async def test_logistics_received_import_creates_and_updates_info_only():
    bus = Bus()
    session = Session(Result([]))
    ctx = context(session, bus)
    await logistics_events.on_procurement_received(
        {"entity_ref": "purchase:1", "item": "Battery", "qty": 4, "country": "CN"}, ctx
    )
    assert session.added[-1].stage == "warehouse"
    assert bus.calls[-1][1] == "logistics.import.received"

    existing = SimpleNamespace(id=5, number="IMP-5", stage="customs", customs_status="", amount=None, eta=None, supplier="Supplier")
    session = Session(Result([existing]))
    ctx = context(session, bus)
    await logistics_events.on_procurement_received({"entity_ref": "purchase:2", "item": "x"}, ctx)
    assert existing.stage == "warehouse"
    assert existing.customs_status == "Принято закупкой"
    await logistics_events.on_procurement_received({"entity_ref": "doc:2", "country": "CN"}, ctx)


@pytest.mark.asyncio
async def test_production_and_wms_event_handlers_preserve_idempotency():
    session = Session(Result([]))
    ctx = context(session)
    await production_events.on_deal_handoff({"deal_id": 7, "product": "Battery", "qty": "3"}, ctx)
    assert session.added[-1].month == 7
    duplicate = Session(Result([SimpleNamespace(id=1)]))
    await production_events.on_deal_handoff({"deal_id": 7}, context(duplicate))
    assert duplicate.added == []
    await production_events.on_order_received({"po_number": "PO-1"}, ctx)

    wms_session = Session(Result([SimpleNamespace(title="Battery")]))
    await wms_events.on_stock_reserved(
        {"doc_ref": "deal:7", "items": [{"sku_code": "S-1", "qty": "2"}, {"sku_code": "S-2", "qty": "1"}]},
        context(wms_session),
    )
    assert len(wms_session.added) == 4
    await wms_events.on_stock_released({"items": [{"sku_code": "S-1", "qty": "1"}]}, context(wms_session))

    receipt_session = Session(Result([SimpleNamespace(title="Battery")]))
    await wms_events.on_goods_received(
        {"sku_code": "S-1", "qty": "5", "entity_ref": "purchase:1"}, context(receipt_session)
    )
    assert receipt_session.added[-1].sku_title == "Battery"
