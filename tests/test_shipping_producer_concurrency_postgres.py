"""Actual registered producers and PG waits; only fresh pg_factory databases."""
import asyncio
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from core.domain.models import AuditLog, OutboxEvent, User
from core.runtime.app import create_app
from core.services.auth import CurrentUser
from core.services.shipping_payload import shipping_intent_digest
from modules.accounting.models import AccessGrant, Organization
from modules.logistics.models import CarrierRfq, Shipment, ShipmentIntake, ShippingExecution
from modules.office.shipping_access import assign_reviewer
from modules.office.shipping_associations import (
    OfficeInvoiceAssociation,
    ShippingRequest,
    ShippingReviewAssignment,
)
from modules.office.shipping_producer import ConfirmInput as OfficeConfirm
from modules.office.shipping_producer import OfficeShippingProducer
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.models import Deal, DealDocument
from modules.sales.shipping_associations import OrderInvoiceAssociation, ShippingEnvelope
from modules.sales.shipping_producer import ConfirmInput as SalesConfirm
from modules.sales.shipping_producer import SalesShippingProducer
from modules.wms.models import StockMovement
from tests.accounting.test_postgres import pg_factory  # noqa: F401

TIMEOUT = 30
OFFICE_EVENT = "logistics.delivery.requested"


@pytest.fixture(scope="module", autouse=True)
def isolated_target():
    raw = os.getenv("ACCOUNTING_TEST_POSTGRES_URL")
    if not raw:
        pytest.fail("Explicit isolated PostgreSQL URL is required, no skip")
    url = make_url(raw)
    if url.host not in {"127.0.0.1", "localhost"} or url.port != 15436 or url.database != "accounting_test":
        pytest.fail("Refusing PostgreSQL target outside local port 15436/accounting_test")


def intent(mode="spot"):
    return {"mode": mode, "customer": "Synthetic receiver", "cargo": "Synthetic goods", "weight_kg": "2.00",
        "declared_value_byn": "100.00", "route_from": "W", "route_to": "Minsk", "address": "Synthetic address",
        "zone_code": "z1", "carrier_code": "dpd", "carrier_name": "DPD", "pickup_date": "2026-09-11",
        "contact": "Synthetic", "comment": ""}


def confirmation(envelope, exact, kind):
    return {"request_key": "bind-" + kind, "expected_source_hash": envelope["source_sha256"],
        "expected_assignment_revision": 1 if kind == "office" else 0, "exact_invoice": exact,
        "envelope_id": envelope["envelope_id"], "expected_payload_hash": envelope["payload_sha256"],
        "expected_intent_digest": shipping_intent_digest(exact, envelope["payload"]["intent"]),
        "evidence_refs": {"source_sha256": envelope["source_sha256"],
            "invoice_sha256": exact["expected_content_sha256"], "explanation": "Compared exact synthetic originals"}}


@pytest_asyncio.fixture
async def producer_pg(pg_factory, request):  # noqa: F811
    factory = pg_factory
    app = create_app()
    core = app.state.core
    assert core.services.config.auth_mode == "dev"
    core.services.db.session_factory = factory
    # Runtime registration is tested, never replaced with a test dispatcher.
    assert isinstance(core.services.shipping_producer._adapter("office"), OfficeShippingProducer)
    assert isinstance(core.services.shipping_producer._adapter("order"), SalesShippingProducer)
    actor = CurrentUser("pg-producer", ["director"])
    revoker = CurrentUser("pg-revoker", ["director"])
    async with factory() as session:
        database = await session.scalar(text("SELECT current_database()"))
        assert re.fullmatch(r"acc_test_[0-9a-f]{32}", database)
        for name in ("sales.shipping_envelope", "sales.order_invoice_association", "office.shipping_request",
                     "office.office_invoice_association", "office.shipping_review_assignment"):
            assert await session.scalar(text("SELECT to_regclass(:name)"), {"name": name}) == name
        conn = await session.connection()
        # Existing baseline only. All new shipping/physical tables came from the
        # frozen proposal in pg_factory; no repeated guard SQL or create_all.
        await conn.run_sync(lambda sync: User.__table__.create(sync, checkfirst=True))
        session.add_all([User(username=actor.username, full_name="Synthetic producer", role="director", status="active"),
            User(username=revoker.username, full_name="Synthetic revoker", role="director", status="active"),
            Organization(id=1, name="Synthetic", unp="999999971"),
            Deal(id=1, number="PG-D1", title="Synthetic", counterparty="Synthetic")])
        await session.flush()
        session.add(AccessGrant(organization_id=1, subject=actor.username, role="chief"))
        session.add(DealOwnership(deal_id=1, organization_id=1, snapshot={}, evidence="Synthetic", actor=actor.username))
        exact = None
        order_hash = None
        for document_id, kind in ((1, "invoice"), (10, "order")):
            html = f"<p>Synthetic original {kind}</p>"
            digest = hashlib.sha256(html.encode()).hexdigest()
            session.add(DealDocument(id=document_id, deal_id=1, number=f"PG-{kind}", kind=kind,
                version=1, status="paid" if kind == "invoice" else "posted", reserve_status="reserved", amount=100,
                original_html=html, content_sha256=digest, issued_at=datetime(2026, 9, 10),
                snapshot_json={"items": [{"sku_code": "A", "qty": "2"}]}))
            if kind == "invoice":
                exact = dict(organization_id=1, document_id=1, expected_version=1, expected_content_sha256=digest)
            else:
                order_hash = digest
        await session.commit()
    evidence = {"database": database, "test": request.node.name, "locks": []}
    evidence_dir = Path(os.environ["PRODUCER_PG_EVIDENCE_DIR"])
    evidence_dir.mkdir(parents=True, exist_ok=True)
    record = evidence_dir / (database + ".json")
    record.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           headers={"X-User": actor.username, "X-User-Roles": "director"}) as api:
        response = await api.post("/office/docs", json={"number": "PG-OFF", "company": "Synthetic", "title": "Goods", "amount": 100})
        assert response.status_code == 201, response.text
        doc_id = response.json()["id"]
        response = await api.post(f"/office/docs/{doc_id}/shipping-reviewer", json={
            "subject": actor.username, "expected_revision": 0, "evidence": "Synthetic review mandate"})
        assert response.status_code == 200, response.text
        pg = SimpleNamespace(factory=factory, core=core, api=api, actor=actor, revoker=revoker,
            exact=exact, order_hash=order_hash, doc_id=doc_id, evidence=evidence)
        try:
            yield pg
        finally:
            evidence["fixture_sessions_closed"] = True
            record.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")


async def prepare(pg, kind, shipping_intent=None):
    data = {"request_key": "prepare-" + kind, "intent": shipping_intent or intent()}
    if kind == "office":
        source = await pg.api.get(f"/office/docs/{pg.doc_id}/shipping-source")
        assert source.status_code == 200, source.text
        data.update(expected_source_hash=source.json()["source_sha256"], expected_assignment_revision=1)
        url = f"/office/docs/{pg.doc_id}/carrier-request"
    else:
        data["expected_source_hash"] = pg.order_hash
        url = "/sales/deals/1/documents/10/shipping-envelope"
    response = await pg.api.post(url, json=data)
    assert response.status_code == 200, response.text
    return response.json()


async def bind(pg, session, kind, envelope):
    adapter = pg.core.services.shipping_producer._adapter(kind)
    data = confirmation(envelope, pg.exact, kind)
    if kind == "office":
        return await adapter.association(session, pg.doc_id, OfficeConfirm.model_validate(data), pg.actor, confirm=True)
    return await adapter.association(session, 1, 10, SalesConfirm.model_validate(data), pg.actor, confirm=True)


async def revoke(pg, session):
    return await assign_reviewer(pg.core, session, pg.doc_id, pg.revoker,
        subject="", expected_revision=1, evidence="Synthetic revocation")


async def connection_identity(session):
    row = (await session.execute(text("SELECT pg_backend_pid(), txid_current()"))).one()
    return {"pid": row[0], "txid": row[1]}


async def ready(event, task):
    signal = asyncio.create_task(event.wait())
    try:
        done, _ = await asyncio.wait({signal, task}, timeout=TIMEOUT, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            await task  # propagate the actual writer failure, not a timeout
        assert signal in done and event.is_set(), "Writer did not reach the barrier"
    finally:
        signal.cancel()
        await asyncio.gather(signal, return_exceptions=True)


async def observe_wait(pg, waiter, holder):
    async with asyncio.timeout(TIMEOUT):
        async with pg.factory() as observer:
            while True:
                blockers = await observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter})
                if holder in blockers:
                    row = (await observer.execute(text(
                        "SELECT wait_event_type,wait_event,query FROM pg_stat_activity WHERE pid=:pid"), {"pid": waiter})).one()
                    assert row.wait_event_type == "Lock"
                    return {"waiter_pid": waiter, "holder_pid": holder, "blockers": blockers,
                        "wait_event": row.wait_event, "query": row.query}
                await asyncio.sleep(0.02)


async def interleave(pg, first, second):
    holding, started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    trace = {}

    async def holder():
        async with pg.factory() as session:
            trace["holder"] = await connection_identity(session)
            value = await first(session)
            holding.set()
            await asyncio.wait_for(release.wait(), TIMEOUT)
            await session.commit()
            return {"status": 200, "result": value}

    async def waiter():
        async with pg.factory() as session:
            trace["waiter"] = await connection_identity(session)
            started.set()
            try:
                value = await second(session)
                await session.commit()
                return {"status": 200, "result": value}
            except HTTPException as exc:
                await session.rollback()
                return {"status": exc.status_code, "detail": exc.detail}

    tasks = [asyncio.create_task(holder())]
    try:
        await ready(holding, tasks[0])
        tasks.append(asyncio.create_task(waiter()))
        await ready(started, tasks[1])
        trace["blocked"] = await observe_wait(pg, trace["waiter"]["pid"], trace["holder"]["pid"])
        release.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks), TIMEOUT)
        trace["results"] = results
        pg.evidence["locks"].append(trace)
        return results, trace
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def state(pg):
    result = {}
    async with pg.factory() as session:
        for model in (ShippingExecution, Shipment, CarrierRfq, ShipmentIntake, OrderInvoiceAssociation,
                      OfficeInvoiceAssociation, ShippingEnvelope, ShippingRequest, ShippingReviewAssignment,
                      StockMovement, OutboxEvent, AuditLog):
            rows = await session.scalars(select(model).order_by(model.id))
            result[model.__name__] = [{c.name: getattr(row, c.name) for c in model.__table__.columns} for row in rows]
    return result


async def test_pg_revoke_then_bind(producer_pg):
    pg = producer_pg
    envelope = await prepare(pg, "office")
    results, trace = await interleave(pg, lambda s: revoke(pg, s), lambda s: bind(pg, s, "office", envelope))
    assert "office.office_doc" in trace["blocked"]["query"]
    assert results[0]["status"] == 200 and results[1]["status"] in {403, 404}
    after = await state(pg)
    assert not after["OfficeInvoiceAssociation"] and not after["ShippingExecution"]
    assert not after["Shipment"] and not after["CarrierRfq"]
    assert after["ShippingRequest"][0]["payload_sha256"] == envelope["payload_sha256"]
    pg.evidence["counts"] = {key: len(value) for key, value in after.items()}


async def test_pg_bind_then_revoke(producer_pg):
    pg = producer_pg
    envelope = await prepare(pg, "office")
    results, trace = await interleave(pg, lambda s: bind(pg, s, "office", envelope), lambda s: revoke(pg, s))
    assert "office.office_doc" in trace["blocked"]["query"]
    assert [r["status"] for r in results] == [200, 200]
    before = await state(pg)
    with pytest.raises(HTTPException) as error:
        await pg.core.event_bus.relay_pending(pg.factory, pg.core.services, event_types=[OFFICE_EVENT])
    assert error.value.status_code == 409
    after = await state(pg)
    assert after == before
    assert len(after["OfficeInvoiceAssociation"]) == len(after["ShippingExecution"]) == 1
    assert not after["ShipmentIntake"] and not after["Shipment"] and not after["CarrierRfq"]
    pg.evidence["execution_id"] = results[0]["result"]["execution_id"]


@pytest.mark.parametrize("first_kind", ["order", "office"])
@pytest.mark.parametrize("different", [False, True])
async def test_pg_order_office_concurrent_claim(producer_pg, first_kind, different):
    pg = producer_pg
    office_intent = {**intent(), "route_to": "Other"} if different else intent()
    envelopes = {"order": await prepare(pg, "order"), "office": await prepare(pg, "office", office_intent)}
    second_kind = "office" if first_kind == "order" else "order"
    results, trace = await interleave(pg, lambda s: bind(pg, s, first_kind, envelopes[first_kind]),
        lambda s: bind(pg, s, second_kind, envelopes[second_kind]))
    assert "accounting.organization" in trace["blocked"]["query"]
    assert [r["status"] for r in results] == [200, 409 if different else 200]
    if not different:
        assert results[0]["result"]["execution_id"] == results[1]["result"]["execution_id"]
    assert await pg.core.event_bus.relay_pending(pg.factory, pg.core.services,
        event_types=["sales.document.posted", OFFICE_EVENT]) == 2
    after = await state(pg)
    assert len(after["ShippingExecution"]) == len(after["Shipment"]) == 1
    assert len(after["OrderInvoiceAssociation"]) + len(after["OfficeInvoiceAssociation"]) == (1 if different else 2)
    assert sorted(row["state"] for row in after["ShipmentIntake"]) == (["pending", "resolved"] if different else ["resolved", "resolved"])
    assert after["ShippingEnvelope"][0]["payload_sha256"] == envelopes["order"]["payload_sha256"]
    assert after["ShippingRequest"][0]["payload_sha256"] == envelopes["office"]["payload_sha256"]
    pg.evidence["execution_id"] = after["ShippingExecution"][0]["id"]
    pg.evidence["counts"] = {key: len(value) for key, value in after.items()}


@pytest.mark.parametrize("mode", ["spot", "contract"])
async def test_pg_resolved_replay_after_revoke(producer_pg, mode):
    pg = producer_pg
    envelope = await prepare(pg, "office", intent(mode))
    response = await pg.api.post(f"/office/docs/{pg.doc_id}/shipping-association-confirm",
        json=confirmation(envelope, pg.exact, "office"))
    assert response.status_code == 200, response.text
    assert await pg.core.event_bus.relay_pending(pg.factory, pg.core.services, event_types=[OFFICE_EVENT]) == 1
    response = await pg.api.post(f"/office/docs/{pg.doc_id}/shipping-reviewer", json={
        "subject": "", "expected_revision": 1, "evidence": "Synthetic revoke after resolved"}, headers={"X-User": pg.revoker.username})
    assert response.status_code == 200, response.text
    before = await state(pg)
    intake_id = before["ShipmentIntake"][0]["id"]
    async with pg.factory() as session:
        duplicate = OutboxEvent(event_type=OFFICE_EVENT, version=1, payload=envelope["payload"])
        session.add(duplicate)
        await session.commit()
        duplicate_id = duplicate.id
    assert await pg.core.event_bus.relay_pending(pg.factory, pg.core.services, event_types=[OFFICE_EVENT]) == 1
    after = await state(pg)
    for name in before.keys() - {"OutboxEvent", "AuditLog"}:
        assert after[name] == before[name], name
    assert [r for r in after["OutboxEvent"] if r["id"] != duplicate_id] == before["OutboxEvent"]
    assert next(r for r in after["OutboxEvent"] if r["id"] == duplicate_id)["processed_at"] is not None
    assert after["AuditLog"][:-1] == before["AuditLog"]
    assert len(after["AuditLog"]) == len(before["AuditLog"]) + 1
    assert after["AuditLog"][-1]["action"] == OFFICE_EVENT
    response = await pg.api.post(f"/logistics/intakes/{intake_id}/resolve")
    assert response.status_code in {403, 404}, response.text
    forged = {**envelope["payload"], "intent": {**envelope["payload"]["intent"], "cargo": "Forged"},
        "payload_sha256": envelope["payload_sha256"]}
    async with pg.factory() as session:
        pg.core.event_bus.emit(session, OFFICE_EVENT, forged)
        await session.commit()
    before_forged = await state(pg)
    with pytest.raises(HTTPException) as error:
        await pg.core.event_bus.relay_pending(pg.factory, pg.core.services, event_types=[OFFICE_EVENT])
    assert error.value.status_code == 409
    assert await state(pg) == before_forged
    pg.evidence.update(execution_id=after["ShippingExecution"][0]["id"], intake_id=intake_id,
        duplicate_outbox_id=duplicate_id, replay_domain_rows_unchanged=True, delivery_audit_increment=1)
