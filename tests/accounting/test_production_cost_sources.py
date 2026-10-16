from datetime import date, datetime
from decimal import localcontext

import pytest

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


async def _posted_owned_cost(db, book, mutation=None):
    from core.db.base import Base
    from modules.accounting.models import Account, Policy
    from modules.accounting.order_snapshot import dimensions_from_ownership
    from modules.production.accounting_ownership import ProductionOrderOwnership, order_snapshot
    from modules.production.models import ProductionOrder

    await db.rollback()
    mapping = dict(db.bind.get_execution_options()['schema_translate_map'], production=None)
    db.bind.update_execution_options(schema_translate_map=mapping)
    connection = await db.connection()
    await connection.run_sync(lambda c: Base.metadata.create_all(c, tables=[
        ProductionOrder.__table__, ProductionOrderOwnership.__table__,
    ]))
    await seed(db, book[0])
    policy_body = body()
    policy_body['production_costing']['finished_goods_account'] = '43'
    policy = Policy(organization_id=book[0], normative_verified=False,
                    approved_by='tester', **policy_body)
    policy.effective_from = date(2026, 10, 1)
    db.add(policy)
    db.add(Account(organization_id=book[0], code='43', title='Synthetic finished goods',
                   category='asset', valid_from=date(2026, 1, 1),
                   required_dimensions=['warehouse', 'sku', 'lot'], quantity_tracking=True,
                   currency_tracking=False, cash=False, normative_ref='Synthetic'))
    order = ProductionOrder(id=42, number='OWNED-42', product='Widget', qty=2,
                            stage='queue', created_at=datetime(2026, 10, 1))
    db.add(order)
    await db.flush()
    snapshot, digest = order_snapshot(order)
    ownership = ProductionOrderOwnership(order_id=42, organization_id=book[0], snapshot=snapshot,
                                        digest=digest, evidence='Synthetic verified ownership', actor='tester')
    db.add(ownership)
    dimensions = dict(dimensions_from_ownership(ownership), department='SHOP')
    account = '20'
    if mutation == 'unknown':
        dimensions['unexpected'] = 'not an analytic'
    elif mutation == 'missing':
        dimensions.pop('order_digest')
    elif mutation == 'changed':
        dimensions['order_product'] = 'Forged product'
    elif mutation == 'foreign':
        ownership.organization_id = book[0] + 1000
    elif mutation == 'overhead':
        account = '25'
    await db.commit()
    entry = await service.post(db, book[0], PostingInput(
        source='owned-wip', source_version=1, operation='manual',
        document_date='2026-10-10', operation_date='2026-10-10', posting_date='2026-10-10',
        policy_id=policy.id, rule_version='Synthetic', explanation='Synthetic owned WIP', lines=[
            {'account': account, 'side': 'debit', 'amount': '177.00', 'dimensions': dimensions},
            {'account': '60', 'side': 'credit', 'amount': '177.00'},
        ]), 'tester')
    await db.commit()
    return policy, dimensions, entry


async def test_owned_wip_snapshot_survives_cost_sources_and_transfer_preview(db, book):
    from modules.accounting.production_cost_sources import cost_sources
    from modules.accounting.production_output_transfer import (
        ProductionOutputTransferInput,
        prepare_output_transfer,
    )
    from tests.accounting.test_production_output_cost_basis import Production, output

    policy, dimensions, entry = await _posted_owned_cost(db, book)
    source = await cost_sources(db, book[0], '2026-10', policy.id)
    assert source['snapshot']['lines'][0]['entry_digest'] == entry.digest
    assert source['snapshot']['lines'][0]['dimensions'] == dimensions
    assert source['snapshot']['balances'][0]['dimensions'] == dimensions
    assert source['snapshot']['balances'][0]['closing_byn'] == '177.00'
    physical = dict(output(), sku_code='WIDGET', lot='LOT-1')
    result = await prepare_output_transfer(db, book[0], '2026-10', ProductionOutputTransferInput(
        policy_id=policy.id, order_id=42, analytical_order='OWNED-42', department='SHOP',
        warehouse='warehouse1', posting_date=date(2026, 10, 31), output_document_ids=[1],
    ), Production(physical), object())
    assert result['candidate_transfer_byn'] == '177.00'
    assert result['posting_available'] is True
    assert result['posting_document']['lines'][1]['dimensions'] == dimensions
    assert result['posting_document']['lines'][1]['amount'] == '177.00'


@pytest.mark.parametrize('mutation', ['unknown', 'missing', 'changed', 'foreign', 'overhead'])
async def test_cost_sources_reject_invalid_owned_snapshot(db, book, mutation):
    from modules.accounting.production_cost_sources import cost_sources

    policy, _, _ = await _posted_owned_cost(db, book, mutation)
    with pytest.raises(service.AccountingError):
        await cost_sources(db, book[0], '2026-10', policy.id)
