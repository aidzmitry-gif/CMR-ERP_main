# ruff: noqa: F811 -- imported pytest fixtures
"""Actual registered adapters and SQLite rows; not PostgreSQL lock evidence."""
import json
from dataclasses import FrozenInstanceError

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.auth import CurrentUser
from core.services.logistics import snapshot_hash, snapshot_row
from modules.logistics.models import (
    CarrierRfqInvite,
    ShipmentIntake,
    ShipmentJournal,
    ShippingExecution,
)
from tests.test_logistics_invoice_binding import exact  # noqa: F401
from tests.test_office_shipping_associations import office, prepare_office  # noqa: F401
from tests.test_sales_shipping_associations import confirmation, order, prepare_order  # noqa: F401


async def snapshot(api, session, exact):
    return await api._transport.app.state.core.services.logistics.invoice_fulfillment_snapshot(
        session, exact_invoice=exact, user=CurrentUser("ship-tester", ["director"]))


async def test_split_collect_has_no_source_callbacks_and_is_single_use(api, session, exact, monkeypatch):
    services = api._transport.app.state.core.services
    gateway = services.logistics
    prepared = await gateway.prepare_invoice_fulfillment_snapshot(
        session, exact_invoice=exact, user=CurrentUser("ship-tester", ["director"]))
    assert await session.get(ShipmentJournal, 1) is None
    with pytest.raises(FrozenInstanceError):
        prepared.sources_json = "{}"

    async def forbidden(*args, **kwargs):
        raise AssertionError("Source callback after prepare")

    with monkeypatch.context() as patch:
        patch.setattr(services.shipping_producer, "invoice_shipping_sources_snapshot", forbidden)
        patch.setattr(services.accounting, "source_member", forbidden)
        result = await gateway.collect_prepared_invoice_fulfillment_snapshot(session, prepared)
    assert result == await snapshot(api, session, exact)
    with pytest.raises(HTTPException) as error:
        await gateway.collect_prepared_invoice_fulfillment_snapshot(session, prepared)
    assert error.value.status_code == 409


@pytest.mark.parametrize("end", ["commit", "rollback"])
async def test_split_context_expires_with_root_transaction(api, session, exact, end):
    gateway = api._transport.app.state.core.services.logistics
    prepared = await gateway.prepare_invoice_fulfillment_snapshot(
        session, exact_invoice=exact, user=CurrentUser("ship-tester", ["director"]))
    await getattr(session, end)()
    with pytest.raises(HTTPException) as error:
        await gateway.collect_prepared_invoice_fulfillment_snapshot(session, prepared)
    assert error.value.status_code == 409


async def test_split_rejects_other_session_and_savepoints(api, session, exact):
    gateway = api._transport.app.state.core.services.logistics
    prepared = await gateway.prepare_invoice_fulfillment_snapshot(
        session, exact_invoice=exact, user=CurrentUser("ship-tester", ["director"]))
    async with AsyncSession() as other:
        with pytest.raises(HTTPException) as error:
            await gateway.collect_prepared_invoice_fulfillment_snapshot(other, prepared)
        assert error.value.status_code == 409
    async with session.begin_nested():
        for operation in (
            gateway.collect_prepared_invoice_fulfillment_snapshot(session, prepared),
            gateway.prepare_invoice_fulfillment_snapshot(session, exact_invoice=exact,
                user=CurrentUser("ship-tester", ["director"])),
        ):
            with pytest.raises(HTTPException) as error:
                await operation
            assert error.value.status_code == 409


async def test_split_rejects_unflushed_business_changes(api, session, exact):
    gateway = api._transport.app.state.core.services.logistics
    prepared = await gateway.prepare_invoice_fulfillment_snapshot(
        session, exact_invoice=exact, user=CurrentUser("ship-tester", ["director"]))
    row = ShipmentIntake(source_kind="order", source_key="unflushed", source_revision="1",
                        request_digest="a" * 64, snapshot={})
    session.add(row)
    with pytest.raises(HTTPException) as error:
        await gateway.collect_prepared_invoice_fulfillment_snapshot(session, prepared)
    assert error.value.status_code == 409
    session.expunge(row)


async def test_empty_snapshot_initializes_only_technical_gate(api, session, exact):
    assert await session.get(ShipmentJournal, 1) is None
    result = await snapshot(api, session, exact)
    assert result["coverage_complete"] is False
    assert await session.get(ShipmentJournal, 1) is not None
    assert "journal_generation" not in result
    assert all(result[name] == [] for name in ("shipments", "rfqs", "bids", "invites", "intakes", "executions"))
    assert result["sha256"] == snapshot_hash({k: v for k, v in result.items() if k != "sha256"})
    assert await snapshot(api, session, exact) == result
    assert not session.new and not session.dirty and not session.deleted
    await session.rollback()


async def test_bound_producers_without_intake_are_included(api, session, exact, order, office):
    envelope = await prepare_order(api, order)
    response = await api.post("/sales/deals/1/documents/10/shipping-association-confirm", json=confirmation(envelope, exact))
    assert response.status_code == 200, response.text
    request, _ = await prepare_office(api, office)
    response = await api.post(f"/office/docs/{office.id}/shipping-association-confirm", json=confirmation(request, exact, assignment=1))
    assert response.status_code == 200, response.text
    assert not list(await session.scalars(select(ShipmentIntake)))
    from modules.office.shipping_associations import OfficeInvoiceAssociation, ShippingRequest
    from modules.sales.shipping_associations import OrderInvoiceAssociation, ShippingEnvelope

    business_models = (OrderInvoiceAssociation, ShippingEnvelope, OfficeInvoiceAssociation, ShippingRequest, ShippingExecution)
    business_before = [[snapshot_row(row) for row in await session.scalars(select(model))] for model in business_models]
    result = await snapshot(api, session, exact)
    assert {s["source"]["kind"] for s in result["producer_sources"]["sources"]} == {"office", "order"}
    assert len(result["executions"]) == 1 and result["intakes"] == []
    assert await snapshot(api, session, exact) == result
    assert business_before == [[snapshot_row(row) for row in await session.scalars(select(model))] for model in business_models]
    await session.execute(update(ShippingExecution).values(intent_digest="0" * 64))
    with pytest.raises(HTTPException) as error:
        await snapshot(api, session, exact)
    assert error.value.status_code == 409


async def test_public_bid_changes_actual_hash_without_generation(api, session, exact):
    response = await api.post("/logistics/rfqs", json={"invoice": exact, "source_key": "snapshot-rfq", "cargo": "A"})
    assert response.status_code == 201, response.text
    session.add(CarrierRfqInvite(rfq_id=response.json()["id"], carrier_code="dpd", token="snapshot-secret", detail="secret-url"))
    await session.commit()
    before = await snapshot(api, session, exact)
    generation = (await session.get(ShipmentJournal, 1, populate_existing=True)).generation
    await session.commit()
    response = await api.post("/logistics/rfqs/bid/snapshot-secret", json={"price": 50, "eta_days": 1})
    assert response.status_code == 201, response.text
    after = await snapshot(api, session, exact)
    assert generation == (await session.get(ShipmentJournal, 1, populate_existing=True)).generation
    assert before["sha256"] != after["sha256"] and len(after["bids"]) == 1
    assert "snapshot-secret" not in json.dumps(after) and "secret-url" not in json.dumps(after)


async def test_foreign_bound_writer_does_not_change_local_snapshot(api, session, exact):
    from modules.accounting.models import AccessGrant
    from modules.sales.models import DealDocument

    session.add(AccessGrant(organization_id=2, subject="foreign-writer", role="chief"))
    await session.commit()
    before = await snapshot(api, session, exact)
    generation = (await session.get(ShipmentJournal, 1, populate_existing=True)).generation
    doc = await session.get(DealDocument, 2)
    foreign = dict(organization_id=2, document_id=2, expected_version=doc.version,
        expected_content_sha256=doc.content_sha256)
    await session.commit()
    response = await api.post("/logistics/shipments", headers={"X-User": "foreign-writer"},
        json={"invoice": foreign, "source_key": "foreign-snapshot-regression", "customer": "Foreign"})
    assert response.status_code == 201, response.text
    assert response.json()["organization_id"] == 2
    assert (await session.get(ShipmentJournal, 1, populate_existing=True)).generation > generation
    after = await snapshot(api, session, exact)
    assert after == before
    assert "journal_generation" not in after


async def test_missing_adapter_fails_closed(api, session, exact):
    dispatcher = api._transport.app.state.core.services.shipping_producer
    dispatcher._adapters.pop("office")
    with pytest.raises(HTTPException) as error:
        await snapshot(api, session, exact)
    assert error.value.status_code == 503


async def test_real_resolved_intake_and_unrelated_unknown_are_scoped(api, session, order, exact):
    from modules.logistics.canonical_intakes import receive

    envelope = await prepare_order(api, order)
    response = await api.post("/sales/deals/1/documents/10/shipping-association-confirm", json=confirmation(envelope, exact))
    assert response.status_code == 200, response.text
    services = api._transport.app.state.core.services
    intake = await receive(session, services, "order", envelope["payload"])
    await session.commit()
    before = await snapshot(api, session, exact)
    assert [row["row"]["id"] for row in before["intakes"]] == [intake.id]
    assert len(before["shipments"]) == 1
    session.add(ShipmentIntake(source_kind="office", source_key="private-unknown-source", source_revision="1",
        request_digest="0" * 64, snapshot={"private": "private-payload"}, pending_reason="unknown"))
    await session.commit()
    after = await snapshot(api, session, exact)
    assert after == before
    assert "private-" not in json.dumps(after)
    await session.execute(update(ShipmentIntake).where(ShipmentIntake.id == intake.id).values(request_digest="0" * 64))
    with pytest.raises(HTTPException) as error:
        await snapshot(api, session, exact)
    assert error.value.status_code == 409
