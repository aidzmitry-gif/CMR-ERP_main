"""Fresh database acceptance; reuse the project's pg_factory lifecycle."""
import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from core.runtime.app import create_app
from core.runtime.deps import get_session
from modules.accounting.gateway import AccountingService
from modules.wms.invoice_shipments import PhysicalShipmentAct, PhysicalShipmentLine
from modules.wms.reservation_events import ReservationEventState, ReservationPick
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.test_invoice_physical_shipments import counts, endpoint, prepared, request


@pytest_asyncio.fixture
async def physical_pg(pg_factory):  # noqa: F811
    factory = pg_factory
    async with factory() as session:
        conn = await session.connection()
        tables = [ReservationEventState.__table__, ReservationPick.__table__, PhysicalShipmentAct.__table__, PhysicalShipmentLine.__table__]
        await conn.run_sync(lambda c: PhysicalShipmentAct.metadata.create_all(c, tables=tables, checkfirst=True))
        # Physical tables and guards are installed by the frozen proposal.
        await session.commit()
    app = create_app()
    app.state.core.services.db.session_factory = factory
    async def sessions():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_session] = sessions
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           headers={"X-User": "allocator", "X-User-Roles": "director"}) as api:
        async with factory() as session:
            org, facts = await prepared(api, session)
        yield api, factory, org, facts


async def test_pg_partial_replay_concurrent_and_sql_guards(physical_pg):
    api, factory, org, facts = physical_pg
    body = await request(api, org, facts)
    results = await asyncio.gather(api.post(endpoint(org), json=body), api.post(endpoint(org), json=body), return_exceptions=True)
    assert not any(isinstance(r, BaseException) for r in results), results
    assert [r.status_code for r in results] == [201, 201], [r.text for r in results]
    assert results[0].json() == results[1].json()
    body2 = await request(api, org, facts, [{"line_no": 1, "warehouse": "W", "qty": "1.00"},
                                          {"line_no": 2, "warehouse": "W", "qty": "3.00"}])
    response = await api.post(endpoint(org), json=body2)
    assert response.status_code == 201, response.text
    assert (await api.post(endpoint(org), json=body)).json() == results[0].json()
    async with factory() as session:
        assert await counts(session) == [2, 3, 5, 4]
    for statement in [
        "UPDATE wms.physical_shipment_act SET actor='forged'",
        "DELETE FROM wms.physical_shipment_act",
        "TRUNCATE wms.physical_shipment_act CASCADE",
        "UPDATE wms.physical_shipment_line SET qty=0.01",
        "DELETE FROM wms.physical_shipment_line",
        "TRUNCATE wms.physical_shipment_line",
        "UPDATE wms.stock_movement SET qty=9 WHERE kind='out'",
        "DELETE FROM wms.stock_movement WHERE kind='out'",
        "TRUNCATE wms.stock_movement CASCADE",
        "UPDATE wms.reservation_version SET qty=1",
        "INSERT INTO wms.reservation_version(organization_id,source,version,sku_code,warehouse,qty,evidence,actor) SELECT organization_id,source,99,sku_code,warehouse,0,'fake','fake' FROM wms.reservation_version LIMIT 1",
    ]:
        async with factory() as session:
            with pytest.raises(DBAPIError):
                await session.execute(text(statement))
                await session.commit()
            await session.rollback()


async def test_pg_fulfillment_snapshot_tracks_partial_act_and_stable_facts(physical_pg):
    from core.services.auth import CurrentUser
    from modules.sales.reservation_source import SalesReservationSource
    from modules.wms.reservation_gateway import WmsReservationService

    api, factory, org, facts = physical_pg
    async def snapshot():
        async with factory() as session:
            await AccountingService().source_member(session, org, CurrentUser("allocator", ["director"]))
            current = await SalesReservationSource().invoice_reservation(session, 1)
            return await WmsReservationService().invoice_fulfillment_snapshot(session, org, current)

    before = await snapshot()
    assert before["observed_state"] == "no_shipment"
    assert before["coverage_complete"] is False
    body = await request(api, org, facts)
    response = await api.post(endpoint(org), json=body)
    assert response.status_code == 201, response.text
    after = await snapshot()
    assert after["observed_state"] == "shipped" and after["coverage_complete"] is False
    assert after["digest"] != before["digest"]
    assert len(after["snapshot"]["acts"]) == len(after["snapshot"]["movements"]) == 1
    assert await snapshot() == after


async def test_pg_waits_on_org_lock_and_rechecks_remaining(physical_pg):
    api, factory, org, facts = physical_pg
    body = await request(api, org, facts)
    async with factory() as blocker:
        await AccountingService().lock_event_organization(blocker, org)
        pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
        pending = asyncio.create_task(api.post(endpoint(org), json=body))
        try:
            blocked = False
            for _ in range(100):
                async with factory() as observer:
                    blocked = await observer.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE :pid=ANY(pg_blocking_pids(pid)))"), {"pid": pid})
                if blocked:
                    break
                await asyncio.sleep(.02)
            assert blocked, "Must observe actual PostgreSQL lock contention"
            await blocker.rollback()
            result = await pending
            assert result.status_code == 201, result.text
        finally:
            await blocker.rollback()
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)


async def test_pg_rollback_after_stock_before_act(physical_pg, monkeypatch):
    import modules.wms.invoice_shipments as shipment
    api, factory, org, facts = physical_pg
    body = await request(api, org, facts)
    original = shipment.act_result
    async def fail(*args):
        raise RuntimeError("Synthetic after all inserts")
    monkeypatch.setattr(shipment, "act_result", fail)
    with pytest.raises(RuntimeError, match="Synthetic"):
        await api.post(endpoint(org), json=body)
    monkeypatch.setattr(shipment, "act_result", original)
    async with factory() as session:
        assert await counts(session) == [0, 0, 2, 1]


async def test_pg_competing_keys_cannot_double_consume(physical_pg):
    from uuid import uuid4
    api, factory, org, facts = physical_pg
    first = await request(api, org, facts, [{"line_no": 1, "warehouse": "W", "qty": "2.00"}])
    second = {**first, "source_key": str(uuid4())}
    responses = await asyncio.gather(api.post(endpoint(org), json=first), api.post(endpoint(org), json=second))
    assert sorted(r.status_code for r in responses) == [201, 409]
    async with factory() as session:
        assert await counts(session) == [1, 1, 3, 2]


async def test_pg_close_and_no_shipment_preview_share_org_lock(physical_pg):
    from fastapi import HTTPException

    from core.services.auth import CurrentUser
    from modules.sales.reservation_source import SalesReservationSource
    from modules.wms.invoice_reservations import release_preview

    api, factory, org, facts = physical_pg
    body = await request(api, org, facts)
    assert (await api.post(endpoint(org), json=body)).status_code == 201
    async with factory() as session:
        await AccountingService().source_member(session, org, CurrentUser("allocator", ["director"]))
        current = await SalesReservationSource().invoice_reservation(session, 1)
        with pytest.raises(HTTPException, match="physical_act_excludes"):
            await release_preview(session, org, current)
        await session.rollback()
        await session.execute(text("UPDATE accounting.period SET closed=true WHERE organization_id=:org"), {"org": org})
        await session.commit()
    assert (await api.post(endpoint(org), json=body)).status_code == 201
    next_body = await request(api, org, facts)
    assert (await api.post(endpoint(org), json=next_body)).status_code == 409


async def test_pg_raw_partial_package_rejected(physical_pg):
    api, factory, org, facts = physical_pg
    body = await request(api, org, facts)
    assert (await api.post(endpoint(org), json=body)).status_code == 201
    async with factory() as session:
        with pytest.raises(DBAPIError):
            await session.execute(text("""INSERT INTO wms.physical_shipment_act
                (organization_id,document_id,document_version,content_sha256,reservation_digest,source_key,request_hash,operation_date,actor,snapshot,digest)
                SELECT organization_id,document_id,document_version,content_sha256,reservation_digest,'forged',request_hash,operation_date,actor,snapshot,digest
                FROM wms.physical_shipment_act LIMIT 1"""))
            await session.commit()
        await session.rollback()
        assert await counts(session) == [1, 1, 3, 2]


async def test_pg_pending_shipment_serializes_no_shipment_decision(physical_pg):
    from fastapi import HTTPException

    from core.services.auth import CurrentUser
    from modules.sales.reservation_source import SalesReservationSource
    from modules.wms.invoice_reservations import release_preview
    from modules.wms.invoice_shipments import ShipmentInput, create

    api, factory, org, facts = physical_pg
    body = await request(api, org, facts)
    user = CurrentUser("allocator", ["director"])
    async def cancellation_boundary():
        async with factory() as session:
            await AccountingService().source_member(session, org, user)
            current = await SalesReservationSource().invoice_reservation(session, 1)
            with pytest.raises(HTTPException, match="physical_act_excludes"):
                await release_preview(session, org, current)
    async with factory() as writer:
        accounting = AccountingService()
        actor = await accounting.source_member(writer, org, user)
        current = await SalesReservationSource().invoice_shipping_source(writer, 1, organization_id=org,
            expected_version=facts["version"], expected_content_sha256=facts["content_sha256"])
        await accounting.source_changed(writer, org, user, f"wms:physical-shipment:{org}:{body['source_key']}", 1, body["operation_date"])
        await create(writer, org, current, ShipmentInput.model_validate(body), actor)
        pid = await writer.scalar(text("SELECT pg_backend_pid()"))
        pending = asyncio.create_task(cancellation_boundary())
        try:
            blocked = False
            for _ in range(100):
                async with factory() as observer:
                    blocked = await observer.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE :pid=ANY(pg_blocking_pids(pid)))"), {"pid": pid})
                if blocked:
                    break
                await asyncio.sleep(.02)
            assert blocked
            await writer.commit()
            await pending
        finally:
            await writer.rollback()
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
