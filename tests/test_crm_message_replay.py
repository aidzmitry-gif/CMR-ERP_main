"""Lost response retries preserve one history row and one outbox event."""
from sqlalchemy import func, select

from core.domain.models import OutboxEvent
from modules.sales.models import Message
from tests.test_crm_client_contacts import FOREIGN, OWN, setup_client


async def test_history_replay_conflict_and_foreign_scope(api, session):
    client_id = await setup_client(api, session)
    deal = (await api.post('/sales/deals', headers=OWN, json={
        'number':'REPLAY-HISTORY','title':'Replay','counterparty':'ignored','crm_client_id':client_id})).json()
    path = f"/sales/deals/{deal['id']}/messages"
    data = {'channel':'phone','text':'Confirmed next step','author':'Manager','request_key':'history-001'}
    first = await api.post(path, headers=OWN, json=data)
    assert first.status_code == 201, first.text
    assert (await api.post(path, headers=OWN, json=data)).json() == first.json()
    assert (await api.post(path, headers=OWN, json={**data,'text':'Changed'})).status_code == 409
    assert (await api.post(path, headers=FOREIGN, json=data)).status_code == 404
    assert (await api.get(path, headers=FOREIGN)).status_code == 404
    assert (await api.post(path, headers=OWN, json={**data,'request_key':'bad'})).status_code == 422
    assert (await api.get(path, headers=OWN)).json() == [first.json()]
    assert await session.scalar(select(func.count()).select_from(Message)) == 1
    assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
        OutboxEvent.event_type == 'sales.message.sent')) == 1
    distinct = await api.post(path, headers=OWN, json={**data,'request_key':'history-002'})
    assert distinct.status_code == 201 and distinct.json()['id'] != first.json()['id']


async def test_legacy_history_without_key_remains_distinct(api, session):
    client_id = await setup_client(api, session)
    deal = (await api.post('/sales/deals', headers=OWN, json={
        'number':'LEGACY-HISTORY','title':'Legacy','counterparty':'ignored','crm_client_id':client_id})).json()
    path = f"/sales/deals/{deal['id']}/messages"
    a = await api.post(path, headers=OWN, json={'text':'Legacy entry'})
    b = await api.post(path, headers=OWN, json={'text':'Legacy entry'})
    assert a.status_code == b.status_code == 201
    assert a.json()['id'] != b.json()['id']
