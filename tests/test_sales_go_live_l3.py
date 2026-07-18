"""Go-live L3: доска сделок для менеджера (RBAC, стадии, SKU picker)."""
from __future__ import annotations

import pytest

SALES_HEADERS = {"X-User-Roles": "sales"}
GUEST_HEADERS = {"X-User-Roles": "guest"}
SALES_HEAD_HEADERS = {"X-User-Roles": "sales_head"}


def test_sales_role_rbac_contract():
    """Роль sales: deal.read+write; approve — только sales_head (РОП)."""
    from core.runtime.app import create_app
    from core.services.auth import CurrentUser, has_permission

    core = create_app().state.core
    sales = CurrentUser("makarov", ["sales"])
    rop = CurrentUser("ryazanov", ["sales_head"])
    guest = CurrentUser("guest", ["guest"])

    assert has_permission(core, sales, "sales.deal.read")
    assert has_permission(core, sales, "sales.deal.write")
    assert not has_permission(core, sales, "sales.deal.approve")

    assert has_permission(core, rop, "sales.deal.approve")
    assert not has_permission(core, guest, "sales.deal.read")


@pytest.mark.asyncio
async def test_board_sales_manager_200(api):
    """GET /sales/board под ролью sales → 200 и структура воронки."""
    r = await api.get("/sales/board", headers=SALES_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert "stages" in data
    assert isinstance(data["stages"], list)
    assert len(data["stages"]) >= 1


@pytest.mark.asyncio
async def test_board_guest_403(api):
    """Без права sales.deal.read доска fail-closed → 403, не пустой 200."""
    r = await api.get("/sales/board", headers=GUEST_HEADERS)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_stage_change_sales_manager(api):
    """Менеджер (sales) может сменить стадию сделки."""
    created = (
        await api.post(
            "/sales/deals",
            json={"number": "GL3-1", "title": "Go-live", "counterparty": "ООО Тест", "stage": "new"},
            headers=SALES_HEADERS,
        )
    ).json()
    r = await api.patch(
        f"/sales/deals/{created['id']}",
        json={"stage": "qual"},
        headers=SALES_HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["stage"] == "qual"


@pytest.mark.asyncio
async def test_skus_picker_empty_mdm(api):
    """Пустой MDM: for_picker=1 → 200 и [], без падения и без «всегда demo»."""
    r = await api.get("/sales/skus", params={"for_picker": "1"}, headers=SALES_HEADERS)
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_skus_picker_excludes_demo_seed(session, api):
    """Реальные SKU из MDM остаются; seed «(демо)»/«(тест)» отфильтрованы в picker."""
    from core.domain.models import Sku

    session.add(Sku(code="DEMO-GL3", title="Щелочная (демо)", unit="шт"))
    session.add(Sku(code="REAL-GL3", title="Батарейка RADIAN AA", unit="шт"))
    await session.commit()

    picker = (
        await api.get("/sales/skus", params={"for_picker": "1"}, headers=SALES_HEADERS)
    ).json()
    codes = {s["code"] for s in picker}
    assert "REAL-GL3" in codes
    assert "DEMO-GL3" not in codes


@pytest.mark.asyncio
async def test_sales_manager_cannot_approve_document(api):
    """sales без sales.deal.approve → 403 на decide; sales_head → 200."""
    deal = (
        await api.post(
            "/sales/deals",
            json={"number": "AP-GL3", "title": "t", "counterparty": "c", "amount": 100},
            headers=SALES_HEADERS,
        )
    ).json()
    doc = (
        await api.post(
            f"/sales/deals/{deal['id']}/documents",
            json={"kind": "contract", "requested_by": "Менеджер"},
            headers=SALES_HEADERS,
        )
    ).json()
    assert doc["status"] == "pending_approval"
    denied = await api.post(
        f"/sales/documents/{doc['id']}/decide",
        json={"approved": True, "by": "Менеджер"},
        headers=SALES_HEADERS,
    )
    assert denied.status_code == 403

    ok = await api.post(
        f"/sales/documents/{doc['id']}/decide",
        json={"approved": True, "by": "РОП"},
        headers=SALES_HEAD_HEADERS,
    )
    assert ok.status_code == 200
