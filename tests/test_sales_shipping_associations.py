# ruff: noqa: F811 -- imported pytest fixtures are injected by parameter name
"""Real SQLite originals, producer rows, outbox and execution gate; no PG lock proof."""
import hashlib
from datetime import datetime

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select, update
from starlette.requests import Request

from core.domain.models import OutboxEvent, User
from core.runtime.app import create_app
from core.runtime.contract import Role
from core.services.auth import CurrentUser
from core.services.shipping_payload import shipping_intent_digest
from modules.logistics.models import ShippingExecution
from modules.sales.access import get_deal_access, get_deal_access_for_user, visible_deal_or_404
from modules.sales.models import Deal, DealDocument
from modules.sales.shipping_associations import OrderInvoiceAssociation, ShippingEnvelope
from modules.sales.shipping_producer import ConfirmInput, SalesShippingProducer
from tests.test_logistics_invoice_binding import exact  # noqa: F401
from tests.test_shipping_payload import payload


@pytest_asyncio.fixture
async def order(session, exact):
    original = "<p>issued order</p>"
    row = DealDocument(id=10, deal_id=1, number="O10", kind="order", status="posted", version=1,
        original_html=original, content_sha256=hashlib.sha256(original.encode()).hexdigest(),
        issued_at=datetime(2026, 9, 10), amount=100)
    session.add(row)
    await session.commit()
    return row


def confirmation(envelope, exact, *, assignment=0, key="bind-1"):
    return {"request_key": key, "expected_source_hash": envelope["source_sha256"],
        "expected_assignment_revision": assignment, "exact_invoice": exact,
        "envelope_id": envelope["envelope_id"], "expected_payload_hash": envelope["payload_sha256"],
        "expected_intent_digest": shipping_intent_digest(exact, envelope["payload"]["intent"]),
        "evidence_refs": {"source_sha256": envelope["source_sha256"],
            "invoice_sha256": exact["expected_content_sha256"], "explanation": "Compared the two exact originals"}}


async def prepare_order(api, order, intent=None):
    response = await api.post("/sales/deals/1/documents/10/shipping-envelope", json={
        "request_key": "order-1", "expected_source_hash": order.content_sha256,
        "intent": intent or payload()["intent"]})
    assert response.status_code == 200, response.text
    return response.json()


async def test_reverse_snapshot_checks_original_and_read_permission(api, session, order, exact):
    envelope = await prepare_order(api, order)
    response = await api.post("/sales/deals/1/documents/10/shipping-association-confirm", json=confirmation(envelope, exact))
    assert response.status_code == 200, response.text
    core = api._transport.app.state.core
    core.declare_role(Role("snapshot-reader", permissions=("sales.deal.read",)))
    producer = SalesShippingProducer(core)
    user = CurrentUser("ship-tester", ["snapshot-reader"])
    discovery = await producer.discover_invoice_shipping_sources(session, exact_invoice=exact, user=user)
    assert discovery["source_document_ids"] == [1, 10]
    result = await producer.lock_invoice_shipping_sources_snapshot(session, exact_invoice=exact, user=user, discovery=discovery)
    assert len(result["sources"]) == 1 and result["coverage_complete"] is False
    await session.execute(update(DealDocument).where(DealDocument.id == 10).values(original_html="corrupt"))
    with pytest.raises(HTTPException) as error:
        await producer.lock_invoice_shipping_sources_snapshot(session, exact_invoice=exact, user=user, discovery=discovery)
    assert error.value.status_code == 409


async def test_order_http_envelope_late_bind_and_exact_replay(api, session, order, exact):
    envelope = await prepare_order(api, order)
    assert await prepare_order(api, order) == envelope
    events = list(await session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "sales.document.posted")))
    assert len(events) == 1
    assert events[0].payload["payload_sha256"] == envelope["payload_sha256"]
    producer = SalesShippingProducer(create_app().state.core)
    lookup = {"source_kind": "order", "source_key": "sales:order:10", "source_revision": "1"}
    assert await producer.resolve_shipping_source(session, **lookup) is None
    data = confirmation(envelope, exact)
    preview = await api.post("/sales/deals/1/documents/10/shipping-association-preview", json=data)
    assert preview.status_code == 200, preview.text
    assert "issued order" in preview.json()["source_original"]
    assert not list(await session.scalars(select(ShippingExecution)))
    first = await api.post("/sales/deals/1/documents/10/shipping-association-confirm", json=data)
    assert first.status_code == 200, first.text
    repeated = await api.post("/sales/deals/1/documents/10/shipping-association-confirm", json=data)
    assert repeated.status_code == 200 and repeated.json()["replayed"]
    assert repeated.json()["execution_id"] == first.json()["execution_id"]
    assert await producer.resolve_shipping_source(session, **lookup) == exact
    verified = await producer.verify_shipping_source(session, **lookup, actual_payload_hash=envelope["payload_sha256"])
    assert verified["execution_id"] == first.json()["execution_id"]
    assert (await session.get(ShippingEnvelope, envelope["envelope_id"])).payload_sha256 == envelope["payload_sha256"]
    assert len(list(await session.scalars(select(ShippingExecution)))) == 1
    assert len(list(await session.scalars(select(OrderInvoiceAssociation)))) == 1


@pytest.mark.parametrize("change", ["source", "payload", "intent", "evidence", "foreign_invoice"])
async def test_order_confirmation_rejects_mismatch(api, session, order, exact, change):
    envelope = await prepare_order(api, order)
    data = confirmation(envelope, exact)
    if change == "evidence":
        data["evidence_refs"]["source_sha256"] = "0" * 64
    elif change == "foreign_invoice":
        data["exact_invoice"] = {**exact, "document_id": 2}
    else:
        data[{"source": "expected_source_hash", "payload": "expected_payload_hash", "intent": "expected_intent_digest"}[change]] = "0" * 64
    response = await api.post("/sales/deals/1/documents/10/shipping-association-confirm", json=data)
    assert response.status_code == 409, response.text
    assert not list(await session.scalars(select(OrderInvoiceAssociation)))
    assert not list(await session.scalars(select(ShippingExecution)))


async def test_actual_hash_and_original_tampering_fail(api, session, order, exact):
    envelope = await prepare_order(api, order)
    producer = SalesShippingProducer(create_app().state.core)
    lookup = dict(source_kind="order", source_key="sales:order:10", source_revision="1")
    with pytest.raises(HTTPException) as error:
        await producer.verify_shipping_source(session, **lookup, actual_payload_hash="0" * 64)
    assert error.value.status_code == 409
    await session.execute(update(DealDocument).where(DealDocument.id == 10).values(original_html="tampered"))
    with pytest.raises(HTTPException) as error:
        await producer.verify_shipping_source(session, **lookup, actual_payload_hash=envelope["payload_sha256"])
    assert error.value.status_code == 409


async def test_terminal_new_bind_rejected_but_existing_confirmation_is_read_only(api, session, order, exact):
    envelope = await prepare_order(api, order)
    producer = SalesShippingProducer(create_app().state.core)
    user = CurrentUser("ship-tester", ["director"])
    data = ConfirmInput.model_validate(confirmation(envelope, exact))
    result = await producer.association(session, 1, 10, data, user, confirm=True)
    await session.commit()
    await session.execute(update(DealDocument).where(DealDocument.id == 1).values(status="cancelled"))
    await session.commit()
    replay = await producer.association(session, 1, 10, data, user, confirm=True)
    assert replay["replayed"] and replay["execution_id"] == result["execution_id"]
    assert not session.new and not session.dirty


async def test_own_scope_foreign_inactive_and_oidc_no_username_fallback(session, api, order):
    session.add(User(username="scoped", full_name="Scoped", employee_id=101, deal_visibility="own", role="sales", status="active"))
    await session.execute(update(Deal).where(Deal.id == 1).values(owner_id=101))
    await session.commit()
    user = CurrentUser("scoped", ["sales"])
    access = await get_deal_access_for_user(session, user)
    assert (await visible_deal_or_404(session, 1, access)).id == 1
    with pytest.raises(HTTPException) as error:
        await visible_deal_or_404(session, 2, access)
    assert error.value.status_code == 404
    with pytest.raises(HTTPException) as error:
        await get_deal_access_for_user(session, CurrentUser("scoped", ["sales"], "unlinked-sub"))
    assert error.value.status_code == 403
    await session.execute(update(User).where(User.username == "scoped").values(status="disabled"))
    with pytest.raises(HTTPException) as error:
        await get_deal_access_for_user(session, user)
    assert error.value.status_code == 403
    assert (await get_deal_access(Request({"type": "http", "path": "/sales/ping", "headers": []}), session, user)).visibility == "all"


async def test_permission_rechecked_using_current_registry(session, api, order):
    core = create_app().state.core
    core.declare_role(Role("worker-test", permissions=("sales.shipping.associate",)))
    producer = SalesShippingProducer(core)
    await prepare_order(api, order)
    user = CurrentUser("employee", ["worker-test"])
    lookup = dict(source_kind="order", source_key="sales:order:10", user=user)
    await producer.authorize_shipping_intake(session, **lookup)
    core.roles[:] = [r for r in core.roles if r.name != "worker-test"]
    with pytest.raises(HTTPException) as error:
        await producer.authorize_shipping_intake(session, **lookup)
    assert error.value.status_code == 403


async def test_envelope_rollback_also_rolls_back_outbox(api, session, order):
    from modules.sales.shipping_producer import EnvelopeInput

    producer = SalesShippingProducer(create_app().state.core)
    await producer.prepare(session, 1, 10, EnvelopeInput(request_key="rollback", expected_source_hash=order.content_sha256,
        intent=payload()["intent"]), CurrentUser("ship-tester", ["director"]))
    await session.rollback()
    assert not list(await session.scalars(select(ShippingEnvelope)))
    assert not list(await session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "sales.document.posted")))


async def test_own_guarded_http_route_allowed_and_foreign_hidden(api, session, order):
    from modules.accounting.models import AccessGrant

    core = api._transport.app.state.core
    core.declare_role(Role("sales", permissions=("sales.shipping.associate",)))
    session.add(User(username="scoped", full_name="Scoped", employee_id=101, deal_visibility="own", role="sales", status="active"))
    session.add(AccessGrant(organization_id=1, subject="scoped", role="reader"))
    await session.execute(update(Deal).where(Deal.id == 1).values(owner_id=101))
    await session.commit()
    data = {"request_key": "scoped-order", "expected_source_hash": order.content_sha256, "intent": payload()["intent"]}
    headers = {"X-User": "scoped", "X-User-Roles": "sales"}
    result = await api.post("/sales/deals/1/documents/10/shipping-envelope", json=data, headers=headers)
    assert result.status_code == 200, result.text
    result = await api.post("/sales/deals/2/documents/10/shipping-envelope", json=data, headers=headers)
    assert result.status_code == 404, result.text


async def test_immutable_envelope_rejects_orm_mutation(api, session, order):
    envelope = await prepare_order(api, order)
    row = await session.get(ShippingEnvelope, envelope["envelope_id"])
    row.payload_sha256 = "0" * 64
    with pytest.raises(ValueError, match="immutable"):
        await session.flush()
    await session.rollback()
    assert (await session.get(ShippingEnvelope, envelope["envelope_id"])).payload_sha256 == envelope["payload_sha256"]


@pytest.mark.parametrize("state", ["pending", "resolved"])
@pytest.mark.parametrize("terminal", ["cancelled", "superseded"])
async def test_terminal_order_keeps_history_but_cannot_promote(api, session, order, exact, state, terminal):
    from core.services.logistics import ShippingProducerDispatcher
    from modules.logistics.canonical_intakes import receive
    from modules.office.shipping_producer import OfficeShippingProducer
    from tests.test_office_shipping_associations import durable_state

    core = api._transport.app.state.core
    core.services.shipping_producer = ShippingProducerDispatcher(
        order=SalesShippingProducer(core), office=OfficeShippingProducer(core))
    envelope = await prepare_order(api, order)
    if state == "pending":
        assert (await receive(session, core.services, "order", envelope["payload"])).state == "pending"
        await session.commit()
    response = await api.post("/sales/deals/1/documents/10/shipping-association-confirm", json=confirmation(envelope, exact))
    assert response.status_code == 200, response.text
    if state == "resolved":
        assert (await receive(session, core.services, "order", envelope["payload"])).state == "resolved"
        await session.commit()
    # Synthetic lifecycle state fixtures; this suite does not claim cancellation
    # or supersession writer evidence.
    if terminal == "cancelled":
        await session.execute(update(DealDocument).where(DealDocument.id == 10).values(status="cancelled"))
    else:
        session.add(DealDocument(id=11, deal_id=1, kind="order", number="O11", version=2, status="draft", amount=100))
        await session.flush()
        await session.execute(update(DealDocument).where(DealDocument.id == 10).values(superseded_by_id=11))
    await session.commit()
    before = await durable_state(session)
    verified = await core.services.shipping_producer.verify_shipping_source(session,
        source_kind="order", source_key="sales:order:10", source_revision="1", actual_payload_hash=envelope["payload_sha256"])
    assert verified["fulfillment_allowed"] is False
    if state == "resolved":
        assert (await receive(session, core.services, "order", envelope["payload"])).state == "resolved"
        await session.commit()
    else:
        with pytest.raises(HTTPException) as error:
            await receive(session, core.services, "order", envelope["payload"])
        assert error.value.status_code == 409
        await session.rollback()
    assert await durable_state(session) == before
