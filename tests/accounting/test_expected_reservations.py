from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from modules.procurement import events as procurement_events
from modules.procurement.expected_reservations import (
    ExpectedConversionRequest,
    ExpectedReservation,
    ExpectedReservationEvent,
    PhysicalReceiptAcceptance,
)
from modules.procurement.models import PurchaseOrder, PurchaseOrderLine
from modules.procurement.ownership import PurchaseOwnership
from modules.procurement.receipt_documents import ReceiptDocument, ReceiptRevision
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.models import Deal, DealDocument


async def setup_expected(db, book):
    order = PurchaseOrder(number="PO-EXPECTED", supplier="Supplier", status="ordered")
    db.add(order)
    await db.flush()
    line = PurchaseOrderLine(order_id=order.id, sku_code="SKU-EXPECTED", qty=Decimal("100.00"))
    deal = Deal(number="DEAL-EXPECTED", title="Expected goods", counterparty="Buyer", amount=0)
    db.add_all([line, deal])
    await db.flush()
    db.add_all([
        PurchaseOwnership(organization_id=book[0], kind="order", source_id=order.id,
                          snapshot={}, evidence="Order ownership", actor="tester"),
        DealOwnership(deal_id=deal.id, organization_id=book[0], snapshot={}, evidence="Deal ownership", actor="tester"),
    ])
    await db.commit()
    return order.id, line.id, deal.id


def payload(order_id, line_id, deal_id, qty="60.00", document_id=None):
    return {"order_id": order_id, "order_line_id": line_id, "deal_id": deal_id,
            "document_id": document_id, "qty": qty, "request_key": str(uuid4()), "evidence": "Customer demand"}


def accepted_by_warehouse(organization_id, receipt_id, line_id, qty):
    return PhysicalReceiptAcceptance(
        organization_id=organization_id, event_id=700, receipt_id=receipt_id,
        source_receipt_id=receipt_id, source_version=1,
        lines=[{"position": 1, "order_line_id": line_id, "sku_code": "SKU-EXPECTED",
                "accepted_qty": qty, "source_line": "primary:1"}],
        evidence="Warehouse QC accepted", actor="warehouse-user",
    )


@pytest.mark.parametrize("items", [
    [], None, [None], [{"sku_code": "", "qty": "1.00"}],
    *[[{"sku_code": "SKU", "qty": qty}] for qty in
      [None, True, "NaN", "Infinity", "0", "-1", "0.001", "1e100000", "1000000000000"]],
    [{"sku_code": "SKU", "qty": "600000000000"}, {"sku_code": "SKU", "qty": "600000000000"}],
])
async def test_invalid_stock_event_creates_no_waiting_request_or_conversion(db, book, items):
    with pytest.raises(ValueError, match="Expected conversion"):
        await procurement_events.on_stock_reserved_for_expected(
            {"organization_id": book[0], "document_id": 1, "items": items},
            SimpleNamespace(session=db, event_id=9001),
        )
    assert await db.scalar(select(func.count()).select_from(ExpectedConversionRequest)) == 0
    assert await db.scalar(select(func.count()).select_from(ExpectedReservationEvent)) == 0


async def test_expected_reserve_shows_free_quantity_and_idempotent_retry(client, db, book):
    order_id, line_id, deal_id = await setup_expected(db, book)
    command = payload(order_id, line_id, deal_id)
    first = await client.post(f"/procurement/organizations/{book[0]}/expected-reservations",
                              json=command)
    assert first.status_code == 201, first.text
    assert first.json()["free_expected"] == "40.00"
    aggregate = await client.get(f"/procurement/organizations/{book[0]}/expected-reservations/order/{order_id}")
    assert aggregate.status_code == 200 and aggregate.json()["lines"][0]["expected_reserved"] == "60.00"
    repeat = await client.post(f"/procurement/organizations/{book[0]}/expected-reservations",
                               json=command)
    assert repeat.status_code == 201 and repeat.json()["replayed"] is True
    same = await client.post(f"/procurement/organizations/{book[0]}/expected-reservations",
                             json={**payload(order_id, line_id, deal_id), "qty": "30.00"})
    assert same.status_code == 201 and same.json()["free_expected"] == "10.00"
    over = await client.post(f"/procurement/organizations/{book[0]}/expected-reservations",
                             json={**payload(order_id, line_id, deal_id), "qty": "11.00"})
    assert over.status_code == 409
    assert await db.scalar(select(func.count()).select_from(ExpectedReservation)) == 2


async def test_expected_release_is_append_only_and_converts_only_after_receipt(client, db, book):
    order_id, line_id, deal_id = await setup_expected(db, book)
    created = await client.post(f"/procurement/organizations/{book[0]}/expected-reservations",
                                json=payload(order_id, line_id, deal_id, "60.00"))
    reservation_id = created.json()["reservations"][0]["id"]
    assert created.json()["accepted"] == "0.00"
    assert created.json()["converted"] == "0.00"
    assert created.json()["convertible"] == "0.00"
    event_url = f"/procurement/organizations/{book[0]}/expected-reservations/{reservation_id}/events"
    convert = await client.post(event_url, json={"kind": "convert", "qty": "1.00", "request_key": str(uuid4()), "evidence": "No receipt yet"})
    assert convert.status_code == 409
    receipt = ReceiptDocument(organization_id=book[0], source_key="accepted-for-expected", current_version=1,
                              status="draft", created_by="tester")
    db.add(receipt)
    await db.flush()
    db.add(ReceiptRevision(receipt_id=receipt.id, version=1, actor="tester", document={
        "items": [{"order_line_id": line_id, "quantity": "20.00"}],
    }))
    await db.commit()
    draft_only = await client.post(event_url, json={"kind": "convert", "qty": "1.00", "request_key": str(uuid4()), "evidence": "Primary draft only"})
    assert draft_only.status_code == 409
    await db.refresh(receipt)
    db.add(accepted_by_warehouse(book[0], receipt.id, line_id, "20.00"))
    await db.commit()
    converted = await client.post(event_url, json={"kind": "convert", "qty": "5.00", "request_key": str(uuid4()), "evidence": "Accepted receipt"})
    assert converted.status_code == 201 and converted.json()["reservations"][0]["converted"] == "5.00"
    assert converted.json()["accepted"] == "20.00"
    assert converted.json()["converted"] == "5.00"
    assert converted.json()["convertible"] == "15.00"
    assert converted.json()["reservations"][0]["convertible"] == "15.00"
    released = await client.post(event_url, json={"kind": "release", "qty": "10.00", "request_key": str(uuid4()), "evidence": "Customer cancelled"})
    assert released.status_code == 201 and released.json()["free_expected"] == "35.00"
    count = await db.scalar(select(func.count()).select_from(ExpectedReservationEvent))
    assert count == 2


async def test_conversion_uses_stable_reservation_order(client, db, book):
    order_id, line_id, first_deal_id = await setup_expected(db, book)
    second_deal = Deal(number="DEAL-EXPECTED-2", title="Second expected goods", counterparty="Buyer 2", amount=0)
    db.add(second_deal)
    await db.flush()
    db.add(DealOwnership(deal_id=second_deal.id, organization_id=book[0], snapshot={}, evidence="Order ownership", actor="tester"))
    await db.commit()

    first = await client.post(
        f"/procurement/organizations/{book[0]}/expected-reservations",
        json=payload(order_id, line_id, first_deal_id, "10.00"),
    )
    second = await client.post(
        f"/procurement/organizations/{book[0]}/expected-reservations",
        json=payload(order_id, line_id, second_deal.id, "10.00"),
    )
    assert first.status_code == second.status_code == 201
    first_id = first.json()["reservations"][0]["id"]
    second_id = second.json()["reservations"][1]["id"]

    receipt = ReceiptDocument(
        organization_id=book[0], source_key="stable-conversion-order", current_version=1,
        status="draft", created_by="tester",
    )
    db.add(receipt)
    await db.flush()
    db.add(ReceiptRevision(receipt_id=receipt.id, version=1, actor="tester", document={
        "items": [{"order_line_id": line_id, "quantity": "5.00"}],
    }))
    await db.commit()

    db.add(accepted_by_warehouse(book[0], receipt.id, line_id, "5.00"))
    await db.commit()
    blocked = await client.post(
        f"/procurement/organizations/{book[0]}/expected-reservations/{second_id}/events",
        json={"kind": "convert", "qty": "1.00", "request_key": str(uuid4()), "evidence": "Later reserve first"},
    )
    assert blocked.status_code == 409
    converted = await client.post(
        f"/procurement/organizations/{book[0]}/expected-reservations/{first_id}/events",
        json={"kind": "convert", "qty": "5.00", "request_key": str(uuid4()), "evidence": "Accepted receipt"},
    )
    assert converted.status_code == 201
    view = (await client.get(f"/procurement/organizations/{book[0]}/expected-reservations/order/{order_id}")).json()
    assert view["lines"][0]["reservations"][0]["converted"] == "5.00"
    assert view["lines"][0]["reservations"][1]["convertible"] == "0.00"


async def test_wms_reservation_closes_only_accepted_expected_quantity_and_replays(client, db, book):
    order_id, line_id, deal_id = await setup_expected(db, book)
    document = DealDocument(deal_id=deal_id, kind="invoice", number="ERP-EXPECTED-1", status="issued")
    db.add(document)
    await db.flush()
    created = await client.post(
        f"/procurement/organizations/{book[0]}/expected-reservations",
        json=payload(order_id, line_id, deal_id, "10.00", document_id=document.id),
    )
    assert created.status_code == 201
    receipt = ReceiptDocument(
        organization_id=book[0], source_key="wms-reserved-expected", current_version=1,
        status="draft", created_by="tester",
    )
    db.add(receipt)
    await db.flush()
    db.add(ReceiptRevision(receipt_id=receipt.id, version=1, actor="tester", document={
        "items": [{"order_line_id": line_id, "quantity": "4.00"}],
    }))
    await db.commit()
    db.add(accepted_by_warehouse(book[0], receipt.id, line_id, "4.00"))
    await db.commit()
    payload_value = {
        "organization_id": book[0], "document_id": document.id,
        "reservation_digest": "a" * 64,
        "items": [{"line_no": 1, "sku_code": "SKU-EXPECTED", "warehouse": "Главный", "qty": "4.00"}],
        "by": "warehouse-user",
    }
    context = SimpleNamespace(session=db, event_id=701)
    await procurement_events.on_stock_reserved_for_expected({**payload_value, "items": [
        {**payload_value["items"][0], "qty": "7.00"},
    ]}, SimpleNamespace(session=db, event_id=702))
    await db.rollback()
    assert await db.scalar(select(func.count()).select_from(ExpectedReservationEvent)) == 0
    await procurement_events.on_stock_reserved_for_expected(payload_value, context)
    await db.commit()
    view = (await client.get(
        f"/procurement/organizations/{book[0]}/expected-reservations/order/{order_id}"
    )).json()
    assert view["lines"][0]["accepted"] == "4.00"
    assert view["lines"][0]["converted"] == "4.00"
    assert view["lines"][0]["convertible"] == "0.00"
    assert view["lines"][0]["reservations"][0]["converted"] == "4.00"
    await procurement_events.on_stock_reserved_for_expected(payload_value, context)
    await db.commit()
    assert await db.scalar(select(func.count()).select_from(ExpectedReservationEvent)) == 1


async def test_physical_acceptance_preserves_source_version_and_rejects_changed_replay(db, book):
    receipt = ReceiptDocument(organization_id=book[0], source_key="qc-history", current_version=2,
                              status="draft", created_by="tester")
    db.add(receipt)
    await db.flush()
    db.add(ReceiptRevision(receipt_id=receipt.id, version=1, actor="tester", document={
        "items": [{"order_line_id": 15, "sku": "QC-SKU", "quantity": "8.00"}],
    }))
    await db.commit()
    command = {
        "organization_id": book[0], "receipt_id": 42, "source_receipt_id": receipt.id,
        "source_version": 1, "lines": [{"position": 1, "sku_code": "QC-SKU",
            "accepted_qty": "5.00", "source_line": f"procurement:receipt:{receipt.id}:1:1"}],
    }
    context = SimpleNamespace(session=db, event_id=902)
    await procurement_events.on_physical_receipt_accepted(command, context)
    await db.commit()
    await procurement_events.on_physical_receipt_accepted(command, context)
    assert await db.scalar(select(func.count()).select_from(PhysicalReceiptAcceptance)) == 1
    row = await db.scalar(select(PhysicalReceiptAcceptance))
    assert row.lines[0]["accepted_qty"] == "5.00"
    assert row.lines[0]["order_line_id"] == 15
    with pytest.raises(ValueError, match="another source"):
        await procurement_events.on_physical_receipt_accepted({**command, "lines": [
            {**command["lines"][0], "accepted_qty": "6.00"},
        ]}, context)
    with pytest.raises(ValueError, match="source line differs"):
        await procurement_events.on_physical_receipt_accepted({**command, "lines": [
            {**command["lines"][0], "source_line": "wrong"},
        ]}, context)


async def test_reservation_before_qc_retries_after_acceptance_without_losing_quantity(client, db, book):
    order_id, line_id, deal_id = await setup_expected(db, book)
    document = DealDocument(deal_id=deal_id, kind="invoice", number="ERP-QC-LATE", status="issued")
    db.add(document)
    await db.flush()
    document_id = document.id
    created = await client.post(
        f"/procurement/organizations/{book[0]}/expected-reservations",
        json=payload(order_id, line_id, deal_id, "6.00", document_id=document_id),
    )
    assert created.status_code == 201
    reserve = {"organization_id": book[0], "document_id": document_id,
               "reservation_digest": "a" * 64,
               "items": [{"sku_code": "SKU-EXPECTED", "qty": "6.00"}]}
    context = SimpleNamespace(session=db, event_id=801)
    await procurement_events.on_stock_reserved_for_expected(reserve, context)
    await db.commit()
    assert await db.scalar(select(func.count()).select_from(ExpectedReservationEvent)) == 0
    request = await db.scalar(select(ExpectedConversionRequest))
    assert request.completed is False
    unrelated = ExpectedConversionRequest(organization_id=book[0] + 100, event_identity="foreign",
        payload_hash="b" * 64, payload={}, reservation_ids=list(request.reservation_ids), completed=False)
    db.add(unrelated)
    await db.commit()
    pending_view = (await client.get(
        f"/procurement/organizations/{book[0]}/expected-reservations/order/{order_id}"
    )).json()["lines"][0]
    assert pending_view["pending_conversion_count"] == 1
    later = await client.post(
        f"/procurement/organizations/{book[0]}/expected-reservations",
        json=payload(order_id, line_id, deal_id, "2.00", document_id=document_id),
    )
    assert later.status_code == 201

    receipt = ReceiptDocument(organization_id=book[0], source_key="delayed-qc", current_version=1,
                              status="draft", created_by="tester")
    db.add(receipt)
    await db.flush()
    receipt_id = receipt.id
    db.add(ReceiptRevision(receipt_id=receipt_id, version=1, actor="tester", document={
        "items": [{"order_line_id": line_id, "sku": "SKU-EXPECTED", "quantity": "6.00"}],
    }))
    await db.commit()
    await procurement_events.on_physical_receipt_accepted({
        "organization_id": book[0], "receipt_id": 81, "source_receipt_id": receipt_id,
        "source_version": 1, "lines": [{"position": 1, "sku_code": "SKU-EXPECTED",
            "accepted_qty": "6.00", "source_line": f"procurement:receipt:{receipt_id}:1:1"}],
    }, SimpleNamespace(session=db, event_id=802))
    await db.commit()
    await procurement_events.on_stock_reserved_for_expected(reserve, context)
    await db.commit()
    await procurement_events.on_stock_reserved_for_expected(reserve, context)
    await db.commit()
    assert await db.scalar(select(func.count()).select_from(ExpectedReservationEvent)) == 1
    view = (await client.get(
        f"/procurement/organizations/{book[0]}/expected-reservations/order/{order_id}"
    )).json()["lines"][0]
    assert view["converted"] == "6.00"
    assert view["pending_conversion_count"] == 0
    assert view["expected_reserved"] == "2.00"
    assert view["reservations"][1]["converted"] == "0.00"
    await db.refresh(request)
    assert request.completed is True
    assert len(request.reservation_ids) == 1
    await procurement_events.on_stock_reserved_for_expected(reserve, SimpleNamespace(session=db, event_id=899))
    await db.commit()
    assert await db.scalar(select(func.count()).select_from(ExpectedConversionRequest).where(
        ExpectedConversionRequest.organization_id == book[0])) == 1
    assert await db.scalar(select(func.count()).select_from(ExpectedReservationEvent)) == 1
    with pytest.raises(ValueError, match="payload changed"):
        await procurement_events.on_stock_reserved_for_expected({**reserve, "items": [
            {"sku_code": "SKU-EXPECTED", "qty": "8.00"},
        ]}, SimpleNamespace(session=db, event_id=900))


@pytest.mark.parametrize("release_kind", ["manual", "deal_loss"])
async def test_fifo_release_completes_waiting_customer_without_another_qc(client, db, book, release_kind):
    order_id, line_id, first_deal_id = await setup_expected(db, book)
    first = await client.post(f"/procurement/organizations/{book[0]}/expected-reservations",
                              json=payload(order_id, line_id, first_deal_id, "5.00"))
    assert first.status_code == 201
    first_id = first.json()["reservations"][0]["id"]
    deal = Deal(number="FIFO-NEXT", title="Next customer", counterparty="Next", amount=0)
    db.add(deal)
    await db.flush()
    db.add(DealOwnership(deal_id=deal.id, organization_id=book[0], snapshot={},
                         evidence="Synthetic", actor="tester"))
    invoice = DealDocument(deal_id=deal.id, kind="invoice", number="FIFO-NEXT-INV", status="issued")
    db.add(invoice)
    await db.flush()
    second = await client.post(f"/procurement/organizations/{book[0]}/expected-reservations",
        json=payload(order_id, line_id, deal.id, "5.00", document_id=invoice.id))
    assert second.status_code == 201
    db.add(accepted_by_warehouse(book[0], 91, line_id, "5.00"))
    await db.commit()
    reserve = {"organization_id": book[0], "document_id": invoice.id,
               "items": [{"sku_code": "SKU-EXPECTED", "qty": "5.00"}]}
    await procurement_events.on_stock_reserved_for_expected(reserve, SimpleNamespace(session=db, event_id=991))
    await db.commit()
    assert (await db.scalar(select(ExpectedConversionRequest))).completed is False
    if release_kind == "manual":
        command = {"kind": "release", "qty": "5.00", "request_key": str(uuid4()), "evidence": "Customer cancelled"}
        url = f"/procurement/organizations/{book[0]}/expected-reservations/{first_id}/events"
        assert (await client.post(url, json=command)).status_code == 201
        assert (await client.post(url, json=command)).json()["replayed"] is True
    else:
        command = {"organization_id": book[0], "deal_id": first_deal_id, "resolution_id": str(uuid4())}
        for _ in range(2):
            await procurement_events.on_deal_loss_finalized(command, SimpleNamespace(session=db))
            await db.commit()
    request = await db.scalar(select(ExpectedConversionRequest).execution_options(populate_existing=True))
    assert request.completed is True
    view = (await client.get(f"/procurement/organizations/{book[0]}/expected-reservations/order/{order_id}")).json()["lines"][0]
    assert view["reservations"][0]["released"] == "5.00"
    assert view["reservations"][1]["converted"] == "5.00"
    assert await db.scalar(select(func.count()).select_from(ExpectedReservationEvent)) == 2
