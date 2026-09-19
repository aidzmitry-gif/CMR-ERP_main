"""Contact replay and primary selection under real independent transactions."""
import asyncio
from uuid import uuid4

from sqlalchemy import func, select

from core.domain.models import Contact, User
from modules.sales.models import CrmClientContact


async def test_concurrent_contact_replay_and_primary_selection(pg_app):
    factory = pg_app._transport.app.state.core.services.db.session_factory
    key = uuid4().hex
    async with factory() as session:
        owner = User(username=f'contact-{key}', full_name='Synthetic owner', employee_id=int(key[:7], 16) + 1000000,
                     department='Продажи', role='sales', status='active', deal_visibility='own')
        session.add(owner)
        await session.commit()
    headers = {'X-User':owner.username, 'X-User-Roles':'sales'}
    created = await pg_app.post('/sales/clients', headers=headers, json={'name':key, 'request_key':key})
    assert created.status_code == 201, created.text
    client_id = created.json()['id']
    path = f'/sales/clients/{client_id}/contacts'
    data = {'full_name':'First', 'is_primary':True, 'request_key':key}
    repeated = await asyncio.gather(*[pg_app.post(path, headers=headers, json=data) for _ in range(2)])
    assert [r.status_code for r in repeated] == [201, 201], [r.text for r in repeated]
    assert repeated[0].json()['id'] == repeated[1].json()['id']
    results = await asyncio.gather(*[pg_app.post(path, headers=headers, json={
        'full_name':name, 'is_primary':True, 'request_key':uuid4().hex,
    }) for name in ['Second', 'Third']])
    assert all(r.status_code == 201 for r in results), [r.text for r in results]
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(CrmClientContact).where(
            CrmClientContact.crm_client_id == client_id, CrmClientContact.is_primary.is_(True))) == 1
        assert await session.scalar(select(func.count()).select_from(CrmClientContact).where(
            CrmClientContact.crm_client_id == client_id)) == 3
        assert await session.scalar(select(func.count()).select_from(Contact).where(Contact.full_name.in_(['First','Second','Third']))) == 0
