# ruff: noqa: F811 -- disposable PostgreSQL fixtures
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from core.services.auth import CurrentUser
from modules.accounting import service
from modules.accounting.gateway import AccountingService
from modules.accounting.models import Line
from modules.accounting.production_cost_posting import ProductionOverheadConfirm, confirm_overhead
from modules.accounting.production_cost_review import ProductionCostReviewInput, review_costs
from modules.accounting.production_cost_sources import cost_sources
from modules.accounting.schemas import PostingInput
from modules.production.accounting_ownership import OwnershipCommand, assign_order, order_snapshot
from modules.production.models import ProductionOrder
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_production_cost_policy import body, seed
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401


@pytest.mark.parametrize('pool_count', [1, 2])
async def test_three_order_cent_allocation_commit_and_input_permutation(issuance_pg, pg_book, monkeypatch, pool_count):
    api, factory = issuance_pg
    api.headers['X-User'] = 'tester'
    async with factory() as session:
        await session.execute(text("SELECT setval(pg_get_serial_sequence('accounting.account','id'), (SELECT max(id) FROM accounting.account))"))
        await session.execute(text("SELECT setval(pg_get_serial_sequence('accounting.policy','id'), (SELECT max(id) FROM accounting.policy))"))
        await seed(session, pg_book[0])
    policy = await api.post(f'/accounting/organizations/{pg_book[0]}/policies', json=body())
    assert policy.status_code == 201, policy.text
    policy_id = policy.json()['id']
    production = api._transport.app.state.core.services.production_output
    ids = []
    async with factory() as session:
        for number in range(3 * pool_count):
            order = ProductionOrder(number=f'ROUND-{number}', product='Synthetic rounding target', qty=1)
            session.add(order)
            await session.flush()
            await assign_order(session, AccountingService(), pg_book[0], CurrentUser('tester', ['director']),
                OwnershipCommand(order_id=order.id, expected_digest=order_snapshot(order)[1], evidence='Synthetic reviewed cost target'))
            ids.append(order.id)
        sources = [(order_id, i // 3, '1.00') for i, order_id in enumerate(ids)]
        sources += [(None, pool, ['100.01', '200.02'][pool]) for pool in range(pool_count)]
        for index, (order_id, pool, amount) in enumerate(sources):
            account = '20' if order_id else '25'
            dimensions = {'department': f'SHOP-{pool}'} | ({'order': f'KEY-{order_id}'} if order_id else {})
            await service.post(session, pg_book[0], PostingInput(source=f'ROUND-COST-{index}', source_version=1,
                operation='manual', document_date='2026-10-02', operation_date='2026-10-02', posting_date='2026-10-02',
                policy_id=policy_id, rule_version='synthetic', explanation='Synthetic rounding source', lines=[
                    {'account': account, 'side': 'debit', 'amount': amount, 'dimensions': dimensions},
                    {'account': '60', 'side': 'credit', 'amount': amount}]), 'tester')
        await session.commit()
    async with factory() as session:
        source = await cost_sources(session, pg_book[0], '2026-10', policy_id)
        command = ProductionCostReviewInput(policy_id=policy_id, expected_source_digest=source['digest'],
            classifications=[{'line_id': line['line_id'], 'role': 'direct_cost' if line['account'] == '20' else 'overhead',
                'evidence': 'Synthetic reviewed cost classification'} for line in reversed(source['snapshot']['lines'])],
            orders=[{'analytical_order': f'KEY-{order_id}', 'order_id': order_id, 'evidence': 'Synthetic reviewed analytical mapping'} for order_id in reversed(ids)])
        reviewed = await review_costs(session, pg_book[0], '2026-10', command, production)
        expected_amounts = ['33.34', '33.34', '33.33'] + (['66.68', '66.67', '66.67'] if pool_count == 2 else [])
        allocations = reviewed['snapshot']['allocations']
        assert len(allocations) == pool_count
        for pool, allocation in enumerate(allocations):
            assert allocation['pool_dimensions'] == {'department': f'SHOP-{pool}'}
            assert [(row['order_id'], row['amount_byn']) for row in allocation['allocation']['shares']] == list(zip(
                ids[pool * 3:pool * 3 + 3], expected_amounts[pool * 3:pool * 3 + 3]))
        reordered = command.model_copy(update={'classifications': list(reversed(command.classifications)), 'orders': list(reversed(command.orders))})
        second = await review_costs(session, pg_book[0], '2026-10', reordered, production)
        assert second['snapshot']['allocations'] == reviewed['snapshot']['allocations']
        confirm = ProductionOverheadConfirm(request_key=uuid4(), review=command, expected_review_digest=reviewed['digest'],
            posting_date='2026-10-31', evidence='Synthetic reviewed three-order allocation')
        await session.rollback()
    if pool_count == 2:
        from modules.accounting import production_cost_posting as posting_module
        original = posting_module.posting_candidate
        def misplaced_cost(*args):
            posting = original(*args)
            lines = list(posting.lines)
            lines[0] = lines[0].model_copy(update={'dimensions': {**lines[0].dimensions, 'department': 'SHOP-1'}})
            return posting.model_copy(update={'lines': lines})
        with monkeypatch.context() as patch:
            patch.setattr(posting_module, 'posting_candidate', misplaced_cost)
            async with factory() as session:
                with pytest.raises(DBAPIError, match='independently allocated ledger costs'):
                    await confirm_overhead(session, pg_book[0], '2026-10', confirm, 'tester', production)
                    await session.commit()
                await session.rollback()
    import asyncio
    payload = confirm.model_dump(mode='json')
    path = f'/accounting/organizations/{pg_book[0]}/periods/2026-10/production-overhead-confirm'
    readback = f'/accounting/organizations/{pg_book[0]}/production-overhead-confirmations/{confirm.request_key}'
    assert (await api.get(readback)).status_code == 404
    access_path = f'/accounting/organizations/{pg_book[0]}/production-overhead-access'
    access = await api.get(access_path)
    assert access.status_code == 200
    assert access.json() == {'organization_id': pg_book[0], 'principal': 'tester', 'can_confirm': True}
    assert access.headers['cache-control'] == 'private, no-store'
    assert (await api.get(access_path.replace(f'organizations/{pg_book[0]}', 'organizations/999'))).status_code == 403
    assert (await api.post(path, json=payload)).status_code == 422
    assert (await api.post(path, json=payload, headers={'X-Expected-Principal': 'other'})).status_code == 409
    responses = await asyncio.gather(*[api.post(path, json=payload, headers={'X-Expected-Principal': 'tester'}) for _ in range(2)])
    assert [response.status_code for response in responses] == [201, 201], [response.text for response in responses]
    assert responses[0].json() == responses[1].json()
    saved = (await api.get(readback))
    assert saved.status_code == 200 and saved.json() == responses[0].json()
    assert saved.headers['cache-control'] == 'private, no-store'
    assert saved.json()['command'] == payload and saved.json()['posted'] is True
    assert saved.json()['final_cost_certified'] is False
    from modules.accounting.models import AccessGrant
    async with factory() as session:
        session.add(AccessGrant(id=99001, organization_id=pg_book[0], subject='cost-viewer', role='reader'))
        await session.commit()
    reader_headers = {'X-User': 'cost-viewer', 'X-Expected-Principal': 'cost-viewer'}
    reader_access = await api.get(access_path, headers=reader_headers)
    assert reader_access.status_code == 200
    assert reader_access.json() == {'organization_id': pg_book[0], 'principal': 'cost-viewer', 'can_confirm': False}
    assert (await api.post(path, json=payload, headers=reader_headers)).status_code == 403
    reader_result = await api.get(readback, headers=reader_headers)
    assert reader_result.status_code == 200 and reader_result.json() == saved.json()
    conflict = await api.post(path, json={**payload, 'evidence': 'Changed confirmation evidence'}, headers={'X-Expected-Principal': 'tester'})
    assert conflict.status_code == 409
    assert (await api.get(readback.replace(f'organizations/{pg_book[0]}', 'organizations/999'))).status_code == 403
    async with factory() as session:
        lines = (await session.scalars(select(Line).where(Line.entry_id == saved.json()['entry_id']))).all()
        assert sorted((line.dimensions['order'], str(line.amount)) for line in lines if line.side == 'debit') == sorted(zip(
            [f'KEY-{order_id}' for order_id in ids], expected_amounts))
        assert [str(line.amount) for line in lines if line.side == 'credit'] == ['100.01', '200.02'][:pool_count]
