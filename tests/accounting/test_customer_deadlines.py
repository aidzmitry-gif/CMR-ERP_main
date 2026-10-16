from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from modules.procurement.expected_reservations import ExpectedReservation, ExpectedReservationEvent
from modules.procurement.models import PurchaseOrder
from modules.sales.models import Deal
from tests.accounting.test_expected_reservations import payload, setup_expected


async def test_deadlines_follow_explicit_reservations_and_keep_unknown_visible(client, db, book):
    from modules.procurement.scoped_reads import router

    client._transport.app.include_router(router, prefix="/procurement")
    order_id, line_id, deal_id = await setup_expected(db, book)
    deal = await db.get(Deal, deal_id)
    deal.ship_deadline = "2026-12-31"
    order = await db.get(PurchaseOrder, order_id)
    order.target_arrival_date = date(2026, 12, 30)
    # An unrelated deal with the same item must not supply a deadline.
    db.add(Deal(number="UNRELATED", title="Other customer", counterparty="Other",
                amount=0, ship_deadline="2026-01-01"))
    await db.commit()
    url = f"/procurement/organizations/{book[0]}/orders/{order_id}/customer-deadlines"
    empty = await client.get(url)
    assert empty.status_code == 200, empty.text
    assert empty.json()["items"] == [] and empty.json()["at_risk"] is None
    created = await client.post(f"/procurement/organizations/{book[0]}/expected-reservations",
                                json=payload(order_id, line_id, deal_id))
    assert created.status_code == 201, created.text
    result = (await client.get(url)).json()
    assert result["earliest_required_arrival"] == "2026-12-28"
    assert result["at_risk"] is True
    assert result["items"][0]["outstanding_qty"] == "60.00"
    assert result["complete_customer_demand"] is False
    deal.ship_deadline = "по согласованию"
    await db.commit()
    result = (await client.get(url)).json()
    assert result["unresolved_deadlines"] == 1 and result["at_risk"] is None
    assert result["earliest_required_arrival"] is None
    denied = await client.get(f"/procurement/organizations/{book[0]+1000}/orders/{order_id}/customer-deadlines")
    assert denied.status_code in (403, 404)

    reservation = await db.scalar(select(ExpectedReservation))
    db.add(ExpectedReservationEvent(organization_id=book[0], reservation_id=reservation.id,
        kind="release", qty=Decimal("60"), request_key=str(uuid4()),
        evidence="Customer released expected stock", actor="tester"))
    await db.commit()
    released = (await client.get(url)).json()
    assert released["items"] == [] and released["at_risk"] is None
