from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import func, select, update

from core.domain.models import Sku
from modules.procurement import events as procurement_events
from modules.procurement.deal_demands import DealProcurementAllocation, DealProcurementDemand
from modules.procurement.expected_reservations import ExpectedReservation, ExpectedReservationEvent
from modules.procurement.models import PurchaseOrder, PurchaseOrderLine
from modules.procurement.ownership import PurchaseOwnership
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.models import Deal, DealItem


async def setup_demand(db, book, *, number="DEMAND-1", item_qty="10.00", order_qty="12.00"):
    sku = await db.scalar(select(Sku).where(Sku.code == "SKU-DEMAND"))
    if sku is None:
        sku = Sku(code="SKU-DEMAND", title="Demand SKU", unit="шт", is_active=True)
    deal = Deal(number=number, title="Demand deal", counterparty="Buyer", amount=0, stage="invoice")
    db.add(deal)
    if sku.id is None:
        db.add(sku)
    await db.flush()
    item = DealItem(deal_id=deal.id, sku_id=sku.id, qty=Decimal(item_qty))
    order = PurchaseOrder(number=f"PO-{number}", supplier="Supplier", status="ordered")
    db.add(order)
    await db.flush()
    line = PurchaseOrderLine(order_id=order.id, sku_code=sku.code, qty=Decimal(order_qty))
    db.add(line)
    await db.flush()
    db.add_all([
        DealOwnership(deal_id=deal.id, organization_id=book[0], snapshot={}, evidence="Deal", actor="tester"),
        PurchaseOwnership(organization_id=book[0], kind="order", source_id=order.id,
                          snapshot={}, evidence="Order", actor="tester"),
        item,
    ])
    await db.commit()
    return deal.id, item.id, order.id, line.id, sku.id


def demand_payload(item_id, qty="6.00", document_id=None):
    return {
        "deal_item_id": item_id,
        "qty": qty,
        "document_id": document_id,
        "request_key": str(uuid4()),
        "evidence": "Client order without warehouse stock",
    }


async def test_demand_is_created_before_supplier_order_and_replayed(client, db, book):
    deal_id, item_id, _order_id, _line_id, _sku_id = await setup_demand(db, book)
    body = demand_payload(item_id, "6.00")
    response = await client.post(f"/procurement/organizations/{book[0]}/deals/{deal_id}/demands", json=body)
    assert response.status_code == 201, response.text
    assert response.json()["qty"] == "6.00"
    assert response.json()["ordered_qty"] == "0.00"
    repeated = await client.post(f"/procurement/organizations/{book[0]}/deals/{deal_id}/demands", json=body)
    assert repeated.status_code == 201 and repeated.json()["replayed"] is True
    listed = await client.get(f"/procurement/organizations/{book[0]}/deals/{deal_id}/demands")
    assert listed.status_code == 200
    assert listed.json()["demands"][0]["free_qty"] == "6.00"
    over = await client.post(
        f"/procurement/organizations/{book[0]}/deals/{deal_id}/demands",
        json=demand_payload(item_id, "4.01"),
    )
    assert over.status_code == 409
    assert await db.scalar(select(func.count()).select_from(DealProcurementDemand)) == 1


async def test_demand_allocation_shows_client_and_free_supplier_line_quantity(client, db, book):
    deal_id, item_id, order_id, line_id, _sku_id = await setup_demand(db, book, number="DEMAND-2", order_qty="12.00")
    created = await client.post(
        f"/procurement/organizations/{book[0]}/deals/{deal_id}/demands",
        json=demand_payload(item_id, "6.00"),
    )
    assert created.status_code == 201, created.text
    demand_id = created.json()["id"]
    allocation = {
        "order_id": order_id,
        "order_line_id": line_id,
        "qty": "4.00",
        "request_key": str(uuid4()),
        "evidence": "Placed on supplier order",
    }
    linked = await client.post(
        f"/procurement/organizations/{book[0]}/demands/{demand_id}/allocations",
        json=allocation,
    )
    assert linked.status_code == 201, linked.text
    receipt = linked.json()
    assert receipt["ordered_qty"] == "4.00"
    assert receipt["free_qty"] == "2.00"
    assert receipt["allocation_request_key"] == allocation["request_key"]
    assert receipt["allocation"]["id"] > 0
    assert receipt["allocation"]["demand_id"] == demand_id
    assert receipt["allocation"]["order_id"] == order_id
    assert receipt["allocation"]["order_line_id"] == line_id
    assert receipt["allocation"]["sku_code"] == "SKU-DEMAND"
    assert receipt["allocation"]["qty"] == "4.00"
    assert await db.scalar(select(func.count()).select_from(ExpectedReservation)) == 1
    expected = await client.get(f"/procurement/organizations/{book[0]}/expected-reservations/order/{order_id}")
    assert expected.status_code == 200
    assert expected.json()["lines"][0]["expected_reserved"] == "4.00"
    assert expected.json()["lines"][0]["free_expected"] == "8.00"
    replay = await client.post(
        f"/procurement/organizations/{book[0]}/demands/{demand_id}/allocations",
        json=allocation,
    )
    assert replay.status_code == 201 and replay.json()["replayed"] is True
    line_view = await client.get(f"/procurement/organizations/{book[0]}/orders/{order_id}/deal-demands")
    assert line_view.status_code == 200
    assert line_view.json()["lines"][0]["ordered"] == "12.00"
    assert line_view.json()["lines"][0]["client_ordered"] == "4.00"
    assert line_view.json()["lines"][0]["free_for_client"] == "8.00"
    assert line_view.json()["lines"][0]["candidates"][0]["demand_id"] == demand_id
    assert line_view.json()["lines"][0]["candidates"][0]["free_qty"] == "2.00"
    too_much = await client.post(
        f"/procurement/organizations/{book[0]}/demands/{demand_id}/allocations",
        json={**allocation, "qty": "2.01", "request_key": str(uuid4())},
    )
    assert too_much.status_code == 409
    reservation_id = expected.json()["lines"][0]["reservations"][0]["id"]
    released = await client.post(
        f"/procurement/organizations/{book[0]}/expected-reservations/{reservation_id}/events",
        json={"kind": "release", "qty": "1.00", "request_key": str(uuid4()), "evidence": "Customer cancelled"},
    )
    assert released.status_code == 201
    demand_view = await client.get(f"/procurement/organizations/{book[0]}/deals/{deal_id}/demands")
    assert demand_view.json()["demands"][0]["ordered_qty"] == "3.00"
    assert demand_view.json()["demands"][0]["free_qty"] == "3.00"
    line_view = await client.get(f"/procurement/organizations/{book[0]}/orders/{order_id}/deal-demands")
    assert line_view.json()["lines"][0]["client_ordered"] == "3.00"
    assert line_view.json()["lines"][0]["free_for_client"] == "9.00"
    assert await db.scalar(select(func.count()).select_from(DealProcurementAllocation)) == 1


async def test_two_client_demands_share_one_supplier_line_without_overallocation(client, db, book):
    first = await setup_demand(db, book, number="DEMAND-3", item_qty="8.00", order_qty="10.00")
    second = await setup_demand(db, book, number="DEMAND-4", item_qty="8.00", order_qty="10.00")
    # The helper deliberately uses the same SKU code for both deals; create a second order line
    # only for the second fixture, then allocate both demands to the first line below.
    deal_a, item_a, order_id, line_id, _ = first
    deal_b, item_b, _order_b, _line_b, _ = second
    a = await client.post(
        f"/procurement/organizations/{book[0]}/deals/{deal_a}/demands",
        json=demand_payload(item_a, "6.00"),
    )
    b = await client.post(
        f"/procurement/organizations/{book[0]}/deals/{deal_b}/demands",
        json=demand_payload(item_b, "6.00"),
    )
    assert a.status_code == b.status_code == 201
    for demand_id, qty in ((a.json()["id"], "6.00"), (b.json()["id"], "4.00")):
        result = await client.post(
            f"/procurement/organizations/{book[0]}/demands/{demand_id}/allocations",
            json={
                "order_id": order_id,
                "order_line_id": line_id,
                "qty": qty,
                "request_key": str(uuid4()),
                "evidence": "Shared supplier line",
            },
        )
        assert result.status_code == 201, result.text
    blocked = await client.post(
        f"/procurement/organizations/{book[0]}/demands/{a.json()['id']}/allocations",
        json={
            "order_id": order_id,
            "order_line_id": line_id,
            "qty": "0.01",
            "request_key": str(uuid4()),
            "evidence": "Should exceed line",
        },
    )
    assert blocked.status_code == 409
    line_view = await client.get(f"/procurement/organizations/{book[0]}/orders/{order_id}/deal-demands")
    assert line_view.json()["lines"][0]["client_ordered"] == "10.00"
    assert line_view.json()["lines"][0]["free_for_client"] == "0.00"


async def test_finalized_lost_deal_releases_expected_reserve_idempotently(client, db, book):
    deal_id, item_id, order_id, _line_id, _sku_id = await setup_demand(
        db, book, number="DEMAND-LOSS", order_qty="10.00"
    )
    created = await client.post(
        f"/procurement/organizations/{book[0]}/deals/{deal_id}/demands",
        json=demand_payload(item_id, "6.00"),
    )
    demand_id = created.json()["id"]
    allocated = await client.post(
        f"/procurement/organizations/{book[0]}/demands/{demand_id}/allocations",
        json={
            "order_id": order_id,
            "order_line_id": _line_id,
            "qty": "4.00",
            "request_key": str(uuid4()),
            "evidence": "Loss release",
        },
    )
    assert allocated.status_code == 201
    payload = {"organization_id": book[0], "deal_id": deal_id, "resolution_id": str(uuid4()), "by": "tester"}
    ctx = SimpleNamespace(session=db)
    await procurement_events.on_deal_loss_finalized(payload, ctx)
    await db.commit()
    await procurement_events.on_deal_loss_finalized(payload, ctx)
    await db.commit()
    demand_view = await client.get(f"/procurement/organizations/{book[0]}/deals/{deal_id}/demands")
    assert demand_view.json()["demands"][0]["ordered_qty"] == "0.00"
    assert demand_view.json()["demands"][0]["free_qty"] == "6.00"
    assert await db.scalar(select(func.count()).select_from(ExpectedReservationEvent)) == 1
    await db.execute(update(Deal).where(Deal.id == deal_id).values(stage="lost"))
    await db.commit()
    blocked = await client.post(
        f"/procurement/organizations/{book[0]}/demands/{demand_id}/allocations",
        json={
            "order_id": order_id,
            "order_line_id": _line_id,
            "qty": "1.00",
            "request_key": str(uuid4()),
            "evidence": "Lost deal must stay closed",
        },
    )
    assert blocked.status_code == 409
