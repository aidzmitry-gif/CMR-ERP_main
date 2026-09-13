"""Actual PostgreSQL uniqueness serializes independent client creation requests."""
import asyncio
from uuid import uuid4

from sqlalchemy import func, select, text

from core.domain.models import Counterparty, User
from modules.sales.models import CrmClient


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
