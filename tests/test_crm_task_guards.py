"""Own task assignments and explicit patch fields must not bypass scope."""
from tests.test_crm_client_contacts import FOREIGN, OWN, setup_client


async def test_own_task_assignment_status_and_foreign_updates(api, session):
    client_id = await setup_client(api, session)
    deal = (await api.post('/sales/deals',headers=OWN,json={
        'number':'TASK-GUARDS','title':'Task','counterparty':'ignored','crm_client_id':client_id})).json()
    path=f"/sales/deals/{deal['id']}/tasks"
    assert (await api.post(path,headers=OWN,json={'title':'Forbidden','assignee_id':652})).status_code == 403
    created=await api.post(path,headers=OWN,json={'title':'My follow-up'})
    assert created.status_code == 201,created.text
    task=created.json()
    assert task['assignee_id'] == 651
    endpoint=f"/sales/tasks/{task['id']}"
    assert (await api.patch(endpoint,headers=OWN,json={'assignee_id':652})).status_code == 403
    assert (await api.patch(endpoint,headers=FOREIGN,json={'status':'done'})).status_code == 404
    for patch in [{'status':None},{'status':'made_up'},{'title':None},{'kind':None}]:
        assert (await api.patch(endpoint,headers=OWN,json=patch)).status_code == 422
    unchanged=(await api.get(path,headers=OWN)).json()
    assert unchanged == [task]
    updated=await api.patch(endpoint,headers=OWN,json={'status':'done','result':'Completed'})
    assert updated.status_code == 200 and updated.json()['assignee_id'] == 651
    assert updated.json()['status'] == 'done'
    assert (await api.patch(endpoint,headers=OWN,json={'status':'open'})).status_code == 200
    assert (await api.patch(endpoint,headers=OWN,json={'status':'canceled'})).status_code == 200
