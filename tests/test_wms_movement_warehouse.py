"""Manual stock writes require an explicit active warehouse in the exact company."""
# ruff: noqa: F811 -- imported pytest fixture
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from core.domain.models import Sku
from modules.accounting.models import Organization
from modules.wms.models import StockMovement, WarehouseDirectory
from tests.test_erp import erp_organization  # noqa: F401


@pytest_asyncio.fixture
async def movement_scope(api, session, erp_organization):
    created = await api.post(f"/wms/organizations/{erp_organization}/warehouses",
                             json={"name": "ERP-WH", "title": "Synthetic owned"})
    assert created.status_code == 201, created.text
    own = await session.get(WarehouseDirectory, created.json()["id"])
    assert own is not None and own.wms_enabled is False and own.prohibit_negative_stock is True
    foreign = Organization(name="Synthetic foreign warehouse owner", unp="999999991")
    session.add(foreign)
    await session.flush()
    session.add_all([
        WarehouseDirectory(organization_id=erp_organization, name="INACTIVE-WH", title="Synthetic inactive",
                           wms_enabled=False, prohibit_negative_stock=True, is_active=False, created_by="erp-test-owner"),
        WarehouseDirectory(organization_id=foreign.id, name="FOREIGN-WH", title="Synthetic foreign",
                           wms_enabled=False, prohibit_negative_stock=True, is_active=True, created_by="synthetic-other"),
        Sku(code="SYN-MOVE", title="Synthetic movement item", unit="шт"),
    ])
    await session.commit()
    return erp_organization, own


@pytest.mark.parametrize("warehouse", [None, "", "   "], ids=["omitted", "empty", "whitespace"])
async def test_movement_requires_explicit_nonempty_warehouse(api, session, movement_scope, warehouse):
    org, _ = movement_scope
    body = {"organization_id": org, "sku_code": "SYN-MOVE", "kind": "in", "qty": "2"}
    if warehouse is not None:
        body["warehouse"] = warehouse
    result = await api.post("/wms/movements", json=body)
    assert result.status_code == 422, result.text
    assert (await session.scalars(select(StockMovement))).all() == []


@pytest.mark.parametrize("warehouse", ["UNKNOWN-WH", "INACTIVE-WH", "FOREIGN-WH"],
                         ids=["unknown", "inactive", "foreign"])
async def test_movement_requires_active_owned_warehouse(api, session, movement_scope, warehouse):
    org, _ = movement_scope
    result = await api.post("/wms/movements", json={"organization_id": org, "warehouse": warehouse,
                            "sku_code": "SYN-MOVE", "kind": "in", "qty": "2"})
    assert result.status_code == 409, result.text
    assert result.json()["detail"] == "Склад неизвестен, неактивен или недоступен в этой организации"
    assert (await session.scalars(select(StockMovement))).all() == []


@pytest.mark.parametrize("enabled", [False, True], ids=["document", "wms"])
async def test_owned_movement_keeps_mode_and_negative_stock_protection(api, session, movement_scope, enabled):
    org, warehouse = movement_scope
    warehouse.wms_enabled = enabled
    await session.commit()
    base = {"organization_id": org, "warehouse": "ERP-WH", "sku_code": "SYN-MOVE", "doc_ref": "SYN-WH-MOVE"}
    incoming = await api.post("/wms/movements", json={**base, "kind": "in", "qty": "2"})
    assert incoming.status_code == 201, incoming.text
    assert incoming.json()["organization_id"] == org and incoming.json()["warehouse"] == "ERP-WH"
    too_much = await api.post("/wms/movements", json={**base, "kind": "out", "qty": "3"})
    assert too_much.status_code == 409, too_much.text
    assert too_much.json()["detail"]["reason"] == "insufficient_stock"
    rows = (await session.scalars(select(StockMovement))).all()
    assert len(rows) == 1 and rows[0].id == incoming.json()["id"] and rows[0].qty == Decimal("2")
    outgoing = await api.post("/wms/movements", json={**base, "kind": "out", "qty": "1"})
    assert outgoing.status_code == 201, outgoing.text
    rows = (await session.scalars(select(StockMovement))).all()
    assert len(rows) == 2 and all(row.organization_id == org and row.warehouse == "ERP-WH" for row in rows)
    assert sum((row.qty if row.kind == "in" else -row.qty for row in rows), Decimal("0")) == Decimal("1")
    await session.refresh(warehouse)
    assert warehouse.wms_enabled is enabled and warehouse.prohibit_negative_stock is True


async def operation_body(session, org, endpoint, warehouse):
    from modules.wms.models import Location

    body = {"organization_id": org, "sku_code": "SYN-MOVE", "qty": "1"}
    if warehouse is not None:
        body["warehouse"] = warehouse
    if endpoint == "transfer":
        name = warehouse.strip() if warehouse and warehouse.strip() else "Главный"
        first = Location(warehouse=name, zone="A", code="SYN-FROM")
        second = Location(warehouse=name, zone="B", code="SYN-TO")
        session.add_all([first, second])
        await session.commit()
        body.update(from_location_id=first.id, to_location_id=second.id)
    return body


@pytest.mark.parametrize("endpoint", ["shipment", "transfer", "adjustment"])
@pytest.mark.parametrize("warehouse", [None, "", "   "], ids=["omitted", "empty", "whitespace"])
async def test_operation_requires_explicit_warehouse(api, session, movement_scope, endpoint, warehouse):
    org, _ = movement_scope
    body = await operation_body(session, org, endpoint, warehouse)
    result = await api.post(f"/wms/{endpoint}", json=body)
    assert result.status_code == 422, result.text
    assert (await session.scalars(select(StockMovement))).all() == []


@pytest.mark.parametrize("endpoint", ["shipment", "transfer", "adjustment"])
@pytest.mark.parametrize("warehouse", ["UNKNOWN-WH", "INACTIVE-WH", "FOREIGN-WH"],
                         ids=["unknown", "inactive", "foreign"])
async def test_operation_requires_active_owned_warehouse(api, session, movement_scope, endpoint, warehouse):
    org, _ = movement_scope
    body = await operation_body(session, org, endpoint, warehouse)
    result = await api.post(f"/wms/{endpoint}", json=body)
    assert result.status_code == 409, result.text
    assert result.json()["detail"] == "Склад неизвестен, неактивен или недоступен в этой организации"
    assert (await session.scalars(select(StockMovement))).all() == []


@pytest.mark.parametrize("endpoint", ["shipment", "transfer", "adjustment"])
@pytest.mark.parametrize("enabled", [False, True], ids=["document", "wms"])
async def test_qualified_operation_preserves_stock_and_location_guards(api, session, movement_scope, endpoint, enabled):
    from core.domain.models import OutboxEvent
    from modules.wms.models import Location

    org, warehouse = movement_scope
    warehouse.wms_enabled = enabled
    await session.commit()
    body = await operation_body(session, org, endpoint, "ERP-WH")
    incoming = await api.post("/wms/movements", json={"organization_id": org, "warehouse": "ERP-WH",
        "sku_code": "SYN-MOVE", "kind": "in", "qty": "3", "location_id": body.get("from_location_id")})
    assert incoming.status_code == 201, incoming.text
    wrong = Location(warehouse="OTHER-WH", zone="X", code="SYN-WRONG")
    session.add(wrong)
    await session.commit()
    bad_location = {**body, "from_location_id" if endpoint == "transfer" else "location_id": wrong.id}
    rejected = await api.post(f"/wms/{endpoint}", json=bad_location)
    assert rejected.status_code == 422, rejected.text
    assert len((await session.scalars(select(StockMovement))).all()) == 1
    if endpoint == "transfer":
        same = await api.post("/wms/transfer", json={**body, "to_location_id": body["from_location_id"]})
        assert same.status_code == 400, same.text
        assert len((await session.scalars(select(StockMovement))).all()) == 1
        moved = await api.post("/wms/transfer", json=body)
        assert moved.status_code == 201, moved.text
        pair = moved.json()
        assert len(pair) == 2 and {row["kind"] for row in pair} == {"in", "out"}
        assert {row["doc_ref"] for row in pair} == {pair[0]["doc_ref"]} and pair[0]["doc_ref"].startswith("TRF-")
        assert {row["location_id"] for row in pair} == {body["from_location_id"], body["to_location_id"]}
        expected, count = Decimal("3"), 3
    elif endpoint == "adjustment":
        added = await api.post("/wms/adjustment", json=body)
        assert added.status_code == 201, added.text
        zero = await api.post("/wms/adjustment", json={**body, "qty": "0"})
        assert zero.status_code == 400, zero.text
        too_much = await api.post("/wms/adjustment", json={**body, "qty": "-5"})
        assert too_much.status_code == 409, too_much.text
        assert too_much.json()["detail"]["reason"] == "insufficient_stock"
        assert len((await session.scalars(select(StockMovement))).all()) == 2
        removed = await api.post("/wms/adjustment", json={**body, "qty": "-1"})
        assert removed.status_code == 201, removed.text
        expected, count = Decimal("3"), 3
    else:
        body["doc_ref"] = "SYN-SHIP-1"
        too_much = await api.post("/wms/shipment", json={**body, "qty": "4"})
        assert too_much.status_code == 409, too_much.text
        assert too_much.json()["detail"]["reason"] == "insufficient_stock"
        assert len((await session.scalars(select(StockMovement))).all()) == 1
        shipped = await api.post("/wms/shipment", json=body)
        assert shipped.status_code == 201, shipped.text
        events = (await session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "wms.shipment.completed"))).all()
        assert len(events) == 1
        assert events[0].payload["organization_id"] == org and events[0].payload["warehouse"] == "ERP-WH"
        expected, count = Decimal("2"), 2
    rows = (await session.scalars(select(StockMovement))).all()
    assert len(rows) == count and all(row.organization_id == org and row.warehouse == "ERP-WH" for row in rows)
    assert sum((row.qty if row.kind == "in" else -row.qty for row in rows), Decimal("0")) == expected
    await session.refresh(warehouse)
    assert warehouse.wms_enabled is enabled and warehouse.prohibit_negative_stock is True


@pytest.mark.parametrize("explicit", [False, True], ids=["omitted", "explicit"])
async def test_retired_receipt_stays_closed(api, session, movement_scope, explicit):
    org, _ = movement_scope
    body = {"organization_id": org, "sku_code": "SYN-MOVE", "qty": "1"}
    if explicit:
        body["warehouse"] = "ERP-WH"
    result = await api.post("/wms/receipt", json=body)
    assert result.status_code == (409 if explicit else 422), result.text
    assert (await session.scalars(select(StockMovement))).all() == []


@pytest.mark.parametrize("enabled", [False, True], ids=["document", "wms"])
async def test_pack_shared_dto_keeps_explicit_mode_guard(api, session, movement_scope, enabled):
    org, warehouse = movement_scope
    warehouse.wms_enabled = enabled
    await session.commit()
    body = {"organization_id": org, "sku_code": "SYN-MOVE", "qty": "1"}
    omitted = await api.post("/wms/pack", json=body)
    assert omitted.status_code == 422, omitted.text
    assert (await session.scalars(select(StockMovement))).all() == []
    incoming = await api.post("/wms/movements", json={**body, "warehouse": "ERP-WH", "kind": "in", "qty": "2"})
    assert incoming.status_code == 201, incoming.text
    packed = await api.post("/wms/pack", json={**body, "warehouse": "ERP-WH"})
    assert packed.status_code == (201 if enabled else 409), packed.text
    rows = (await session.scalars(select(StockMovement))).all()
    assert len(rows) == (3 if enabled else 1)
    assert sum((row.qty if row.kind == "in" else -row.qty for row in rows), Decimal("0")) == Decimal("2")
    await session.refresh(warehouse)
    assert warehouse.wms_enabled is enabled and warehouse.prohibit_negative_stock is True
