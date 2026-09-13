# ruff: noqa: F811 -- imported pytest fixtures are injected by name
"""Bounded real PG schedules; no claim of general deadlock freedom or coverage."""
import hashlib
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select

from core.services.auth import CurrentUser
from modules.accounting.models import AccessGrant, Organization
from modules.logistics.canonical_intakes import receive
from modules.logistics.models import CarrierBid, CarrierRfqInvite, ShipmentJournal
from modules.logistics.shipment_writer import create
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.models import Deal, DealDocument
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.test_shipping_producer_concurrency_postgres import (
    bind,
    intent,
    interleave,
    isolated_target,  # noqa: F401
    prepare,
    producer_pg,  # noqa: F401
    revoke,
    state,
)

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def snapshot_pg(producer_pg):
    pg = producer_pg
    async with pg.factory() as session:
        conn = await session.connection()
        # Only these two pre-existing tables are missing from pg_factory's
        # baseline. Producer/fulfillment tables and guards use frozen proposal.
        await conn.run_sync(lambda sync: CarrierBid.__table__.create(sync, checkfirst=True))
        await conn.run_sync(lambda sync: CarrierRfqInvite.__table__.create(sync, checkfirst=True))
        await session.commit()
    return pg


async def snapshot(pg, session):
    result = await pg.core.services.logistics.invoice_fulfillment_snapshot(
        session, exact_invoice=pg.exact, user=pg.actor)
    assert result["coverage_complete"] is False
    assert "journal_generation" not in result
    return result


async def read_snapshot(pg):
    async with pg.factory() as session:
        result = await snapshot(pg, session)
        await session.commit()
        return result


async def bound_sources(pg, mode="spot"):
    envelopes = {kind: await prepare(pg, kind, intent(mode)) for kind in ("order", "office")}
    async with pg.factory() as session:
        for kind, envelope in envelopes.items():
            await bind(pg, session, kind, envelope)
        await session.commit()
    return envelopes


async def compete(pg, snapshot_first, operation, relation):
    async def snap(session):
        return await snapshot(pg, session)
    results, trace = await interleave(pg, snap if snapshot_first else operation, operation if snapshot_first else snap)
    assert [item["status"] for item in results] == [200, 200]
    assert relation in trace["blocked"]["query"]
    assert trace["holder"]["pid"] != trace["waiter"]["pid"]
    assert trace["holder"]["txid"] != trace["waiter"]["txid"]
    return results[0 if snapshot_first else 1]["result"]


@pytest.mark.parametrize("mode", ["spot", "contract"])
@pytest.mark.parametrize("snapshot_first", [True, False])
async def test_pg_snapshot_receive(snapshot_pg, mode, snapshot_first):
    pg = snapshot_pg
    envelopes = await bound_sources(pg, mode)
    before = await read_snapshot(pg)
    assert len(before["producer_sources"]["sources"]) == 2 and not before["intakes"]

    async def consume(session):
        row = await receive(session, pg.core.services, "order", envelopes["order"]["payload"])
        return {"id": row.id, "state": row.state}

    observed = await compete(pg, snapshot_first, consume, "accounting.organization")
    after = await read_snapshot(pg)
    assert len(after["intakes"]) == 1 and after["intakes"][0]["row"]["state"] == "resolved"
    assert len(after["rfqs" if mode == "contract" else "shipments"]) == 1
    assert len(after["executions"]) == 1
    assert before["sha256"] != after["sha256"]
    assert observed == (before if snapshot_first else after)
    pg.evidence.update(before_sha256=before["sha256"], after_sha256=after["sha256"], target_mode=mode)


@pytest.mark.parametrize("kind", ["order", "office"])
@pytest.mark.parametrize("snapshot_first", [True, False])
async def test_pg_snapshot_association(snapshot_pg, kind, snapshot_first):
    pg = snapshot_pg
    envelope = await prepare(pg, kind)
    before = await read_snapshot(pg)
    observed = await compete(pg, snapshot_first, lambda session: bind(pg, session, kind, envelope), "accounting.organization")
    after = await read_snapshot(pg)
    assert not before["producer_sources"]["sources"]
    assert len(after["producer_sources"]["sources"]) == 1 and len(after["executions"]) == 1
    assert after["producer_sources"]["sources"][0]["source"]["kind"] == kind
    assert not after["intakes"]
    assert observed == (before if snapshot_first else after)
    assert before["sha256"] != after["sha256"]
    pg.evidence.update(before_sha256=before["sha256"], after_sha256=after["sha256"])


@pytest.mark.parametrize("snapshot_first", [True, False])
async def test_pg_snapshot_revoke(snapshot_pg, snapshot_first):
    pg = snapshot_pg
    await bound_sources(pg)
    before = await read_snapshot(pg)
    observed = await compete(pg, snapshot_first, lambda session: revoke(pg, session), "office.office_doc")
    after = await read_snapshot(pg)
    old = next(s for s in before["producer_sources"]["sources"] if s["source"]["kind"] == "office")
    new = next(s for s in after["producer_sources"]["sources"] if s["source"]["kind"] == "office")
    assert old["fulfillment_allowed"] is True and new["fulfillment_allowed"] is False
    assert old["source_state_sha256"] != new["source_state_sha256"]
    for key in ("envelope", "association", "execution_id", "intent_digest"):
        assert old[key] == new[key]
    assert observed == (before if snapshot_first else after)
    assert before["sha256"] != after["sha256"]
    pg.evidence.update(before_sha256=before["sha256"], after_sha256=after["sha256"])


@pytest.mark.parametrize("snapshot_first", [True, False])
async def test_pg_snapshot_foreign_writer(snapshot_pg, snapshot_first):
    pg = snapshot_pg
    await bound_sources(pg)
    foreign_actor = CurrentUser("pg-foreign", ["director"])
    original = "<p>Foreign original</p>"
    hashed = hashlib.sha256(original.encode()).hexdigest()
    foreign_exact = dict(organization_id=2, document_id=2, expected_version=1, expected_content_sha256=hashed)
    async with pg.factory() as session:
        session.add_all([Organization(id=2, name="Foreign", unp="999999972"),
            Deal(id=2, number="PG-D2", title="Foreign", counterparty="Foreign")])
        await session.flush()
        session.add_all([AccessGrant(organization_id=2, subject=foreign_actor.username, role="chief"),
            DealOwnership(deal_id=2, organization_id=2, snapshot={}, evidence="Synthetic", actor=foreign_actor.username),
            DealDocument(id=2, deal_id=2, number="PG-I2", kind="invoice", version=1, status="paid", reserve_status="reserved",
                amount=100, original_html=original, content_sha256=hashed, issued_at=datetime(2026, 9, 10),
                snapshot_json={"items": [{"sku_code": "A", "qty": "2"}]})])
        await session.commit()
    before = await read_snapshot(pg)
    async with pg.factory() as session:
        generation = await session.scalar(select(ShipmentJournal.generation))

    async def foreign_writer(session):
        row = await create(session, pg.core, foreign_exact, "foreign-snapshot", {"customer": "Foreign"}, foreign_actor)
        return {"id": row.id, "organization_id": row.organization_id}

    observed = await compete(pg, snapshot_first, foreign_writer, "logistics.shipment_journal")
    after = await read_snapshot(pg)
    assert observed == before == after
    async with pg.factory() as session:
        new_generation = await session.scalar(select(ShipmentJournal.generation))
    assert new_generation > generation
    pg.evidence.update(before_sha256=before["sha256"], after_sha256=after["sha256"],
        generation_before=generation, generation_after=new_generation)


async def test_pg_snapshot_public_bid(snapshot_pg):
    pg = snapshot_pg
    envelopes = await bound_sources(pg, "contract")
    async with pg.factory() as session:
        intake = await receive(session, pg.core.services, "order", envelopes["order"]["payload"])
        session.add(CarrierRfqInvite(rfq_id=intake.rfq_id, carrier_code="dpd", token="pg-snapshot-secret", detail="private-link"))
        await session.commit()
        generation = await session.scalar(select(ShipmentJournal.generation))
    before = await read_snapshot(pg)
    response = await pg.api.post("/logistics/rfqs/bid/pg-snapshot-secret", json={"price": 50, "eta_days": 1})
    assert response.status_code == 201, response.text
    after = await read_snapshot(pg)
    async with pg.factory() as session:
        assert await session.scalar(select(ShipmentJournal.generation)) == generation
    assert before["sha256"] != after["sha256"] and len(after["bids"]) == 1
    assert after["invites"][0]["row"]["status"] == "responded"
    assert "token" not in after["invites"][0]["row"] and "detail" not in after["invites"][0]["row"]
    pg.evidence.update(before_sha256=before["sha256"], after_sha256=after["sha256"], generation_unchanged=True)


async def test_pg_snapshot_empty_caller_rollback(snapshot_pg):
    pg = snapshot_pg
    before = await state(pg)
    async with pg.factory() as session:
        assert await session.get(ShipmentJournal, 1) is None
        result = await snapshot(pg, session)
        assert await session.get(ShipmentJournal, 1) is not None
        assert not result["producer_sources"]["sources"]
        assert all(not result[key] for key in ("shipments", "rfqs", "bids", "invites", "executions", "intakes"))
        await session.rollback()
    assert await state(pg) == before
    async with pg.factory() as session:
        assert await session.get(ShipmentJournal, 1) is None
    pg.evidence["snapshot_rollback_business_unchanged"] = True
