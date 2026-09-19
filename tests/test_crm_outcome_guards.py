"""Standalone own deal closure must use canonical audited transitions."""
import pytest
from sqlalchemy import select

from core.domain.models import OutboxEvent
from modules.sales.models import LossReason, Stage
from tests.test_crm_client_contacts import FOREIGN, OWN, setup_client


@pytest.mark.parametrize('stage', ['won', 'lost', 'rp_won', 'missing'])
async def test_standalone_creation_rejects_terminal_or_foreign_stage(api, session, stage):
    client_id=await setup_client(api,session)
    response=await api.post('/sales/deals',headers=OWN,json={
        'number':'GUARD-CREATE','title':'Synthetic','counterparty':'ignored',
        'crm_client_id':client_id,'stage':stage})
    assert response.status_code==422,response.text


async def test_own_close_reopen_requires_canonical_route_and_preserves_deadlines(api, session):
    client_id=await setup_client(api,session)
    created=await api.post('/sales/deals',headers=OWN,json={
        'number':'OUTCOME-OWN','title':'Synthetic','counterparty':'ignored',
        'crm_client_id':client_id,'next_step':'Follow up','next_step_at':'2026-09-15T07:00:00',
        'ship_deadline':'2026-09-20','expected_close_date':'2026-09-18'})
    assert created.status_code==201,created.text
    deal=created.json()
    path=f"/sales/deals/{deal['id']}"
    initial_detail = (await api.get(path, headers=OWN)).json()
    for patch in [{'stage':'won'},{'stage':'lost'},{'closed_date':'01.01.2000'}]:
        denied=await api.patch(path,headers=OWN,json=patch)
        assert denied.status_code==422,denied.text
        assert (await api.get(path,headers=OWN)).json()==initial_detail
    for suffix in ['win','lose']:
        response=await api.post(path+'/'+suffix,headers=FOREIGN,json={'reason_code':'price'})
        assert response.status_code==404
    assert (await api.post(path+'/lose',headers=OWN,json={'reason_code':''})).status_code==422
    won=await api.post(path+'/win',headers=OWN)
    assert won.status_code==200,won.text
    assert won.json()['stage']=='won' and won.json()['closed_date']
    assert (await api.post(path+'/win',headers=OWN)).status_code==409
    assert (await api.patch(path,headers=OWN,json={'stage':'qual','closed_date':'01.01.2000'})).status_code==422
    reopened=await api.patch(path,headers=OWN,json={'stage':'qual'})
    assert reopened.status_code==200 and reopened.json()['closed_date'] is None
    lost=await api.post(path+'/lose',headers=OWN,json={'reason_code':'price','comment':'Synthetic reason'})
    assert lost.status_code==200,lost.text
    assert lost.json()['stage']=='lost' and lost.json()['lost_reason_code']=='price'
    assert lost.json()['lost_comment']=='Synthetic reason' and lost.json()['closed_date']
    assert (await api.post(path+'/lose',headers=OWN,json={'reason_code':'price'})).status_code==409
    for field in ['next_step','next_step_at','ship_deadline','expected_close_date']:
        assert lost.json()[field]==deal[field]
    history=(await api.get(path+'/history',headers=OWN)).json()
    assert [row['to_stage'] for row in history][-3:]==['won','qual','lost']
    events=(await session.scalars(select(OutboxEvent).where(
        OutboxEvent.event_type.in_(['sales.deal.won','sales.deal.lost'])))).all()
    assert len([row for row in events if row.payload.get('deal_id')==deal['id']])==2


async def test_numeric_director_and_unlinked_own_cannot_bypass_closure(api,session):
    client_id=await setup_client(api,session)
    base={'number':'DIRECTOR-NUMERIC','title':'Synthetic','counterparty':'ignored',
          'crm_client_id':client_id,'owner_id':651,'stage':'won'}
    assert (await api.post('/sales/deals',json=base)).status_code==422
    response=await api.post('/sales/deals',json={**base,'stage':'new'})
    assert response.status_code==201,response.text
    assert (await api.patch(f"/sales/deals/{response.json()['id']}",json={'stage':'lost'})).status_code==422
    unlinked={'number':'OWN-UNLINKED','title':'Synthetic','counterparty':'Legacy','stage':'won'}
    assert (await api.post('/sales/deals',headers=OWN,json=unlinked)).status_code==422
    assert (await api.post('/sales/deals',headers=OWN,json={**unlinked,'stage':'cond_lost'})).status_code==201


async def test_disabled_terminal_stage_cannot_be_invented_by_closure(api,session):
    client_id=await setup_client(api,session)
    response=await api.post('/sales/deals',headers=OWN,json={
        'number':'DISABLED-TERMINAL','title':'Synthetic','counterparty':'ignored','crm_client_id':client_id})
    assert response.status_code==201
    path=f"/sales/deals/{response.json()['id']}"
    session.add(Stage(code='new',title='Disabled',kind='normal',funnel='new_clients',is_active=False))
    await session.commit()
    for outcome in ['win','lose']:
        assert (await api.post(path+'/'+outcome,headers=OWN,json={'reason_code':'price'})).status_code==422
    assert (await api.get(path,headers=OWN)).json()['stage']=='new'


async def test_disabled_reason_catalog_cannot_accept_arbitrary_reason(api, session):
    client_id = await setup_client(api, session)
    response = await api.post('/sales/deals', headers=OWN, json={
        'number': 'DISABLED-REASON', 'title': 'Synthetic', 'counterparty': 'ignored',
        'crm_client_id': client_id})
    assert response.status_code == 201, response.text
    path = f"/sales/deals/{response.json()['id']}"
    session.add(LossReason(code='price', title='Disabled price', active=False))
    await session.commit()
    for reason in ['price', 'invented']:
        denied = await api.post(path + '/lose', headers=OWN, json={'reason_code': reason})
        assert denied.status_code == 422, denied.text
    assert (await api.get(path, headers=OWN)).json()['stage'] == 'new'
