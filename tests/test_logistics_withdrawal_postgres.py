# ruff: noqa: F811 -- imported pytest fixtures
"""Eight bounded PG schedules for Logistics only; no Sales cancellation proof."""
import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.runtime.deps import get_session
from core.services.logistics import snapshot_row
from modules.logistics.canonical_intakes import receive
from modules.logistics.models import CarrierBid, CarrierRfqInvite, ShipmentJournal
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.test_logistics_fulfillment_snapshot_postgres import (  # noqa: F401
    read_snapshot,
    snapshot_pg,
)
from tests.test_shipping_producer_concurrency_postgres import (
    TIMEOUT,
    bind,
    connection_identity,
    intent,
    isolated_target,  # noqa: F401
    observe_wait,
    prepare,  # noqa: F401
    producer_pg,  # noqa: F401
    ready,
    state,
)

pytestmark = pytest.mark.integration


async def setup_target(pg, kind):
    data = {**intent("spot" if kind == "shipment" else "contract"), "carrier_name": "", "carrier_code": ""}
    envelopes = {k: await prepare(pg, k, data) for k in ("order", "office")}
    async with pg.factory() as session:
        for k, envelope in envelopes.items():
            await bind(pg, session, k, envelope)
        intake = await receive(session, pg.core.services, "order", envelopes["order"]["payload"])
        target_id = intake.shipment_id if kind == "shipment" else intake.rfq_id
        if kind == "public":
            session.add(CarrierRfqInvite(rfq_id=target_id, carrier_code="dpd", token="withdraw-pg-token"))
        await session.commit()
    return target_id


async def business(pg):
    result = await state(pg)
    async with pg.factory() as session:
        for model in (CarrierBid, CarrierRfqInvite, ShipmentJournal):
            result[model.__name__] = [snapshot_row(row) for row in await session.scalars(select(model).order_by(model.id))]
    return result


async def schedule(pg, kind, target_id, *, writer_first=False, rollback=False):
    """Delay the actual HTTP commit, never replace business logic or row locks."""
    before_snapshot = await read_snapshot(pg)
    before = await business(pg)
    holding, started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    trace = {"kind": kind, "writer_first": writer_first, "withdrawal_rollback": rollback}
    app = pg.api._transport.app
    missing = object()
    original = app.dependency_overrides.get(get_session, missing)

    class CommitBarrierSession(AsyncSession):
        async def commit(self):
            if writer_first and not self.info.get("withdrawal_test_barrier_passed"):
                self.info["withdrawal_test_barrier_passed"] = True
                holding.set()
                await asyncio.wait_for(release.wait(), TIMEOUT)
            await super().commit()
            trace["writer_actual_commit"] = True

    async def writer_session():
        async with CommitBarrierSession(bind=pg.factory.kw["bind"], expire_on_commit=False) as session:
            trace["writer"] = await connection_identity(session)
            if not writer_first:
                started.set()
            yield session

    async def writer():
        if kind == "shipment":
            url, data = f"/logistics/shipments/{target_id}/carrier-order", {"carrier_code": "dpd"}
        elif kind == "rfq":
            url, data = f"/logistics/rfqs/{target_id}/bids", {"carrier_code": "dpd", "price": 10}
        else:
            url, data = "/logistics/rfqs/bid/withdraw-pg-token", {"price": 10, "eta_days": 1}
        response = await pg.api.post(url, json=data)
        return {"status": response.status_code, "result": response.json()}

    async def withdrawal():
        async with pg.factory() as session:
            trace["withdrawal"] = await connection_identity(session)
            if writer_first:
                started.set()
            gateway = pg.core.services.logistics
            try:
                prepared = await gateway.prepare_invoice_fulfillment_snapshot(session, exact_invoice=pg.exact, user=pg.actor)
                current = await gateway.collect_prepared_invoice_fulfillment_snapshot(session, prepared)
                result = await gateway.withdraw_unexecuted_invoice(session, prepared=prepared, current_snapshot=current,
                    expected_digest=before_snapshot["sha256"], cancel_receipt_identity={"exact_invoice": pg.exact,
                        "cancellation_receipt_id": str(uuid4()), "cancellation_request_sha256": "a" * 64})
                value = {"status": 200, "result": result}
            except HTTPException as exc:
                value = {"status": exc.status_code, "detail": exc.detail}
            if not writer_first:
                holding.set()
                await asyncio.wait_for(release.wait(), TIMEOUT)
            if rollback or value["status"] != 200:
                await session.rollback()
                trace["withdrawal_actual_rollback"] = True
            else:
                await session.commit()
                trace["withdrawal_actual_commit"] = True
            return value

    app.dependency_overrides[get_session] = writer_session
    tasks = []
    try:
        tasks.append(asyncio.create_task(writer() if writer_first else withdrawal()))
        await ready(holding, tasks[0])
        tasks.append(asyncio.create_task(withdrawal() if writer_first else writer()))
        await ready(started, tasks[1])
        holder = trace["writer" if writer_first else "withdrawal"]
        waiter = trace["withdrawal" if writer_first else "writer"]
        assert holder["pid"] != waiter["pid"] and holder["txid"] != waiter["txid"]
        trace["holder"], trace["waiter"] = holder, waiter
        trace["blocked"] = await observe_wait(pg, waiter["pid"], holder["pid"])
        assert "accounting.organization" in trace["blocked"]["query"]
        release.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks), TIMEOUT)
        trace["results"] = results
        w, d = results if writer_first else results[::-1]
        success_writer = writer_first or rollback or kind == "public"
        assert w["status"] == ((200 if kind == "shipment" else 201) if success_writer else 409)
        assert d["status"] == (409 if writer_first or kind == "public" else 200)
        assert bool(trace.get("writer_actual_commit")) == success_writer
        after = await business(pg)
        after_snapshot = await read_snapshot(pg)
        # Immutable provenance and resolved links survive every schedule.
        for name in ("ShippingExecution", "OrderInvoiceAssociation", "OfficeInvoiceAssociation",
                     "ShippingEnvelope", "ShippingRequest", "ShippingReviewAssignment", "ShipmentIntake", "StockMovement"):
            assert before[name] == after[name], name
        target = after["Shipment" if kind == "shipment" else "CarrierRfq"][0]
        assert target["status"] == (("assigned" if kind == "shipment" else "collecting") if success_writer else "withdrawn")
        assert len(after["CarrierBid"]) == (1 if success_writer and kind != "shipment" else 0)
        if success_writer and kind == "shipment":
            assert target["carrier_order_no"]
            assert len(after["OutboxEvent"]) == len(before["OutboxEvent"]) + 1
        else:
            assert after["OutboxEvent"] == before["OutboxEvent"]
        assert after["AuditLog"] == before["AuditLog"]
        assert not any(r["state"] == "withdrawn" for r in after["ShipmentIntake"])
        if kind == "public":
            assert after["CarrierRfqInvite"][0]["status"] == "responded"
            assert after["ShipmentJournal"] == before["ShipmentJournal"]
        else:
            assert after["ShipmentJournal"][0]["generation"] == before["ShipmentJournal"][0]["generation"] + 1
        trace.update(before_sha256=before_snapshot["sha256"], after_sha256=after_snapshot["sha256"],
            business_before=before, business_after=after)
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if original is missing:
            app.dependency_overrides.pop(get_session, None)
        else:
            app.dependency_overrides[get_session] = original
        trace["dependency_restored"] = app.dependency_overrides.get(get_session, missing) is original
        pg.evidence["locks"].append(trace)


@pytest.mark.parametrize("kind", ["shipment", "rfq", "public"])
@pytest.mark.parametrize("writer_first", [False, True])
async def test_pg_withdrawal_writer_both_orders(snapshot_pg, kind, writer_first):
    target = await setup_target(snapshot_pg, kind)
    await schedule(snapshot_pg, kind, target, writer_first=writer_first)


@pytest.mark.parametrize("kind", ["shipment", "rfq"])
async def test_pg_withdrawal_rollback_unblocks_real_writer(snapshot_pg, kind):
    target = await setup_target(snapshot_pg, kind)
    await schedule(snapshot_pg, kind, target, rollback=True)
