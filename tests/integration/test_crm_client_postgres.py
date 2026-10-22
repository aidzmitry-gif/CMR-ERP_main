"""Actual PostgreSQL uniqueness serializes independent client creation requests."""
import asyncio
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text

from core.domain.models import Counterparty, User
from core.runtime.app import create_app
from core.runtime.deps import get_session
from modules.sales.models import CrmClient, Deal
from tests.accounting.test_postgres import pg_factory as pg_factory  # noqa: F401


@pytest_asyncio.fixture
async def registered_api(pg_factory):  # noqa: F811
    app = create_app()
    app.state.core.services.db.session_factory = pg_factory

    async def sessions():
        async with pg_factory() as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://isolated-test",
        headers={"X-User": "issuer", "X-User-Roles": "director"},
    ) as api:
        yield api, pg_factory


async def test_concurrent_replay_and_duplicate_are_atomic(pg_app):
    factory = pg_app._transport.app.state.core.services.db.session_factory
    key = uuid4().hex
    async with factory() as session:
        owner = User(username=f'client-{key}', full_name=f'Owner {key}', employee_id=int(key[:7], 16) + 1000000,
                     department='Продажи', role='sales', status='active', deal_visibility='own')
        session.add(owner)
        await session.commit()
    headers = {'X-User':owner.username, 'X-User-Roles':'sales'}
    data = {'name':f'Client {key}', 'request_key':key}
    first, repeated = await asyncio.gather(*[
        pg_app.post('/sales/clients', headers=headers, json=data) for _ in range(2)
    ])
    assert first.status_code == repeated.status_code == 201, (first.text, repeated.text)
    assert first.json()['id'] == repeated.json()['id']
    second_data = {'name':f'Duplicate {key}', 'request_key':uuid4().hex}
    responses = await asyncio.gather(
        pg_app.post('/sales/clients', headers=headers, json=second_data),
        pg_app.post('/sales/clients', headers=headers, json={**second_data, 'request_key':uuid4().hex}),
    )
    assert sorted(response.status_code for response in responses) == [201, 409]
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(CrmClient).where(CrmClient.owner_id == owner.employee_id)) == 2
        assert await session.scalar(select(func.count()).select_from(Counterparty).where(Counterparty.name == data['name'])) == 0


async def test_deactivation_lock_prevents_creation_for_inactive_owner(pg_app):
    factory = pg_app._transport.app.state.core.services.db.session_factory
    key = uuid4().hex
    async with factory() as setup:
        owner = User(username=f'client-{key}', full_name=f'Owner {key}', employee_id=int(key[:7], 16) + 1000000,
                     department='Продажи', role='sales', status='active', deal_visibility='own')
        setup.add(owner)
        await setup.commit()
    headers = {'X-User':owner.username, 'X-User-Roles':'sales'}
    async with factory() as blocker:
        locked = await blocker.scalar(select(User).where(User.id == owner.id).with_for_update())
        locked.status = 'inactive'
        await blocker.flush()
        request = asyncio.create_task(pg_app.post('/sales/clients', headers=headers,
            json={'name':f'Blocked {key}', 'request_key':key}))
        try:
            async def wait_until_blocked():
                async with factory() as observer:
                    while not await observer.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE '%app_user%'")):
                        await observer.commit()  # Refresh PostgreSQL's cached statistics snapshot.
                        await asyncio.sleep(0.02)
            await asyncio.wait_for(wait_until_blocked(), timeout=10)
            await blocker.commit()
        except BaseException:
            await blocker.rollback()
            await asyncio.wait_for(request, timeout=10)
            raise
        response = await asyncio.wait_for(request, timeout=10)
        assert response.status_code == 422, response.text
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(CrmClient).where(CrmClient.owner_id == owner.employee_id)) == 0


async def registered_first_buyer(api, factory):
    key = uuid4().hex
    async with factory() as session:
        owner = User(username=f"first-buyer-{key}", full_name="Synthetic seller",
                     employee_id=int(key[:7], 16) + 1000000, department="Продажи", role="sales",
                     status="active", deal_visibility="own")
        buyers = [Counterparty(name=f"First buyer {key} {index}") for index in range(2)]
        session.add_all([owner, *buyers])
        await session.commit()
        headers = {"X-User": owner.username, "X-User-Roles": "sales"}
        buyer_ids = [buyer.id for buyer in buyers]
    created = await api.post("/sales/clients", headers=headers,
                             json={"name": f"Working client {key}", "request_key": key})
    assert created.status_code == 201, created.text
    return headers, created.json(), buyer_ids, key


@pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)
async def test_registered_concurrent_first_buyer_bindings_are_serialized(registered_api):
    api, factory = registered_api
    headers, client, buyer_ids, key = await registered_first_buyer(api, factory)
    async with factory() as blocker:
        await blocker.scalar(select(CrmClient).where(CrmClient.id == client["id"]).with_for_update())
        blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
        requests = [asyncio.create_task(api.post("/sales/deals", headers=headers, json={
            "number": f"FIRST-{key}-{index}", "title": "Concurrent first selection",
            "counterparty": client["name"], "crm_client_id": client["id"], "counterparty_id": buyer_id,
        })) for index, buyer_id in enumerate(buyer_ids)]
        try:
            async def wait_for_lock():
                async with factory() as observer:
                    while (await observer.scalar(text(
                        "SELECT count(DISTINCT pid) FROM pg_stat_activity WHERE datname=current_database() "
                        "AND pid<>pg_backend_pid() AND pid<>:blocker_pid AND wait_event_type='Lock' "
                        "AND (query LIKE '%crm_client%' OR query LIKE '%app_user%')"
                    ), {"blocker_pid": blocker_pid})) < 2:
                        await observer.commit()
                        await asyncio.sleep(0.02)
            await asyncio.wait_for(wait_for_lock(), timeout=8)
            assert not any(request.done() for request in requests)
            await blocker.commit()
            responses = await asyncio.wait_for(asyncio.gather(*requests), timeout=15)
        except BaseException:
            await blocker.rollback()
            await asyncio.wait_for(asyncio.gather(*requests), timeout=15)
            raise
    assert sorted(response.status_code for response in responses) == [201, 422], [r.text for r in responses]
    winner = next(response.json() for response in responses if response.status_code == 201)
    async with factory() as session:
        saved = await session.get(CrmClient, client["id"])
        assert saved.counterparty_id == winner["counterparty_id"] in buyer_ids
        assert saved.name == client["name"]
        assert await session.scalar(select(func.count()).select_from(Deal).where(Deal.crm_client_id == client["id"])) == 1


@pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)
async def test_registered_first_buyer_fk_rolls_back_with_duplicate_deal(registered_api):
    api, factory = registered_api
    headers, client, buyer_ids, key = await registered_first_buyer(api, factory)
    number = f"DUPLICATE-{key}"
    async with factory() as session:
        session.add(Deal(number=number, title="Existing deal", counterparty="Other buyer"))
        await session.commit()
    response = await api.post("/sales/deals", headers=headers, json={
        "number": number, "title": "Atomic failure", "counterparty": client["name"],
        "crm_client_id": client["id"], "counterparty_id": buyer_ids[0],
    })
    assert response.status_code == 409, response.text
    async with factory() as session:
        saved = await session.get(CrmClient, client["id"])
        assert saved.counterparty_id is None and saved.name == client["name"]
        assert await session.scalar(select(func.count()).select_from(Deal).where(Deal.crm_client_id == client["id"])) == 0
        assert await session.scalar(select(func.count()).select_from(Deal).where(Deal.number == number)) == 1
