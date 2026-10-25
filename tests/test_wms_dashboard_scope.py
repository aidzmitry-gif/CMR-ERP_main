"""Company-scoped dashboard; unavailable valuation is never reconstructed from global stock."""
# ruff: noqa: F811 -- imported pytest fixture
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest_asyncio
from sqlalchemy import func, select

from core.domain.models import Sku, User
from modules.accounting.models import Organization
from modules.integrations.models import StockItem
from modules.wms import routes
from modules.wms.models import InventoryCount, Receipt, StockMovement, Task, WarehouseDirectory
from tests.test_erp import erp_organization  # noqa: F401


@pytest_asyncio.fixture
async def dashboard_scope(api, session, erp_organization):
    for name in ("DASH-W1", "DASH-W2"):
        response = await api.post(f"/wms/organizations/{erp_organization}/warehouses",
                                  json={"name": name, "title": "Synthetic dashboard warehouse"})
        assert response.status_code == 201, response.text
        assert response.json()["wms_enabled"] is False
        assert response.json()["prohibit_negative_stock"] is True
    foreign = Organization(name="Synthetic other dashboard company", unp="999999980")
    session.add(foreign)
    await session.flush()
    session.add(WarehouseDirectory(organization_id=foreign.id, name="DASH-W1", title="Synthetic other",
                                   created_by="other", wms_enabled=False, prohibit_negative_stock=True))
    await session.commit()
    day = (await session.execute(select(func.current_date()))).scalar_one()
    return erp_organization, foreign.id, datetime(day.year, day.month, day.day)


def movement(owner, warehouse, when, *, kind="in", sku="DASH-SKU", qty="1"):
    return StockMovement(organization_id=owner, warehouse=warehouse, sku_code=sku,
                         kind=kind, qty=Decimal(qty), created_at=when)


def assert_unknown(data):
    for key in ("alerts_count", "alerts_deficit_value", "inventory_value",
                "recon_max_diff_value", "recon_total_diff_value", "movements_today_in", "movements_today_out"):
        assert data[key] is None
    assert data["valuation_unavailable_reason"] == "organization_valuation_unavailable"
    assert data["quantity_unavailable_reason"] == "unit_snapshot_unavailable"


async def test_dashboard_own_counts_two_warehouses(api, session, dashboard_scope):
    org, foreign, start = dashboard_scope
    for owner, warehouses in ((org, ("DASH-W1", "DASH-W2")), (foreign, ("DASH-W1",)), (None, ("DASH-W1",))):
        for warehouse in warehouses:
            session.add_all([
                Receipt(organization_id=owner, warehouse=warehouse, status="pending_qc"),
                Task(organization_id=owner, warehouse=warehouse, sku_code="DASH-SKU", kind="putaway", status="open"),
                Task(organization_id=owner, warehouse=warehouse, sku_code="DASH-SKU", kind="pick", status="in_progress"),
                InventoryCount(organization_id=owner, warehouse=warehouse, status="open"),
                movement(owner, warehouse, start + timedelta(hours=1)),
            ])
    session.add_all([
        Receipt(organization_id=org, warehouse="DASH-W1", status="accepted"),
        Task(organization_id=org, warehouse="DASH-W1", sku_code="DASH-SKU", kind="putaway", status="done"),
        InventoryCount(organization_id=org, warehouse="DASH-W1", status="done"),
        movement(org, "DASH-W2", start + timedelta(hours=2), kind="out"),
    ])
    await session.commit()
    response = await api.get("/wms/dashboard", params={"organization_id": org})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["organization_id"] == org
    assert [data[k] for k in ("receipts_pending_qc", "tasks_putaway_open", "tasks_pick_open", "inventories_open")] == [2, 2, 2, 2]
    assert data["movement_rows_today_in"] == 2 and data["movement_rows_today_out"] == 1
    assert_unknown(data)
    warehouses = (await session.scalars(select(WarehouseDirectory))).all()
    assert all(not w.wms_enabled and w.prohibit_negative_stock for w in warehouses)


async def test_dashboard_empty_without_gateway(api_no_gateways):
    api_no_gateways.headers["X-User"] = "dashboard-empty-owner"
    created = await api_no_gateways.post("/accounting/organizations", json={"name": "Synthetic empty", "unp": "999999979"})
    assert created.status_code == 201, created.text
    org = created.json()["id"]
    response = await api_no_gateways.get("/wms/dashboard", params={"organization_id": org})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["gateway"] is False
    assert [data[k] for k in ("receipts_pending_qc", "tasks_putaway_open", "tasks_pick_open",
                              "inventories_open", "movement_rows_today_in", "movement_rows_today_out")] == [0] * 6
    assert_unknown(data)


async def test_dashboard_requires_explicit_scope(api, dashboard_scope):
    response = await api.get("/wms/dashboard")
    assert response.status_code == 422


async def test_dashboard_rejects_invalid_scope(api, dashboard_scope):
    for scope in ("0", "-1", "wrong", "1.5"):
        response = await api.get("/wms/dashboard", params={"organization_id": scope})
        assert response.status_code == 422, response.text


async def test_dashboard_forbidden_company(api, dashboard_scope):
    _, foreign, _ = dashboard_scope
    response = await api.get("/wms/dashboard", params={"organization_id": foreign})
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "No access to this organization's books"


async def test_dashboard_requires_warehouse_access(api, session, dashboard_scope):
    org, _, _ = dashboard_scope
    session.add(User(username="dashboard-finance", full_name="Synthetic finance actor", role="finance", status="active"))
    await session.commit()
    grant = await api.put(f"/accounting/organizations/{org}/members", json={"subject": "dashboard-finance", "role": "reader"})
    assert grant.status_code == 200, grant.text
    response = await api.get("/wms/dashboard", params={"organization_id": org},
                             headers={"X-User": "dashboard-finance", "X-User-Roles": "finance"})
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "Нет доступа к модулю: wms"


async def test_dashboard_half_open_recorded_day(api, session, dashboard_scope):
    org, _, start = dashboard_scope
    end = start + timedelta(days=1)
    session.add_all([
        movement(org, "DASH-W1", start - timedelta(microseconds=1)),
        movement(org, "DASH-W1", start),
        movement(org, "DASH-W2", end - timedelta(microseconds=1)),
        movement(org, "DASH-W1", end),
        movement(org, "DASH-W1", end + timedelta(days=1)),
        movement(org, "DASH-W1", start + timedelta(hours=2), kind="out"),
    ])
    await session.commit()
    data = (await api.get("/wms/dashboard", params={"organization_id": org})).json()
    assert data["report_date"] == start.date().isoformat()
    assert data["period_start"] == start.isoformat() and data["period_end"] == end.isoformat()
    assert data["period_basis"] == "stored_registration_date"
    assert data["movement_rows_today_in"] == 2 and data["movement_rows_today_out"] == 1


async def test_dashboard_never_reads_global_valuation(api, session, dashboard_scope, monkeypatch):
    org, _, _ = dashboard_scope
    session.add_all([
        Sku(code="GLOBAL-MIRROR", title="Synthetic unqualified mirror", unit="шт"),
        StockItem(sku_code="GLOBAL-MIRROR", warehouse="DASH-W1", qty_available=Decimal("100"),
                  qty_reserved=Decimal("10"), cost=Decimal("230")),
    ])
    await session.commit()
    unsafe = [AsyncMock(side_effect=AssertionError("Global source must not be read")) for _ in range(3)]
    for name, spy in zip(("_valued_rows", "_deficit_rows", "reconciliation"), unsafe):
        monkeypatch.setattr(routes, name, spy)
    response = await api.get("/wms/dashboard", params={"organization_id": org})
    assert response.status_code == 200, response.text
    assert_unknown(response.json())
    for spy in unsafe:
        spy.assert_not_awaited()


async def test_dashboard_quantity_requires_historical_unit_snapshot(api, session, dashboard_scope):
    org, _, start = dashboard_scope
    piece = Sku(code="DASH-PIECE", title="Synthetic pieces", unit="шт")
    session.add_all([piece, Sku(code="DASH-MASS", title="Synthetic mass", unit="кг"),
                     movement(org, "DASH-W1", start, sku="DASH-PIECE", qty="100"),
                     movement(org, "DASH-W2", start, sku="DASH-MASS", qty="1.5")])
    await session.commit()
    piece.unit = "л"
    await session.commit()
    data = (await api.get("/wms/dashboard", params={"organization_id": org})).json()
    assert data["movement_rows_today_in"] == 2
    assert data["movements_today_in"] is None and data["movements_today_out"] is None
    assert data["quantity_unavailable_reason"] == "unit_snapshot_unavailable"
