"""Standalone own deal closure must use canonical audited transitions."""
from uuid import uuid4

import pytest
from sqlalchemy import select

from core.domain.models import OutboxEvent
from modules.sales.models import LossReason, Stage
from tests.test_crm_client_contacts import FOREIGN, OWN, setup_client


@pytest.mark.parametrize('stage,expected', [('won', 422), ('lost', 409), ('rp_won', 422), ('missing', 422)])
async def test_standalone_creation_rejects_terminal_or_foreign_stage(api, session, stage, expected):
    client_id=await setup_client(api,session)
    response=await api.post('/sales/deals',headers=OWN,json={
        'number':'GUARD-CREATE','title':'Synthetic','counterparty':'ignored',
        'crm_client_id':client_id,'stage':stage})
    assert response.status_code==expected,response.text


async def owned_loss_payload(api, session, deal_id, **changes):
    from modules.accounting.models import AccessGrant, Organization
    from modules.sales.accounting_ownership import DealOwnership

    owner = await session.get(DealOwnership, deal_id)
    if owner is None:
        organization = Organization(name="Synthetic outcome book", unp="100000009")
        session.add(organization)
        await session.flush()
        session.add_all([
            AccessGrant(organization_id=organization.id, subject=OWN["X-User"], role="chief"),
            DealOwnership(deal_id=deal_id, organization_id=organization.id, snapshot={},
                          evidence="Synthetic own outcome book", actor=OWN["X-User"]),
        ])
        await session.commit()
        org = organization.id
    else:
        org = owner.organization_id
    preview = await api.get(f"/sales/organizations/{org}/deals/{deal_id}/loss-preview", headers=OWN)
    assert preview.status_code == 200, preview.text
    return {"organization_id": org, "request_key": str(uuid4()),
            "expected_composition_digest": preview.json()["composition_digest"],
            "reason_code": "price", "finalize_if_empty": True, **changes}


LOSS_HEADERS = {**OWN, "X-Expected-Principal": OWN["X-User"]}


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
    for patch, expected in [({'stage':'won'}, 422), ({'stage':'lost'}, 409), ({'closed_date':'01.01.2000'}, 422)]:
        denied=await api.patch(path,headers=OWN,json=patch)
        assert denied.status_code==expected,denied.text
        assert (await api.get(path,headers=OWN)).json()==initial_detail
    for suffix in ['win','lose']:
        response=await api.post(path+'/'+suffix,
            headers={**FOREIGN, 'X-Expected-Principal': FOREIGN['X-User']},
            json={'organization_id':999, 'request_key':str(uuid4()), 'expected_composition_digest':'a'*64, 'reason_code':'price'})
        assert response.status_code==404
    assert (await api.post(path+'/lose',headers=OWN,json={'reason_code':''})).status_code==422
    won=await api.post(path+'/win',headers=OWN)
    assert won.status_code==200,won.text
    assert won.json()['stage']=='won' and won.json()['closed_date']
    assert (await api.post(path+'/win',headers=OWN)).status_code==409
    assert (await api.patch(path,headers=OWN,json={'stage':'qual','closed_date':'01.01.2000'})).status_code==422
    reopened=await api.patch(path,headers=OWN,json={'stage':'qual'})
    assert reopened.status_code==200 and reopened.json()['closed_date'] is None
    loss_body = await owned_loss_payload(api, session, deal['id'], comment='Synthetic reason')
    lost = await api.post(path+'/lose', headers=LOSS_HEADERS, json=loss_body)
    assert lost.status_code == 200, lost.text
    assert lost.json()['state'] == 'finalized'
    assert lost.json()['resolution']['action'] == 'finalized'
    replay = await api.post(path+'/lose', headers=LOSS_HEADERS, json=loss_body)
    assert replay.status_code == 200 and replay.json()['replayed'] is True
    assert replay.json()['resolution'] == lost.json()['resolution']
    assert (await api.post(path+'/lose', headers=LOSS_HEADERS,
        json={**loss_body, 'request_key':str(uuid4())})).status_code == 409
    final = (await api.get(path, headers=OWN)).json()
    assert final['stage']=='lost' and final['lost_reason_code']=='price'
    assert final['lost_comment']=='Synthetic reason' and final['closed_date']
    for field in ['next_step','next_step_at','ship_deadline','expected_close_date']:
        assert final[field]==deal[field]
    history=(await api.get(path+'/history',headers=OWN)).json()
    assert [row['to_stage'] for row in history][-3:]==['won','qual','lost']
    events=(await session.scalars(select(OutboxEvent).where(
        OutboxEvent.event_type.in_(['sales.deal.won','sales.deal.loss_requested','sales.deal.loss_finalized'])))).all()
    own_events = [row.event_type for row in events if row.payload.get('deal_id')==deal['id']]
    assert sorted(own_events) == ['sales.deal.loss_finalized', 'sales.deal.loss_requested', 'sales.deal.won']


async def test_numeric_director_and_unlinked_own_cannot_bypass_closure(api,session,synthetic_sales_party):
    client_id=await setup_client(api,session)
    base={'number':'DIRECTOR-NUMERIC','title':'Synthetic','counterparty':'ignored',
          'crm_client_id':client_id,'owner_id':651,'stage':'won'}
    assert (await api.post('/sales/deals',json=base)).status_code==422
    response=await api.post('/sales/deals',json={**base,'stage':'new'})
    assert response.status_code==201,response.text
    assert (await api.patch(f"/sales/deals/{response.json()['id']}",json={'stage':'lost'})).status_code==409
    unlinked={'number':'OWN-UNLINKED','title':'Synthetic','counterparty':'Legacy','counterparty_id':synthetic_sales_party.id,'stage':'won'}
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
    body = await owned_loss_payload(api, session, response.json()['id'])
    assert (await api.post(path+'/win', headers=OWN)).status_code == 422
    assert (await api.post(path+'/lose', headers=LOSS_HEADERS, json=body)).status_code == 409
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
        body = await owned_loss_payload(api, session, response.json()['id'], reason_code=reason)
        denied = await api.post(path + '/lose', headers=LOSS_HEADERS, json=body)
        assert denied.status_code == 422, denied.text
    assert (await api.get(path, headers=OWN)).json()['stage'] == 'new'
