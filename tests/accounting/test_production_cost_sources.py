from decimal import localcontext

from modules.accounting import service
from modules.accounting.schemas import PostingInput
from tests.accounting.test_production_cost_policy import body, seed


async def test_dated_cost_sources_keep_opening_credits_and_document_evidence(client, db, book):
    await seed(db, book[0])
    policy = await client.post(f'/accounting/organizations/{book[0]}/policies', json=body())
    assert policy.status_code == 201, policy.text
    policy_id = policy.json()['id']
    async def post(source, day, account, amount, side='debit', opening=False):
        dimensions = {'department': 'SHOP'} | ({'order': '7'} if account == '20' else {})
        entry = await service.post(db, book[0], PostingInput(source=source, source_version=1, operation='manual',
            document_date=day, operation_date=day, posting_date=day, policy_id=book[1] if day < '2026-10-01' else policy_id,
            rule_version='Synthetic', explanation='Reviewed synthetic cost evidence', opening=opening, lines=[
                {'account': account, 'side': side, 'amount': amount, 'dimensions': dimensions},
                {'account': '60', 'side': 'credit' if side == 'debit' else 'debit', 'amount': amount}]), 'tester')
        await db.commit()
        return entry
    await post('opening', '2026-09-01', '20', '10.00', opening=True)
    source = await post('materials', '2026-10-02', '20', '100.01')
    await post('issue', '2026-10-03', '20', '30.00', side='credit')
    await post('overhead', '2026-10-03', '25', '33.33')
    await post('future', '2026-11-01', '20', '99.00')
    path = f'/accounting/organizations/{book[0]}/periods/2026-10/production-cost-sources?policy_id={policy_id}'
    response = await client.get(path)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'private, no-store'
    result = response.json()
    snapshot = result['snapshot']
    wip = next(b for b in snapshot['balances'] if b['role'] == 'wip')
    assert {k: wip[k] for k in ['opening_byn', 'debit_byn', 'credit_byn', 'closing_byn']} == {
        'opening_byn': '10.00', 'debit_byn': '100.01', 'credit_byn': '30.00', 'closing_byn': '80.01'}
    assert len(snapshot['lines']) == 4
    assert next(line for line in snapshot['lines'] if line['entry_id'] == source.id)['entry_digest'] == source.digest
    assert snapshot['allocation_base_verified'] is False and snapshot['production_order_links_verified'] is False
    with localcontext() as context:
        context.prec = 3
        repeated = await client.get(path)
    assert repeated.json() == result
    assert (await client.get(path.replace(f'policy_id={policy_id}', f'policy_id={book[1]}'))).status_code == 422
    assert (await client.get(path.replace(f'organizations/{book[0]}', 'organizations/999'))).status_code == 403


async def test_unconfigured_cost_policy_does_not_return_zero(client, book):
    response = await client.get(f'/accounting/organizations/{book[0]}/periods/2026-09/production-cost-sources?policy_id={book[1]}')
    assert response.status_code == 422
    assert 'configuration is required' in response.text
