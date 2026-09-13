"""Client documents follow numeric links and both client/deal ownership."""
from modules.sales.models import Deal, DealDocument
from tests.test_crm_client_contacts import FOREIGN, OWN, setup_client


async def test_client_documents_exclude_name_aliases_and_foreign_deals(api, session):
    client_id = await setup_client(api, session)
    path = f'/sales/clients/{client_id}/documents'
    assert (await api.get(path, headers=OWN)).json() == []
    assert (await api.get(path, headers=FOREIGN)).status_code == 404
    for index, (owner_id, linked) in enumerate([(651,True),(652,True),(651,False)]):
        deal = Deal(number=f'DOC-CLIENT-{index}',title='Docs',counterparty='Contact buyer',
                    crm_client_id=client_id if linked else None,owner_id=owner_id)
        session.add(deal)
        await session.flush()
        session.add(DealDocument(deal_id=deal.id,kind='invoice',number=f'DOC-{index}',amount=125.50,
                                 status='posted',version=1))
    await session.commit()
    response = await api.get(path, headers=OWN)
    assert response.status_code == 200, response.text
    assert len(response.json()) == 1
    row = response.json()[0]
    assert row['number'] == 'DOC-0' and row['deal_number'] == 'DOC-CLIENT-0'
    assert row['version'] == 1 and row['original_state'] == 'legacy_unavailable'
    assert (await api.get(path, headers=FOREIGN)).status_code == 404
    assert (await api.get('/sales/clients/99999/documents', headers=OWN)).status_code == 404
