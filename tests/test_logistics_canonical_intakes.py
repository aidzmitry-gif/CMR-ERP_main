"""Actual consumer/storage; producer boundary is an explicitly pinned test adapter."""
from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from core.runtime.app import create_app
from core.services.logistics import ShippingProducerDispatcher
from core.services.shipping_payload import canonical_shipping_payload
from modules.logistics import events
from modules.logistics.canonical_intakes import receive
from modules.logistics.models import CarrierRfq, Shipment, ShipmentIntake
from modules.sales.models import DealDocument
from tests.test_logistics_execution import claim
from tests.test_logistics_invoice_binding import exact  # noqa: F401
from tests.test_shipping_payload import payload


class PinnedProducer:
    def __init__(self, exact_invoice, execution, envelopes):
        self.exact, self.execution = exact_invoice, execution
        self.fulfillment_allowed = True
        self.hashes = {(p["source"]["kind"], p["source"]["key"]): canonical_shipping_payload(p)[1] for p in envelopes}

    async def resolve_shipping_source(self, session, **lookup):
        return self.exact

    async def verify_shipping_source(self, session, *, source_kind, source_key, actual_payload_hash, **kwargs):
        expected = self.hashes[(source_kind, source_key)]
        if expected != actual_payload_hash:
            raise HTTPException(409, "Producer payload changed")
        return {**self.execution, "payload_sha256": expected, "association_id": "fixture", "association_revision": 1,
                "fulfillment_allowed": self.fulfillment_allowed}


@pytest.mark.parametrize("mode", ["spot", "contract"])
async def test_two_producers_share_execution_and_terminal_exact_replay(session, api, exact, mode, terminal_field="status"):  # noqa: F811
    core = create_app().state.core
    first = payload()
    first["intent"]["mode"] = mode
    second = deepcopy(first)
    second["source"] = {"kind": "office", "key": "office:shipping-request:"+str(uuid4()), "revision": "1"}
    execution = await claim(session, core, exact, first["intent"])
    order_producer = PinnedProducer(exact, execution, [first])
    office_producer = PinnedProducer(exact, execution, [second])
    core.services.shipping_producer = ShippingProducerDispatcher(order=order_producer, office=office_producer)
    one = await receive(session, core.services, "order", first)
    two = await receive(session, core.services, "office", second)
    await session.commit()
    assert one.state == two.state == "resolved"
    assert (one.shipment_id, one.rfq_id) == (two.shipment_id, two.rfq_id)
    assert len(list(await session.scalars(select(CarrierRfq if mode == "contract" else Shipment)))) == 1
    terminal = {"status": "cancelled"} if terminal_field == "status" else {"reserve_status": "released"}
    await session.execute(update(DealDocument).where(DealDocument.id == 1).values(**terminal))
    await session.commit()
    order_producer.fulfillment_allowed = False
    office_producer.fulfillment_allowed = False
    replay = await receive(session, core.services, "order", {**first, "transport_attempt": 2})
    assert replay.id == one.id and not replay.observed_transition
    third = deepcopy(second)
    third["source"]["key"] = "office:shipping-request:"+str(uuid4())
    office_producer.hashes[("office", third["source"]["key"])] = canonical_shipping_payload(third)[1]
    with pytest.raises(HTTPException) as err:
        await receive(session, core.services, "office", third)
    assert err.value.status_code == 409
    await session.rollback()
    assert len(list(await session.scalars(select(ShipmentIntake)))) == 2


async def test_forged_embedded_hash_never_creates_delivery(session, api, exact):  # noqa: F811
    core = create_app().state.core
    original = payload()
    execution = await claim(session, core, exact, original["intent"])
    core.services.shipping_producer = PinnedProducer(exact, execution, [original])
    forged = deepcopy(original)
    forged["intent"]["cargo"] = "Different"
    forged["payload_sha256"] = canonical_shipping_payload(original)[1]
    with pytest.raises(HTTPException) as err:
        await receive(session, core.services, "order", forged)
    assert err.value.status_code == 409
    assert list(await session.scalars(select(Shipment))) == []


async def test_canonical_order_event_is_not_ignored_without_legacy_kind(session, api, exact):  # noqa: F811
    from types import SimpleNamespace

    core = create_app().state.core
    await events.on_document_posted(payload(), SimpleNamespace(session=session, services=core.services))
    row = (await session.scalars(select(ShipmentIntake))).one()
    assert row.state == "pending"


async def test_manual_resolve_rechecks_source_access_after_locks(session, api, exact):  # noqa: F811
    from core.services.auth import CurrentUser
    from modules.logistics.routes import resolve_intake

    core = create_app().state.core
    data = payload()
    pending = await receive(session, core.services, "order", data)
    pending_id = pending.id
    await session.commit()
    execution = await claim(session, core, exact, data["intent"])

    class RevokedProducer(PinnedProducer):
        calls = 0

        async def authorize_shipping_intake(self, session, **kwargs):
            self.calls += 1
            if self.calls == 3:
                raise HTTPException(403, "Assignment revoked while waiting")

    producer = RevokedProducer(exact, execution, [data])
    core.services.shipping_producer = producer
    with pytest.raises(HTTPException) as err:
        await resolve_intake(pending_id, session, core, CurrentUser("ship-tester", ["director"]))
    assert err.value.status_code == 403
    assert producer.calls == 3
    await session.rollback()
    assert list(await session.scalars(select(Shipment))) == []
    assert (await session.get(ShipmentIntake, pending_id)).state == "pending"


async def test_manual_resolve_rejects_snapshot_from_another_intake(session, api, exact):  # noqa: F811
    from core.services.auth import CurrentUser
    from modules.logistics.routes import resolve_intake

    core = create_app().state.core
    data = payload()
    pending = await receive(session, core.services, "order", data)
    pending_id = pending.id
    await session.commit()
    execution = await claim(session, core, exact, data["intent"])

    class AuthorizedProducer(PinnedProducer):
        async def authorize_shipping_intake(self, session, **kwargs):
            return None

    core.services.shipping_producer = AuthorizedProducer(exact, execution, [data])
    await session.execute(update(ShipmentIntake).where(ShipmentIntake.id == pending_id)
                          .values(source_key="sales:order:8"))
    await session.commit()
    with pytest.raises(HTTPException) as error:
        await resolve_intake(pending_id, session, core, CurrentUser("ship-tester", ["director"]))
    assert error.value.status_code == 409
    assert list(await session.scalars(select(Shipment))) == []
    rows = list(await session.scalars(select(ShipmentIntake)))
    assert len(rows) == 1 and rows[0].id == pending_id and rows[0].state == "pending"


@pytest.mark.parametrize("eligibility", [False, None, "true", 1])
async def test_source_eligibility_cannot_promote_pending(session, api, exact, eligibility):  # noqa: F811
    core = create_app().state.core
    original = payload()
    execution = await claim(session, core, exact, original["intent"])
    producer = PinnedProducer(exact, execution, [original])
    producer.fulfillment_allowed = eligibility
    core.services.shipping_producer = producer
    await session.commit()
    with pytest.raises(HTTPException) as denied:
        await receive(session, core.services, "order", original)
    assert denied.value.status_code == 409
    await session.rollback()
    assert list(await session.scalars(select(Shipment))) == []
    assert list(await session.scalars(select(ShipmentIntake))) == []
