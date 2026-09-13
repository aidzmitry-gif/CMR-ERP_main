# ruff: noqa: F811 -- pytest fixture imports
"""Actual cancellation schedules in fresh PG databases; no simulated money proof."""
import asyncio
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import OutboxEvent, User
from core.runtime.deps import get_session
from core.services.logistics import snapshot_row
from modules.accounting.models import Entry, Policy
from modules.logistics.models import CarrierBid, CarrierRfqInvite, Shipment
from modules.sales.invoice_cancellation import InvoiceCancellationReceipt, SalesFulfillmentReview
from modules.sales.invoice_settlements import InvoiceSettlement
from modules.sales.models import DealDocument
from modules.sales.reservation_source import SalesReservationSource
from modules.wms.invoice_reservations import (
    InvoiceReservationRelease,
    InvoiceReservationReleaseLine,
)
from modules.wms.invoice_shipments import PhysicalShipmentAct, PhysicalShipmentLine
from modules.wms.models import ReservationVersion, StockMovement
from tests.accounting.test_bank_documents import document
from tests.accounting.test_invoice_settlements import bank
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401
from tests.test_invoice_cancellation import cancel_request
from tests.test_invoice_issuance import erp_money_flow
from tests.test_invoice_physical_shipments import endpoint, request
from tests.test_shipping_producer_concurrency_postgres import (
    TIMEOUT,  # noqa: F401
    connection_identity,
    isolated_target,  # noqa: F401
    observe_wait,
    ready,
)

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def cancel_pg(issuance_pg, request):
    api, factory = issuance_pg
    async with factory() as session:
        database = await session.scalar(text("SELECT current_database()"))
        assert re.fullmatch(r"acc_test_[0-9a-f]{32}", database)
        early_record = Path(os.environ["PRODUCER_PG_EVIDENCE_DIR"]) / (database + ".json")
        early_record.parent.mkdir(parents=True, exist_ok=True)
        early_record.write_text(json.dumps({"database": database, "test": request.node.name, "locks": []}), encoding="utf-8")
        connection = await session.connection()
        for model in (User, CarrierBid, CarrierRfqInvite):
            await connection.run_sync(lambda conn, model=model: model.__table__.create(conn, checkfirst=True))
        await session.commit()
        await erp_money_flow(api, session)
        policy = await session.scalar(select(Policy))
        org, policy_id = policy.organization_id, policy.id
        doc = await session.get(DealDocument, 1)
        # Real bank receipt+full refund already exist; paid is historical status,
        # never a replacement for monetary evidence.
        doc.status = "paid"
        await session.commit()
        facts = await SalesReservationSource().invoice_reservation(session, 1)
        await session.commit()
    target = await api.post("/logistics/shipments", json={"invoice": {"organization_id": org, "document_id": 1,
        "expected_version": facts["version"], "expected_content_sha256": facts["content_sha256"]},
        "source_key": "cancel-safe-plan", "customer": "Synthetic"})
    assert target.status_code == 201, target.text
    pg = SimpleNamespace(api=api, factory=factory, org=org, policy=policy_id, facts=facts,
        prefix=f"/sales/organizations/{org}/invoices/1", evidence={"database": database, "test": request.node.name, "locks": []})
    output = Path(os.environ["PRODUCER_PG_EVIDENCE_DIR"])
    output.mkdir(parents=True, exist_ok=True)
    record = output / (database + ".json")
    record.write_text(json.dumps(pg.evidence), encoding="utf-8")
    try:
        yield pg
    finally:
        pg.evidence["fixture_sessions_closed"] = True
        record.write_text(json.dumps(pg.evidence, indent=2, default=str), encoding="utf-8")


async def state(pg):
    async with pg.factory() as session:
        return {m.__name__: [snapshot_row(r) for r in await session.scalars(select(m).order_by(*m.__table__.primary_key.columns))]
            for m in (DealDocument, Shipment, InvoiceCancellationReceipt, InvoiceReservationRelease,
                InvoiceReservationReleaseLine, PhysicalShipmentAct, PhysicalShipmentLine, ReservationVersion,
                StockMovement, InvoiceSettlement, Entry, OutboxEvent, SalesFulfillmentReview)}


def bank_command(pg, key="race-bank", amount="20.00", direction="receipt"):
    return (f"/accounting/organizations/{pg.org}/bank/confirm", document(policy_id=pg.policy, source=key,
        statement_reference=key, amount=amount, direction=direction,
        settlement_dimensions={"settlement_document": "sales:document:1"}))


def allocation(pg, entry, key="race-allocation", amount="20.00", refund_of=None):
    body = {"bank_entry_id": entry, "source_key": key, "amount": amount, "evidence": "Actual synthetic bank reconciliation"}
    if refund_of is not None:
        body["refund_of"] = refund_of
    return pg.prefix + "/settlements", body


async def post(pg, command):
    return await pg.api.post(command[0], json=command[1])


async def interleave_http(pg, first, second, *, first_rollback=False, fault=False):
    holding, started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    trace = {"fault_before_commit": fault, "first_rollback": first_rollback}
    app = pg.api._transport.app
    original = app.dependency_overrides[get_session]

    class BoundarySession(AsyncSession):
        async def boundary(self, action):
            if self.info["role"] == "holder" and not self.info.get("barrier_done"):
                self.info["barrier_done"] = True
                trace["holder_boundary"] = action
                assert action == ("rollback" if first_rollback else "commit")
                holding.set()
                await asyncio.wait_for(release.wait(), TIMEOUT)
                if fault:
                    raise RuntimeError("Synthetic cancel fault before actual commit")

        async def commit(self):
            await self.boundary("commit")
            await super().commit()
            trace[self.info["role"] + "_committed"] = True

        async def rollback(self):
            await self.boundary("rollback")
            await super().rollback()
            trace[self.info["role"] + "_rolled_back"] = True

    async def request_session(request: Request):
        role = request.headers["X-PG-Test-Role"]
        async with BoundarySession(bind=pg.factory.kw["bind"], expire_on_commit=False) as session:
            session.info["role"] = role
            trace[role] = await connection_identity(session)
            if role == "waiter":
                started.set()
            yield session

    async def call(command, role):
        try:
            response = await pg.api.post(command[0], json=command[1], headers={"X-PG-Test-Role": role})
            return {"status": response.status_code, "body": response.json()}
        except RuntimeError as exc:
            if not fault or role != "holder" or str(exc) != "Synthetic cancel fault before actual commit":
                raise
            return {"status": "injected_fault"}

    app.dependency_overrides[get_session] = request_session
    tasks = []
    try:
        tasks.append(asyncio.create_task(call(first, "holder")))
        await ready(holding, tasks[0])
        tasks.append(asyncio.create_task(call(second, "waiter")))
        await ready(started, tasks[1])
        holder, waiter = trace["holder"], trace["waiter"]
        assert holder["pid"] != waiter["pid"] and holder["txid"] != waiter["txid"]
        trace["blocked"] = await observe_wait(pg, waiter["pid"], holder["pid"])
        assert "accounting.organization" in trace["blocked"]["query"]
        release.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks), TIMEOUT)
        trace["results"] = results
        return results
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        app.dependency_overrides[get_session] = original
        trace["dependency_restored"] = app.dependency_overrides[get_session] is original
        pg.evidence["locks"].append(trace)


def cancellation_state(before, after, cancelled):
    doc = after["DealDocument"][0]
    old = before["DealDocument"][0]
    assert (doc["status"], doc["reserve_status"]) == (("cancelled", "released") if cancelled else ("paid", "reserved"))
    for field in ("original_html", "content_sha256", "version", "amount"):
        assert doc[field] == old[field]
    assert len(after["InvoiceCancellationReceipt"]) == len(after["InvoiceReservationRelease"]) == int(cancelled)
    assert len([r for r in after["OutboxEvent"] if r["event_type"] == "sales.invoice.cancelled"]) == int(cancelled)
    assert after["Shipment"][0]["status"] == ("withdrawn" if cancelled else "planned")


@pytest.mark.parametrize("cancel_first", [True, False])
async def test_pg_cancel_physical_both_orders(cancel_pg, cancel_first):
    pg = cancel_pg
    cancel_cmd = await cancel_request(pg.api, pg.org, pg.facts)
    physical = endpoint(pg.org), await request(pg.api, pg.org, pg.facts)
    before = await state(pg)
    responses = await interleave_http(pg, cancel_cmd if cancel_first else physical, physical if cancel_first else cancel_cmd)
    assert [r["status"] for r in responses] == [201, 409]
    after = await state(pg)
    cancellation_state(before, after, cancel_first)
    assert len(after["PhysicalShipmentAct"]) == int(not cancel_first)
    assert len(after["PhysicalShipmentLine"]) == int(not cancel_first)
    pg.evidence.update(before=before, after=after)


@pytest.mark.parametrize("cancel_first", [True, False])
async def test_pg_cancel_new_bank_both_orders(cancel_pg, cancel_first):
    pg = cancel_pg
    cancel_cmd = await cancel_request(pg.api, pg.org, pg.facts)
    before = await state(pg)
    responses = await interleave_http(pg, cancel_cmd if cancel_first else bank_command(pg), bank_command(pg) if cancel_first else cancel_cmd)
    assert [r["status"] for r in responses] == ([201, 201] if cancel_first else [201, 409])
    entry = responses[1 if cancel_first else 0]["body"]["id"]
    response = await post(pg, allocation(pg, entry))
    assert response.status_code == 201, response.text
    money = await pg.api.get(pg.prefix + "/money-basis")
    assert money.status_code == 200 and money.json()["money_state"] == "funds_held"
    assert "funds_not_fully_refunded" in money.json()["blockers"]
    if cancel_first:
        assert "cancelled_invoice_money_review_required" in money.json()["blockers"]
        replay = await post(pg, cancel_cmd)
        assert replay.json() == responses[0]["body"]
    after = await state(pg)
    cancellation_state(before, after, cancel_first)
    assert len(after["Entry"]) == len(before["Entry"]) + 1
    assert len(after["InvoiceSettlement"]) == len(before["InvoiceSettlement"]) + 1
    pg.evidence.update(before=before, after=after, money=money.json())


@pytest.mark.parametrize("cancel_first", [True, False])
async def test_pg_stale_cancel_allocation_both_orders(cancel_pg, cancel_first):
    pg = cancel_pg
    cancel_cmd = await cancel_request(pg.api, pg.org, pg.facts)
    bank_result = await post(pg, bank_command(pg))
    assert bank_result.status_code == 201
    allocate = allocation(pg, bank_result.json()["id"])
    before = await state(pg)
    responses = await interleave_http(pg, cancel_cmd if cancel_first else allocate,
        allocate if cancel_first else cancel_cmd, first_rollback=cancel_first)
    assert [r["status"] for r in responses] == ([409, 201] if cancel_first else [201, 409])
    after = await state(pg)
    cancellation_state(before, after, False)
    assert len(after["InvoiceSettlement"]) == len(before["InvoiceSettlement"]) + 1
    pg.evidence.update(before=before, after=after)


async def test_pg_cancel_same_key_concurrent_replay(cancel_pg):
    pg = cancel_pg
    command = await cancel_request(pg.api, pg.org, pg.facts)
    before = await state(pg)
    responses = await interleave_http(pg, command, command)
    assert [r["status"] for r in responses] == [201, 201]
    assert responses[0]["body"] == responses[1]["body"]
    after = await state(pg)
    cancellation_state(before, after, True)
    assert len(after["ReservationVersion"]) == len(before["ReservationVersion"]) + 1
    assert after["Entry"] == before["Entry"] and after["InvoiceSettlement"] == before["InvoiceSettlement"]
    pg.evidence.update(before=before, after=after)


async def test_pg_cancel_fault_rollback_unblocks_physical(cancel_pg):
    pg = cancel_pg
    command = await cancel_request(pg.api, pg.org, pg.facts)
    physical = endpoint(pg.org), await request(pg.api, pg.org, pg.facts)
    before = await state(pg)
    responses = await interleave_http(pg, command, physical, fault=True)
    assert [r["status"] for r in responses] == ["injected_fault", 201]
    after = await state(pg)
    cancellation_state(before, after, False)
    assert not after["InvoiceReservationReleaseLine"]
    assert len(after["PhysicalShipmentAct"]) == 1
    assert len(after["ReservationVersion"]) == len(before["ReservationVersion"]) + 1
    pg.evidence.update(before=before, after=after)


async def test_pg_paid_held_partial_full_refund(cancel_pg):
    pg = cancel_pg
    entry = await bank(pg.api, (pg.org, pg.policy), 1, "extra-paid", amount="20.00")
    allocated = await post(pg, allocation(pg, entry))
    assert allocated.status_code == 201
    before = await state(pg)
    for stage in ("held", "partial", "full"):
        if stage != "held":
            outgoing = await bank(pg.api, (pg.org, pg.policy), 1, "refund-" + stage, amount="10.00", direction="payment")
            response = await post(pg, allocation(pg, outgoing, "refund-" + stage, "10.00", allocated.json()["id"]))
            assert response.status_code == 201, response.text
        money = await pg.api.get(pg.prefix + "/money-basis")
        assert money.status_code == 200
        assert money.json()["money_state"] == ("fully_refunded" if stage == "full" else "funds_held")
        current = await state(pg)
        cancellation_state(before, current, False)
        if stage != "full":
            preview = await pg.api.post(pg.prefix + "/cancellation/preview", json={"expected_version": pg.facts["version"],
                "expected_content_sha256": pg.facts["content_sha256"]})
            assert preview.status_code == 200 and preview.json()["observed_blockers"]
            rejected = await pg.api.post(pg.prefix + "/cancel", json={"expected_version": pg.facts["version"],
                "expected_content_sha256": pg.facts["content_sha256"], "request_key": str(uuid4()),
                "fulfillment_review_id": str(uuid4()), "expected_review_digest": "0" * 64,
                "evidence": "Known funds held must not cancel", "acknowledge_invoice_invalidation": True})
            assert rejected.status_code == 409, rejected.text
    command = await cancel_request(pg.api, pg.org, pg.facts)
    assert (await post(pg, command)).status_code == 201
    after = await state(pg)
    cancellation_state(before, after, True)
    pg.evidence.update(before=before, after=after)
