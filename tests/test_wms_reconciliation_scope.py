"""Reconciliation isolation; these are not positive 1C valuation acceptance tests."""
from decimal import Decimal

import pytest
from sqlalchemy import select

from core.domain.models import Sku
from modules.integrations.models import StockItem
from modules.integrations.stock import StockService
from modules.wms.models import StockMovement, WarehouseDirectory
from tests.test_wms_organization import _prepare_warehouse, book


async def prepared(api, session):
    organization = await book(api)
    await _prepare_warehouse(api, organization, "Shared")
    api.headers["X-User"] = "foreign-reconciliation-owner"
    response = await api.post("/accounting/organizations", json={"name": "Synthetic foreign company", "unp": "999999992"})
    assert response.status_code == 201, response.text
    foreign = response.json()["id"]
    await _prepare_warehouse(api, foreign, "Shared")
    api.headers["X-User"] = "wms-owner-test"
    session.add(Sku(code="RECON-SCOPE", title="Synthetic stock"))
    session.add(StockItem(sku_code="RECON-SCOPE", warehouse="Shared", qty_available=Decimal("20"), cost=Decimal("500")))
    for owner, kind, quantity in [(organization, "in", "3"), (organization, "out", "2"), (foreign, "in", "7"), (None, "in", "33")]:
        session.add(StockMovement(organization_id=owner, sku_code="RECON-SCOPE", warehouse="Shared", kind=kind, qty=Decimal(quantity)))
    await session.commit()
    return organization, foreign


async def test_reconciliation_excludes_foreign_and_unowned_rows_and_never_reads_global_mirror(api, session, monkeypatch):
    organization, _ = await prepared(api, session)
    calls = []

    async def forbidden(*args):
        calls.append(args)
        raise AssertionError("Unqualified global mirror must never be read")

    monkeypatch.setattr(StockService, "stock_by_sku", forbidden)
    before = (await session.execute(select(StockMovement.__table__))).all()
    mirror_before = (await session.execute(select(StockItem.__table__))).all()
    response = await api.get("/wms/reconciliation", params={"organization_id": organization})
    assert response.status_code == 200, response.text
    assert response.json() == {
        "organization_id": organization,
        "rows": [{"sku_code": "RECON-SCOPE", "title": "Synthetic stock", "warehouse": "Shared", "wms_qty": 1.0,
                  "onec_qty": None, "diff": None, "diff_value": None}],
        "gateway": False, "total_abs_diff_value": None,
        "source_unavailable_reason": "organization_stock_source_unverified",
    }
    assert calls == []
    assert (await session.execute(select(StockMovement.__table__))).all() == before
    assert (await session.execute(select(StockItem.__table__))).all() == mirror_before
    warehouse = await session.scalar(select(WarehouseDirectory).where(WarehouseDirectory.organization_id == organization))
    assert warehouse.wms_enabled is False and warehouse.prohibit_negative_stock is True


async def test_reconciliation_requires_explicit_organization(api):
    await book(api)
    assert (await api.get("/wms/reconciliation")).status_code == 422


async def test_reconciliation_rejects_foreign_organization(api, session):
    _, foreign = await prepared(api, session)
    response = await api.get("/wms/reconciliation", params={"organization_id": foreign})
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("warehouse", ["unknown", "inactive"])
async def test_reconciliation_rejects_unconfirmed_warehouse(api, session, warehouse):
    organization = await book(api)
    if warehouse == "inactive":
        await _prepare_warehouse(api, organization, warehouse)
        row = await session.scalar(select(WarehouseDirectory).where(WarehouseDirectory.organization_id == organization))
        row.is_active = False
        await session.commit()
    response = await api.get("/wms/reconciliation", params={"organization_id": organization, "warehouse": warehouse})
    assert response.status_code == 409, response.text


async def test_reconciliation_overview_does_not_silently_drop_inactive_warehouse(api, session):
    organization, _ = await prepared(api, session)
    row = await session.scalar(select(WarehouseDirectory).where(WarehouseDirectory.organization_id == organization))
    row.is_active = False
    await session.commit()
    response = await api.get("/wms/reconciliation", params={"organization_id": organization})
    assert response.status_code == 409, response.text


async def test_reconciliation_missing_gateway_preserves_own_journal_and_unknown_values(api, session, monkeypatch):
    organization, _ = await prepared(api, session)
    monkeypatch.setattr(api._transport.app.state.core.services, "stock", None)
    response = await api.get("/wms/reconciliation", params={"organization_id": organization, "warehouse": "Shared"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["rows"][0]["wms_qty"] == 1
    assert data["rows"][0]["onec_qty"] is None and data["rows"][0]["diff"] is None
    assert data["total_abs_diff_value"] is None and data["gateway"] is False
    assert data["source_unavailable_reason"] == "stock_gateway_unavailable"


async def test_reconciliation_empty_company_is_not_a_zero_valuation(api):
    organization = await book(api)
    response = await api.get("/wms/reconciliation", params={"organization_id": organization})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["rows"] == [] and data["total_abs_diff_value"] is None
    assert data["gateway"] is False and data["source_unavailable_reason"] == "organization_stock_source_unverified"
