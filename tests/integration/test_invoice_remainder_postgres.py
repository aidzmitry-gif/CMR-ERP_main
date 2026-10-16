import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from modules.wms.invoice_remainder import RemainderRelease
from modules.wms.invoice_reservations import invoice_availability
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.integration.test_invoice_physical_shipments_postgres import physical_pg  # noqa: F401
from tests.test_invoice_physical_shipments import endpoint, request
from tests.test_invoice_remainder import partial, release_request, release_url

pytestmark = pytest.mark.integration


async def test_release_waits_for_actual_organization_lock(physical_pg):  # noqa: F811
    from modules.accounting.gateway import AccountingService
    api, factory, org, facts = physical_pg
    await partial(api, org, facts, '1')
    body = await release_request(api, org, facts)
    async with factory() as blocker:
        await AccountingService().lock_event_organization(blocker, org)
        pid = await blocker.scalar(text('SELECT pg_backend_pid()'))
        pending = asyncio.create_task(api.post(release_url(org), json=body))
        try:
            for _ in range(100):
                async with factory() as observer:
                    waiting = await observer.scalar(text('SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE :pid=ANY(pg_blocking_pids(pid)))'), {'pid': pid})
                if waiting:
                    break
                await asyncio.sleep(.02)
            assert waiting, 'Expected observable PostgreSQL lock contention'
            await blocker.rollback()
            response = await pending
            assert response.status_code == 201, response.text
        finally:
            await blocker.rollback()
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)


async def test_same_key_concurrent_replay_and_immutable_package(physical_pg):  # noqa: F811
    api, factory, org, facts = physical_pg
    await partial(api, org, facts, '1')
    body = await release_request(api, org, facts)
    responses = await asyncio.gather(*[api.post(release_url(org), json=body) for _ in range(2)])
    assert [r.status_code for r in responses] == [201, 201], [r.text for r in responses]
    assert responses[0].json() == responses[1].json()
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(RemainderRelease)) == 1
        row = (await invoice_availability(session, org, ['A']))['rows'][0]
        assert (row['physical'], row['reserved'], row['free']) == ('9.00', '0.00', '9.00')
    for statement in [
        "UPDATE wms.invoice_remainder_release SET actor='forged'",
        "DELETE FROM wms.invoice_remainder_release",
        "TRUNCATE wms.invoice_remainder_release CASCADE",
        "UPDATE wms.invoice_remainder_release_line SET qty=1",
        "DELETE FROM wms.invoice_remainder_release_line",
        "TRUNCATE wms.invoice_remainder_release_line",
        "UPDATE wms.reservation_version SET qty=100",
        "INSERT INTO wms.reservation_version(organization_id,source,version,sku_code,warehouse,qty,evidence,actor) SELECT organization_id,source,99,sku_code,warehouse,1,'fake','fake' FROM wms.reservation_version LIMIT 1",
    ]:
        async with factory() as session:
            with pytest.raises(DBAPIError):
                await session.execute(text(statement))
                await session.commit()
            await session.rollback()


async def test_different_release_keys_and_shipment_race(physical_pg):  # noqa: F811
    api, factory, org, facts = physical_pg
    await partial(api, org, facts, '1')
    release = await release_request(api, org, facts)
    shipment = await request(api, org, facts, [{"line_no": 1, "warehouse": "W", "qty": "1"}])
    results = await asyncio.gather(api.post(release_url(org), json=release), api.post(endpoint(org), json=shipment))
    assert sorted(r.status_code for r in results) == [201, 409], [r.text for r in results]
    if results[0].status_code == 409:
        release = await release_request(api, org, facts)
        results = await asyncio.gather(api.post(release_url(org), json=release),
                                      api.post(release_url(org), json={**release, 'source_key': str(uuid4())}))
        assert sorted(r.status_code for r in results) == [201, 409], [r.text for r in results]
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(RemainderRelease)) == 1
        assert (await invoice_availability(session, org, ['A']))['rows'][0]['reserved'] == '0.00'


async def test_sql_unlinked_reduction_rolls_back(physical_pg):  # noqa: F811
    api, factory, org, facts = physical_pg
    await partial(api, org, facts, '1')
    async with factory() as session:
        with pytest.raises(DBAPIError):
            await session.execute(text("""INSERT INTO wms.reservation_version
                (organization_id,source,version,sku_code,warehouse,qty,evidence,actor)
                SELECT organization_id,source,version+1,sku_code,warehouse,0,'fake','fake'
                FROM wms.reservation_version WHERE version=2 LIMIT 1"""))
            await session.commit()
        await session.rollback()
        from modules.accounting.gateway import AccountingService
        await AccountingService().lock_event_organization(session, org)
        assert (await invoice_availability(session, org, ['A']))['rows'][0]['reserved'] == '4.00'
