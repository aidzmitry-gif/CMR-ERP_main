"""Supplier metrics must not combine company books or unattributed claims."""
from datetime import datetime, timezone, date
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio

from core.services.auth import CurrentUser, get_current_user
from modules.accounting.models import AccessGrant, Organization
from modules.procurement import routes, scoped_reads
from modules.procurement.models import PurchaseOrder, PurchaseRequest, Rfq, RfqBid, SupplierClaim
from modules.procurement.ownership import PurchaseOwnership

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def scorecard_case(client, db, book):
    connection = await db.connection()
    await connection.run_sync(lambda c: Rfq.__table__.create(c))
    await connection.run_sync(lambda c: RfqBid.__table__.create(c))
    await connection.run_sync(lambda c: SupplierClaim.__table__.create(c))
    await db.commit()
    client.test_app.include_router(routes.router, prefix="/procurement")
    client.test_app.include_router(scoped_reads.router, prefix="/procurement")
    other = Organization(name="Other scorecard company", unp="888888888")
    db.add(other)
    await db.flush()
    db.add(AccessGrant(organization_id=other.id, subject="tester", role="chief"))
    await db.commit()
    now = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
    for org, eta in ((book[0], date(2026, 9, 24)), (other.id, date(2026, 9, 23))):
        order = PurchaseOrder(supplier_id=1, supplier="supplier1", status="received",
                              received_at=now, eta_date=eta)
        request = PurchaseRequest(item="Battery", supplier="supplier1", supplier_id=1, qty=1)
        db.add_all([order, request])
        await db.flush()
        db.add_all([
            PurchaseOwnership(organization_id=org, kind="order", source_id=order.id,
                              snapshot={}, evidence="Checked", actor="tester"),
            PurchaseOwnership(organization_id=org, kind="request", source_id=request.id,
                              snapshot={}, evidence="Checked", actor="tester"),
        ])
        rfq = Rfq(request_id=request.id, request_key=str(uuid4()), item="Battery", qty=1,
                  status="awarded")
        db.add(rfq)
        await db.flush()
        db.add(RfqBid(rfq_id=rfq.id, supplier_id=1, price_byn=Decimal("100.00") if org == book[0]
                      else Decimal("900.00"), is_winner=True))
    db.add(PurchaseOrder(supplier_id=1, supplier="supplier1", status="received",
                         received_at=now, eta_date=date(2026, 9, 24)))  # unowned history
    db.add(SupplierClaim(supplier_id=1, supplier="supplier1", status="open", reason="unattributed"))
    await db.commit()
    return book[0], other.id


async def test_company_scorecards_exclude_other_and_unowned_history(client, scorecard_case):
    org, other = scorecard_case
    assert (await client.get("/procurement/suppliers/1/scorecard")).status_code == 410
    one = await client.get(f"/procurement/organizations/{org}/suppliers/1/scorecard")
    two = await client.get(f"/procurement/organizations/{other}/suppliers/1/scorecard")
    assert one.status_code == 200 and two.status_code == 200
    first, second = one.json(), two.json()
    assert first["organization_id"] == org and second["organization_id"] == other
    assert first["orders_count"] == second["orders_count"] == 1
    assert first["on_time_rate"] == 1.0 and second["on_time_rate"] == 0.0
    assert first["avg_won_price_byn"] == "100.00"
    assert second["avg_won_price_byn"] == "900.00"
    for result in (first, second):
        assert result["claims_total"] is None and result["score"] is None
        assert result["status"] == "provisional_claims_unattributed"


async def test_reader_has_only_own_company_scorecard(client, scorecard_case, db):
    org, other = scorecard_case
    db.add(AccessGrant(organization_id=org, subject="reader", role="reader"))
    await db.commit()
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("reader", ["director"])
    assert (await client.get(f"/procurement/organizations/{org}/suppliers/1/scorecard")).status_code == 200
    assert (await client.get(f"/procurement/organizations/{other}/suppliers/1/scorecard")).status_code == 403
