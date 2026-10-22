from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from modules.wms.invoice_shipments import create, preview
from modules.wms.models import StockMovement
from modules.wms.stock_policy import check, shortage
from tests.test_warehouse_execution_mode import prepared


@pytest.mark.parametrize("wms", [False, True])
@pytest.mark.parametrize("prohibit", [True, False])
async def test_zero_stock_policy_both_modes_and_replay(api, session, wms, prohibit):
    org, facts, actor, warehouse, basis, command = await prepared(api, session, wms)
    warehouse.prohibit_negative_stock = prohibit
    session.add(
        StockMovement(
            organization_id=org,
            sku_code="A",
            warehouse="W",
            kind="out",
            qty="10",
            reason="shipment",
        )
    )
    await session.flush()
    basis = await preview(session, org, facts)
    command = command.model_copy(update={"expected_physical_digest": basis["physical_digest"]})
    before = await session.scalar(select(func.count()).select_from(StockMovement))
    if prohibit:
        assert basis["lines"][0]["blocking_reason"] == "stock_shortage"
        with pytest.raises(HTTPException) as caught:
            await create(
                session, org, facts, command, actor, execution_mode="wms" if wms else "document"
            )
        detail = caught.value.detail
        assert (
            detail["code"] == "stock_shortage"
            and detail["sku_code"] == "A"
            and detail["warehouse"] == "W"
        )
        assert (
            detail["physical"] == "0.00"
            and detail["requested"] == "1.00"
            and detail["shortage"] == "1.00"
        )
        assert await session.scalar(select(func.count()).select_from(StockMovement)) == before
    else:
        assert basis["lines"][0]["blocking_reason"] is None
        result = await create(
            session, org, facts, command, actor, execution_mode="wms" if wms else "document"
        )
        warehouse.prohibit_negative_stock = True
        await session.flush()
        assert (
            await create(
                session, org, facts, command, actor, execution_mode="wms" if wms else "document"
            )
            == result
        )
        assert await session.scalar(select(func.count()).select_from(StockMovement)) == before + 1
        stock = await preview(session, org, facts)
        assert stock["lines"][0]["physical"] == "-1.00"


@pytest.mark.parametrize(
    "physical,other,expected",
    [
        ("0", "0", "insufficient_stock"),
        ("10", "10", "reserved_by_other_documents"),
        (None, "0", "unknown_stock"),
    ],
)
def test_shortage_reason_and_unknown_are_explicit(physical, other, expected):
    detail = shortage("SKU", "Warehouse", Decimal("1"), physical, other)
    assert detail["reason"] == expected
    if physical is None:
        assert detail["available"] is None and detail["shortage"] is None
        with pytest.raises(HTTPException):
            check("SKU", "Warehouse", 1, None, 0, False)


async def test_policy_toggle_is_scoped_audited_and_stale_rejected(api, session):
    org, _, _, warehouse, _, _ = await prepared(api, session, False)
    wid = warehouse.id
    await session.commit()
    result = await api.patch(
        f"/wms/organizations/{org}/warehouses/{wid}/stock-policy",
        json={"expected_prohibit_negative_stock": True, "prohibit_negative_stock": False},
    )
    assert result.status_code == 200, result.text
    assert result.json()["prohibit_negative_stock"] is False
    stale = await api.patch(
        f"/wms/organizations/{org}/warehouses/{wid}/stock-policy",
        json={"expected_prohibit_negative_stock": True, "prohibit_negative_stock": False},
    )
    assert stale.status_code == 409
    foreign = await api.patch(
        f"/wms/organizations/{org + 999}/warehouses/{wid}/stock-policy",
        json={"expected_prohibit_negative_stock": False, "prohibit_negative_stock": True},
    )
    assert foreign.status_code in (403, 404)
    from core.domain.models import OutboxEvent

    rows = (
        await session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.event_type == "wms.warehouse.stock_policy_changed"
            )
        )
    ).all()
    assert len(rows) == 1 and rows[0].payload["prohibit_negative_stock"] is False


async def test_policy_toggle_denied_to_ordinary_accountant(api, session):
    org, _, _, warehouse, _, _ = await prepared(api, session, False)
    wid = warehouse.id
    await session.commit()
    result = await api.patch(
        f"/wms/organizations/{org}/warehouses/{wid}/stock-policy",
        headers={"X-User-Roles": "accountant"},
        json={"expected_prohibit_negative_stock": True, "prohibit_negative_stock": False},
    )
    assert result.status_code == 403


@pytest.mark.parametrize("prohibit", [True, False])
async def test_reservation_from_known_zero_respects_policy(api, session, prohibit):
    from modules.wms.invoice_reservations import reserve
    from modules.wms.models import WarehouseDirectory
    from tests.test_invoice_stock_allocation import setup

    org, facts, data, actor = await setup(api, session, create_warehouse=False)
    session.add(
        WarehouseDirectory(
            organization_id=org,
            name="W",
            title="Warehouse",
            created_by=actor,
            prohibit_negative_stock=prohibit,
        )
    )
    session.add(
        StockMovement(
            organization_id=org,
            sku_code="A",
            warehouse="W",
            kind="out",
            qty="10",
            reason="shipment",
        )
    )
    await session.flush()
    if prohibit:
        with pytest.raises(HTTPException) as caught:
            await reserve(session, org, facts, data, actor)
        assert (
            caught.value.detail["physical"] == "0.00" and caught.value.detail["requested"] == "5.00"
        )
    else:
        result = await reserve(session, org, facts, data, actor)
        assert result["snapshot"]["physical_basis"]["W"]["cutoff"] > 0


async def test_empty_journal_is_structured_unknown_not_zero(api, session):
    from sqlalchemy import delete

    from modules.wms.invoice_reservations import reserve
    from tests.test_invoice_stock_allocation import setup

    org, facts, data, actor = await setup(api, session, create_warehouse=False)
    from modules.wms.models import WarehouseDirectory

    session.add(
        WarehouseDirectory(organization_id=org, name="W", title="Warehouse", created_by=actor)
    )
    await session.flush()
    await session.execute(delete(StockMovement).where(StockMovement.organization_id == org))
    with pytest.raises(HTTPException) as caught:
        await reserve(session, org, facts, data, actor)
    assert caught.value.detail["reason"] == "unknown_stock"
    assert caught.value.detail["sku_code"] == "A" and caught.value.detail["warehouse"] == "W"
    assert caught.value.detail["physical"] is None


def test_negative_exception_does_not_spend_other_document_reserve():
    with pytest.raises(HTTPException) as caught:
        check("SKU", "Warehouse", 1, 10, 10, False)
    assert caught.value.detail["reason"] == "reserved_by_other_documents"


async def test_preview_aggregates_same_sku_lines(api, session):
    org, facts, actor, warehouse, basis, command = await prepared(api, session, False)
    session.add(
        StockMovement(
            organization_id=org, sku_code="A", warehouse="W", kind="out", qty="6", reason="shipment"
        )
    )
    await session.flush()
    basis = await preview(session, org, facts)
    assert len(basis["lines"]) == 2
    assert all(x["blocking_reason"] == "stock_shortage" for x in basis["lines"])
    assert all(x["stock_issue"]["requested"] == "5.00" for x in basis["lines"])


async def test_negative_ledger_can_be_reconciled_by_inventory(api, session):
    from tests.test_inventory_organization import CONFIRM

    org, _, _, _, _, _ = await prepared(api, session, False)
    session.add(
        StockMovement(
            organization_id=org,
            sku_code="A",
            warehouse="W",
            kind="out",
            qty="11",
            reason="shipment",
        )
    )
    await session.commit()
    response = await api.post(
        "/wms/inventory", json={**CONFIRM, "organization_id": org, "warehouse": "W"}
    )
    assert response.status_code == 201, response.text
    cid = response.json()["id"]
    populated = await api.post(f"/wms/inventory/{cid}/populate")
    assert populated.status_code == 200, populated.text
    line = populated.json()["lines"][0]
    assert line["expected_qty"] == -1
    counted = await api.patch(f"/wms/inventory/lines/{line['id']}", json={"counted_qty": 0})
    assert counted.status_code == 200, counted.text
    completed = await api.post(f"/wms/inventory/{cid}/complete")
    assert completed.status_code == 200, completed.text


async def test_negative_exception_is_limited_to_selected_warehouse(api, session):
    from modules.wms.invoice_shipments import guard_free
    from modules.wms.models import WarehouseDirectory
    from tests.test_invoice_stock_allocation import setup

    org, _, _, actor = await setup(api, session, create_warehouse=False)
    session.add_all(
        [
            WarehouseDirectory(
                organization_id=org,
                name="W",
                title="W",
                created_by=actor,
                prohibit_negative_stock=False,
            ),
            WarehouseDirectory(organization_id=org, name="Other", title="Other", created_by=actor),
        ]
    )
    session.add_all(
        [
            StockMovement(
                organization_id=org,
                sku_code="A",
                warehouse="Other",
                kind="in",
                qty=1,
                reason="receipt",
            ),
            StockMovement(
                organization_id=org,
                sku_code="A",
                warehouse="Other",
                kind="out",
                qty=1,
                reason="shipment",
            ),
        ]
    )
    await session.flush()
    await guard_free(session, org, {("A", "W"): Decimal("11")})
    with pytest.raises(HTTPException) as caught:
        await guard_free(session, org, {("A", "Other"): Decimal("1")})
    assert caught.value.detail["warehouse"] == "Other" and caught.value.detail["physical"] == "0.00"


async def test_completed_line_does_not_carry_other_line_shortage(api, session):
    from modules.wms.invoice_shipments import ShipmentInput

    org, facts, actor, _, _, command = await prepared(api, session, False)
    body = ShipmentInput.model_validate(
        {**command.model_dump(), "lines": [{"line_no": 1, "warehouse": "W", "qty": "2.00"}]}
    )
    await create(session, org, facts, body, actor, execution_mode="document")
    session.add(
        StockMovement(
            organization_id=org, sku_code="A", warehouse="W", kind="out", qty="8", reason="shipment"
        )
    )
    await session.flush()
    basis = await preview(session, org, facts)
    first, second = basis["lines"]
    assert first["blocking_reason"] == "fully_shipped" and first["stock_issue"] is None
    assert (
        second["blocking_reason"] == "stock_shortage"
        and second["stock_issue"]["requested"] == "3.00"
    )
