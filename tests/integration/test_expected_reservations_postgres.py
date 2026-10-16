import asyncio
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from modules.accounting.models import Organization
from modules.procurement.expected_reservations import (
    ExpectedReservation,
    ReservationCreate,
    create_expected,
)
from modules.procurement.models import PurchaseOrder, PurchaseOrderLine
from modules.procurement.ownership import PurchaseOwnership
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.models import Deal
from tests.accounting.test_postgres import pg_factory  # noqa: F401

pytestmark = pytest.mark.integration


async def test_pg_malformed_stock_event_remains_unprocessed_without_pending_reserve(pg_factory):  # noqa: F811
    from core.domain.models import OutboxEvent
    from core.services.eventbus import OutboxEventBus
    from modules.procurement import events
    from modules.procurement.expected_reservations import (
        ExpectedConversionRequest,
        ExpectedReservationEvent,
    )

    bus = OutboxEventBus()
    bus.subscribe("sales.stock.reserved", events.on_stock_reserved_for_expected)
    async with pg_factory() as session:
        bus.emit(session, "sales.stock.reserved", {"organization_id": 1, "document_id": 1,
                 "items": [{"sku_code": "PG-SKU", "qty": "NaN"}]})
        await session.commit()
    with pytest.raises(ValueError, match="quantity is invalid"):
        await bus.relay_pending(pg_factory, SimpleNamespace())
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.processed_at.is_(None))) == 1
        assert await session.scalar(select(func.count()).select_from(ExpectedConversionRequest)) == 0
        assert await session.scalar(select(func.count()).select_from(ExpectedReservationEvent)) == 0


@pytest.mark.parametrize("earlier_reserve", [False, True])
async def test_pg_relay_delivers_reserve_before_qc_and_finishes_pending_request(pg_factory, earlier_reserve):  # noqa: F811
    from core.domain.models import OutboxEvent
    from core.services.eventbus import OutboxEventBus
    from modules.procurement import events
    from modules.procurement.expected_reservations import (
        ExpectedConversionRequest,
        ExpectedReservationEvent,
        ReservationEventInput,
        append_event,
    )
    from modules.procurement.receipt_documents import ReceiptDocument, ReceiptRevision
    from modules.sales.models import DealDocument

    order_id, line_id, deal_id = await setup_expected(pg_factory, 1)
    bus = OutboxEventBus()
    bus.subscribe("sales.stock.reserved", events.on_stock_reserved_for_expected)
    bus.subscribe("wms.receipt.accepted", events.on_physical_receipt_accepted)
    async with pg_factory() as session:
        first_id = None
        if earlier_reserve:
            result, _ = await create_expected(session, 1, "tester", command(order_id, line_id, deal_id, "6.00"))
            first_id = result["reservations"][0]["id"]
        invoice = DealDocument(deal_id=deal_id, kind="invoice", number="PG-LATE-QC", status="issued")
        session.add(invoice)
        await session.flush()
        await create_expected(session, 1, "tester", ReservationCreate(
            order_id=order_id, order_line_id=line_id, deal_id=deal_id, document_id=invoice.id,
            qty="6.00", request_key=str(uuid4()), evidence="Synthetic reverse delivery",
        ))
        receipt = ReceiptDocument(organization_id=1, source_key="pg-late-qc", current_version=1,
                                  status="draft", created_by="tester")
        session.add(receipt)
        await session.flush()
        session.add(ReceiptRevision(receipt_id=receipt.id, version=1, actor="tester", document={
            "items": [{"order_line_id": line_id, "sku": "PG-SKU", "quantity": "6.00"}],
        }))
        bus.emit(session, "sales.stock.reserved", {"organization_id": 1, "document_id": invoice.id,
                 "reservation_digest": "a" * 64,
                 "items": [{"sku_code": "PG-SKU", "qty": "6.00"}]})
        bus.emit(session, "wms.receipt.accepted", {"organization_id": 1, "receipt_id": 88,
            "source_receipt_id": receipt.id, "source_version": 1,
            "lines": [{"position": 1, "sku_code": "PG-SKU", "accepted_qty": "6.00",
                       "source_line": f"procurement:receipt:{receipt.id}:1:1"}]})
        await session.commit()
    assert await bus.relay_pending(pg_factory, SimpleNamespace(), limit=1) == 1
    async with pg_factory() as session:
        request = await session.scalar(select(ExpectedConversionRequest))
        assert request.completed is False
        assert await session.scalar(select(func.count()).select_from(ExpectedReservationEvent)) == 0
    assert await bus.relay_pending(pg_factory, SimpleNamespace(), limit=1) == 1
    assert await bus.relay_pending(pg_factory, SimpleNamespace()) == 0
    if earlier_reserve:
        async with pg_factory() as session:
            assert (await session.scalar(select(ExpectedConversionRequest))).completed is False
            await append_event(session, 1, "tester", first_id, ReservationEventInput(
                kind="release", qty="6.00", request_key=str(uuid4()), evidence="Prior customer cancelled",
            ))
            await session.commit()
    async with pg_factory() as session:
        original = await session.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "sales.stock.reserved"))
        bus.emit(session, "sales.stock.reserved", original.payload)
        await session.commit()
    assert await bus.relay_pending(pg_factory, SimpleNamespace()) == 1
    async with pg_factory() as session:
        request = await session.scalar(select(ExpectedConversionRequest))
        assert request.completed is True
        assert await session.scalar(select(func.count()).select_from(ExpectedConversionRequest)) == 1
        assert await session.scalar(select(func.sum(ExpectedReservationEvent.qty)).where(
            ExpectedReservationEvent.kind == "convert")) == Decimal("6.00")
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.processed_at.is_(None))) == 0
        for statement in (
            "UPDATE procurement.expected_conversion_request SET completed = false",
            "UPDATE procurement.expected_conversion_request SET reservation_ids = '[]'::json",
            "DELETE FROM procurement.expected_conversion_request",
            "TRUNCATE procurement.expected_conversion_request",
        ):
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.execute(text(statement))


async def setup_expected(factory, org_id):
    async with factory() as session:
        session.add(Organization(id=org_id, name="PG Expected Org", unp="123456789"))
        await session.flush()
        order = PurchaseOrder(number="PG-EXPECTED", supplier="Supplier", status="ordered")
        session.add(order)
        await session.flush()
        line = PurchaseOrderLine(order_id=order.id, sku_code="PG-SKU", qty=Decimal("100.00"))
        deal = Deal(number="PG-DEAL-EXPECTED", title="Expected", counterparty="Buyer", amount=0)
        session.add_all([line, deal])
        await session.flush()
        session.add_all([
            PurchaseOwnership(organization_id=org_id, kind="order", source_id=order.id,
                              snapshot={}, evidence="Synthetic", actor="tester"),
            DealOwnership(deal_id=deal.id, organization_id=org_id, snapshot={}, evidence="Synthetic", actor="tester"),
        ])
        await session.commit()
        return order.id, line.id, deal.id


def command(order_id, line_id, deal_id, qty):
    return ReservationCreate(order_id=order_id, order_line_id=line_id, deal_id=deal_id,
        qty=qty, request_key=str(uuid4()), evidence="PG expected reservation")


async def test_pg_competing_expected_reservations_are_capped_and_history_is_immutable(pg_factory):  # noqa: F811
    org_id = 1
    order_id, line_id, deal_id = await setup_expected(pg_factory, org_id)

    async def writer(qty):
        async with pg_factory() as session:
            try:
                result, replayed = await create_expected(session, org_id, "tester",
                    command(order_id, line_id, deal_id, qty))
                await session.commit()
                return 201, replayed, result
            except HTTPException as exc:
                await session.rollback()
                return exc.status_code, False, None

    results = await asyncio.gather(writer("60.00"), writer("60.00"))
    assert sorted(row[0] for row in results) == [201, 409]
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ExpectedReservation)) == 1
        assert await session.scalar(select(func.sum(ExpectedReservation.qty))) == 60
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(text("UPDATE procurement.expected_reservation SET evidence='tampered'"))
        await session.rollback()
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(text("DELETE FROM procurement.expected_reservation"))
        await session.rollback()
