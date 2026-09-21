import pytest
from sqlalchemy import func, select

from core.domain.models import OutboxEvent, User
from modules.accounting.models import Policy
from modules.logistics.models import CarrierBid, CarrierRfqInvite
from modules.sales.invoice_cancellation import InvoiceCancellationReceipt
from modules.sales.models import DealDocument
from modules.sales.reservation_source import SalesReservationSource
from modules.wms.invoice_reservations import InvoiceReservationRelease
from modules.wms.invoice_shipments import PhysicalShipmentAct
from modules.wms.models import ReservationVersion
from tests.accounting.test_invoice_settlements import bank
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401
from tests.test_invoice_cancellation import cancel_request
from tests.test_invoice_issuance import erp_money_flow

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_pg_paid_invoice_cancellation_requires_full_refund_then_releases_once(issuance_pg):  # noqa: F811
    api, factory = issuance_pg
    async with factory() as session:
        connection = await session.connection()
        for model in (CarrierBid, CarrierRfqInvite, User):
            await connection.run_sync(lambda c, model=model: model.__table__.create(c, checkfirst=True))
        await session.commit()
        await erp_money_flow(api, session)
        policy = await session.scalar(select(Policy))
        document = await session.get(DealDocument, 1)
        document.status = "paid"
        await session.commit()
        facts = await SalesReservationSource().invoice_reservation(session, 1)
        await session.commit()

    org = policy.organization_id
    prefix = f"/sales/organizations/{org}/invoices/1"

    # The evidence can be prepared only while every received payment has been
    # returned.  A later payment must invalidate that already-confirmed packet;
    # the cancel endpoint must not use it to release the reserve.
    stale_cancel_path, stale_cancel_body = await cancel_request(api, org, facts)

    late_entry = await bank(api, (org, policy.id), 1, "trace-late-payment", amount="20.00")
    late_allocation = await api.post(prefix + "/settlements", json={
        "bank_entry_id": late_entry,
        "source_key": "trace-late-payment",
        "amount": "20.00",
        "evidence": "CRM-ACC-001 late receipt",
    })
    assert late_allocation.status_code == 201, late_allocation.text

    blocked = await api.post(stale_cancel_path, json=stale_cancel_body)
    assert blocked.status_code == 409, blocked.text
    money = await api.get(prefix + "/money-basis")
    assert money.status_code == 200 and money.json()["money_state"] == "funds_held"

    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(InvoiceCancellationReceipt)) == 0
        assert await session.scalar(select(func.count()).select_from(InvoiceReservationRelease)) == 0

    refund_entry = await bank(
        api, (org, policy.id), 1, "trace-late-refund", amount="20.00", direction="payment",
    )
    refunded = await api.post(prefix + "/settlements", json={
        "bank_entry_id": refund_entry,
        "source_key": "trace-late-refund",
        "amount": "20.00",
        "refund_of": late_allocation.json()["id"],
        "evidence": "CRM-ACC-001 confirmed full refund",
    })
    assert refunded.status_code == 201, refunded.text

    cancel_path, cancel_body = await cancel_request(api, org, facts)
    cancelled = await api.post(cancel_path, json=cancel_body)
    assert cancelled.status_code == 201, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert (await api.post(cancel_path, json=cancel_body)).json() == cancelled.json()

    async with factory() as session:
        document = await session.get(DealDocument, 1)
        release = await session.scalar(select(InvoiceReservationRelease))
        assert document.status == "cancelled" and document.reserve_status == "released"
        assert release is not None and release.document_id == 1 and release.organization_id == org
        assert all(line["after_qty"] == "0.00" for line in release.snapshot["lines"])
        assert await session.scalar(select(func.count()).select_from(InvoiceCancellationReceipt)) == 1
        assert await session.scalar(select(func.count()).select_from(PhysicalShipmentAct)) == 0
        assert await session.scalar(select(func.count()).select_from(ReservationVersion)) >= 2
        cancelled_events = await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.event_type == "sales.invoice.cancelled",
        ))
        assert cancelled_events == 1
