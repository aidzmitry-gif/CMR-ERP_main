"""Organization isolation for cells, including identical warehouse names."""

from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from modules.wms.location_scope import validate_location_ids
from modules.wms.models import Location, StockMovement, WarehouseDirectory
from modules.wms.reservation_gateway import WmsReservationService


@pytest_asyncio.fixture
async def locations(api):
    result = []
    for actor, unp in [("location-owner", "999999931"), ("location-foreign", "999999932")]:
        api.headers["X-User"] = actor
        book = await api.post("/accounting/organizations", json={"name": actor, "unp": unp})
        assert book.status_code == 201, book.text
        org = book.json()["id"]
        warehouse = await api.post(f"/wms/organizations/{org}/warehouses", json={"name": "Shared", "title": "Synthetic"})
        assert warehouse.status_code == 201, warehouse.text
        cell = await api.post("/wms/locations", json={"organization_id": org, "warehouse": "Shared", "code": "CELL"})
        assert cell.status_code == 201, cell.text
        result.append((org, cell.json()["id"], warehouse.json()["id"]))
    api.headers["X-User"] = "location-owner"
    return result


async def test_same_name_warehouses_are_isolated_for_list_read_create_and_patch(api, session, locations):
    (own, own_cell, _), (foreign, foreign_cell, _) = locations
    listed = await api.get("/wms/locations")
    assert listed.status_code == 200, listed.text
    assert [(row["id"], row["organization_id"]) for row in listed.json()] == [(own_cell, own)]
    assert (await api.get(f"/wms/locations/{own_cell}")).json()["organization_id"] == own
    assert (await api.get(f"/wms/locations/{foreign_cell}")).status_code == 404
    assert (await api.get("/wms/locations", params={"organization_id": foreign})).status_code == 403
    denied = await api.post("/wms/locations", json={"organization_id": foreign, "warehouse": "Shared", "code": "FORGED"})
    assert denied.status_code == 403
    assert (await api.patch(f"/wms/locations/{foreign_cell}", json={"organization_id": own, "title": "FORGED"})).status_code == 404
    assert (await api.patch(f"/wms/locations/{foreign_cell}", json={"organization_id": foreign, "title": "FORGED"})).status_code == 403
    assert (await session.get(Location, foreign_cell)).title == ""
    own_update = await api.patch(f"/wms/locations/{own_cell}", json={"organization_id": own, "title": "Own cell"})
    assert own_update.status_code == 200, own_update.text


@pytest.mark.parametrize("changes", [
    {"organization_id": None}, {"organization_id": True}, {"organization_id": "1"},
    {"warehouse": ""}, {"warehouse": "   "}, {"warehouse": "Unregistered"},
])
async def test_creation_requires_explicit_registered_scope(api, locations, changes):
    body = {"organization_id": locations[0][0], "warehouse": "Shared", "code": "NEW", **changes}
    assert (await api.post("/wms/locations", json=body)).status_code == 422


async def test_missing_scope_cannot_use_main_warehouse_default(api, locations):
    assert (await api.post("/wms/locations", json={"code": "NEW"})).status_code == 422
    assert (await api.patch(f"/wms/locations/{locations[0][1]}", json={"title": "NEW"})).status_code == 422


async def test_multiple_owned_warehouses_work_without_enabling_physical_writes(api, session, locations):
    org = locations[0][0]
    warehouse = await api.post(f"/wms/organizations/{org}/warehouses", json={"name": "Second", "title": "Second"})
    assert warehouse.status_code == 201
    cell = await api.post("/wms/locations", json={"organization_id": org, "warehouse": "Second", "code": "CELL"})
    assert cell.status_code == 201, cell.text
    rows = (await api.get("/wms/locations", params={"warehouse": "Second"})).json()
    assert [r["id"] for r in rows] == [cell.json()["id"]]
    row = await session.get(WarehouseDirectory, warehouse.json()["id"])
    assert row.wms_enabled is False and row.prohibit_negative_stock is True
    assert await session.scalar(select(StockMovement.id)) is None


async def test_unowned_legacy_cells_are_preserved_without_name_based_assignment(api, session, locations):
    legacy = Location(warehouse="Shared", code="LEGACY", title="Keep provenance unknown")
    session.add(legacy)
    await session.commit()
    ident = legacy.id
    assert ident not in [r["id"] for r in (await api.get("/wms/locations")).json()]
    assert (await api.get(f"/wms/locations/{ident}")).status_code == 404
    assert (await api.patch(f"/wms/locations/{ident}", json={"organization_id": locations[0][0], "title": "Claim"})).status_code == 404
    row = await session.get(Location, ident)
    assert row.organization_id is None and row.title == "Keep provenance unknown"


async def test_movement_and_production_gateway_reject_foreign_same_name_cells(api, session, locations):
    (own, own_cell, _), (_, foreign_cell, _) = locations
    assert (await validate_location_ids(session, own, "Shared", own_cell))[0].id == own_cell
    for ident in [foreign_cell, 999999]:
        with pytest.raises(HTTPException) as denied:
            await validate_location_ids(session, own, "Shared", ident)
        assert denied.value.status_code == 422
    gateway = WmsReservationService()
    for invalid in [None, True, 0]:
        with pytest.raises(HTTPException):
            await gateway.receiving_places(session, invalid, "LEGACY")
    places = await gateway.receiving_places(session, own, "CELL")
    assert [p["location_id"] for p in places] == [own_cell]
    assert (await gateway.receiving_place(session, own, "Shared", own_cell))["location_id"] == own_cell
    assert (await session.get(Location, own_cell)).organization_id == own
    with pytest.raises(HTTPException):
        await gateway.receiving_place(session, own, "Shared", foreign_cell)
    # A real route must reject the reference before any physical movement.
    response = await api.post("/wms/transfer", json={"organization_id": own, "sku_code": "A", "qty": "1.00", "warehouse": "Shared", "from_location_id": own_cell, "to_location_id": foreign_cell})
    assert response.status_code == 422, response.text
    assert await session.scalar(select(StockMovement.id)) is None


async def test_inactive_cells_and_warehouses_cannot_be_used(api, session, locations):
    org, ident, warehouse_id = locations[0]
    assert (await api.patch(f"/wms/locations/{ident}", json={"organization_id": org, "is_active": False})).status_code == 200
    with pytest.raises(HTTPException):
        await validate_location_ids(session, org, "Shared", ident)
    warehouse = await session.get(WarehouseDirectory, warehouse_id)
    warehouse.is_active = False
    await session.commit()
    assert (await api.post("/wms/locations", json={"organization_id": org, "warehouse": "Shared", "code": "NEW"})).status_code == 422


async def test_balances_do_not_disclose_foreign_location_metadata(api, session, locations):
    own, _, _ = locations[0]
    foreign_cell = locations[1][1]
    # Historical corruption must not leak the foreign cell's display code.
    session.add(StockMovement(organization_id=own, sku_code="A", warehouse="Shared", kind="in", qty=Decimal("1"), location_id=foreign_cell))
    await session.commit()
    response = await api.get("/wms/balances")
    assert response.status_code == 200, response.text
    assert response.json()["rows"][0]["location_code"] == ""
