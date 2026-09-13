"""A withdrawal and a delayed confirmation cannot both win, including direct SQL admission."""
# ruff: noqa: F811 -- disposable PostgreSQL fixtures
import asyncio
import hashlib
import json
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError

from core.services.auth import CurrentUser
from modules.accounting import production_cost_correction, service
from modules.accounting.gateway import AccountingService
from modules.accounting.models import (
    AccessGrant,
    Entry,
    Period,
    ProductionOverheadCorrectionWithdrawal,
    ProductionOverheadReceipt,
    ProductionOverheadRevision,
    ProductionOverheadWithdrawal,
)
from modules.accounting.production_cost_review import ProductionCostReviewInput, review_costs
from modules.accounting.production_cost_sources import cost_sources
from modules.accounting.schemas import PostingInput
from modules.production.accounting_ownership import OwnershipCommand, assign_order, order_snapshot
from modules.production.models import ProductionOrder
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_production_cost_policy import body, seed
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401


@pytest.mark.parametrize('delivery', ['withdraw_first', 'confirm_first', 'concurrent'])
async def test_overhead_withdrawal_serializes_with_confirmation_and_history(issuance_pg, pg_book, delivery, monkeypatch):
    api, factory = issuance_pg
    api.headers['X-User'] = 'tester'
    org = pg_book[0]
    base = f'/accounting/organizations/{org}'
    async with factory() as session:
        await session.execute(text("SELECT setval(pg_get_serial_sequence('accounting.account','id'), (SELECT max(id) FROM accounting.account))"))
        await session.execute(text("SELECT setval(pg_get_serial_sequence('accounting.policy','id'), (SELECT max(id) FROM accounting.policy))"))
        await seed(session, org)
    # Synthetic policy attestation enables exercising the real close gate in the disposable database.
    policy = await api.post(base + '/policies', json={**body(), 'normative_verified': True})
    assert policy.status_code == 201, policy.text
    policy_id = policy.json()['id']
    async with factory() as session:
        order = ProductionOrder(number='WITHDRAW-COST', product='Synthetic request target', qty=1)
        session.add(order)
        await session.flush()
        await assign_order(session, AccountingService(), org, CurrentUser('tester', ['director']),
            OwnershipCommand(order_id=order.id, expected_digest=order_snapshot(order)[1], evidence='Synthetic cost target ownership'))
        for account, amount in [('20', '100.00'), ('25', '30.00')]:
            await service.post(session, org, PostingInput(source=f'WITHDRAW-COST-{account}', source_version=1,
                operation='manual', document_date='2026-10-02', operation_date='2026-10-02', posting_date='2026-10-02',
                policy_id=policy_id, rule_version='synthetic', explanation='Synthetic source', lines=[
                    {'account': account, 'side': 'debit', 'amount': amount, 'dimensions': {'department': 'SHOP'} | ({'order': 'A'} if account == '20' else {})},
                    {'account': '60', 'side': 'credit', 'amount': amount}]), 'tester')
        await session.commit()
        source = await cost_sources(session, org, '2026-10', policy_id)
        review = ProductionCostReviewInput(policy_id=policy_id, expected_source_digest=source['digest'],
            classifications=[{'line_id': row['line_id'], 'role': 'direct_cost' if row['account'] == '20' else 'overhead',
                'evidence': 'Synthetic reviewed cost'} for row in source['snapshot']['lines']],
            orders=[{'analytical_order': 'A', 'order_id': order.id, 'evidence': 'Synthetic reviewed mapping'}])
        calculated = await review_costs(session, org, '2026-10', review, api._transport.app.state.core.services.production_output)
        await session.rollback()
    command = dict(request_key=str(uuid4()), review=review.model_dump(mode='json'), expected_review_digest=calculated['digest'],
        posting_date='2026-10-31', evidence='Synthetic confirmed allocation')
    withdrawal = {'command': command, 'reason': 'The saved command must be replaced'}
    headers = {'X-Expected-Principal': 'tester'}
    confirm_path = base + '/periods/2026-10/production-overhead-confirm'
    withdraw_path = base + '/periods/2026-10/production-overhead-withdraw'
    status_path = base + '/production-overhead-requests/' + command['request_key']
    history_path = base + '/periods/2026-10/production-overhead-history'
    assert (await api.get(status_path)).status_code == 404
    assert (await api.get(history_path)).json()['allocations'] == []
    assert (await api.post(withdraw_path, json=withdrawal)).status_code == 422
    assert (await api.post(withdraw_path, json=withdrawal, headers={'X-Expected-Principal': 'other'})).status_code == 409
    if delivery == 'concurrent':
        withdrawn, confirmed = await asyncio.gather(api.post(withdraw_path, json=withdrawal, headers=headers),
            api.post(confirm_path, json=command, headers=headers))
    elif delivery == 'withdraw_first':
        withdrawn = await api.post(withdraw_path, json=withdrawal, headers=headers)
        confirmed = await api.post(confirm_path, json=command, headers=headers)
    else:
        confirmed = await api.post(confirm_path, json=command, headers=headers)
        withdrawn = await api.post(withdraw_path, json=withdrawal, headers=headers)
    assert withdrawn.status_code == 200, withdrawn.text
    result = (await api.get(status_path))
    assert result.status_code == 200 and result.json() == withdrawn.json()
    assert result.headers['cache-control'] == 'private, no-store'
    assert result.json()['command'] == command
    assert (await api.post(withdraw_path, json=withdrawal, headers=headers)).json() == result.json()
    if result.json()['withdrawn']:
        assert confirmed.status_code == 409
        assert (await api.post(withdraw_path, json={**withdrawal, 'reason': 'Changed reason for withdrawal'}, headers=headers)).status_code == 409
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(Entry).where(Entry.operation == 'production_overhead')) == 0
        # A fresh reviewed request remains possible after the old UUID has been permanently withdrawn.
        new_command = {**command, 'request_key': str(uuid4())}
        confirmed = await api.post(confirm_path, json=new_command, headers=headers)
        assert confirmed.status_code == 201, confirmed.text
    else:
        assert confirmed.status_code == 201 and result.json()['posted'] is True
    saved = confirmed.json()
    history = await api.get(history_path)
    assert history.status_code == 200 and history.headers['cache-control'] == 'private, no-store'
    assert history.json()['allocations'] == [{**saved, 'source_state': 'unchanged'}]
    correction_path = base + '/periods/2026-10/production-overhead-correction-preview'

    async def correction_preview():
        sources = await api.get(base + '/periods/2026-10/production-overhead-correction-sources', params={
            'original_entry_id': saved['entry_id'], 'policy_id': policy_id})
        assert sources.status_code == 200, sources.text
        source_body = sources.json()
        assert source_body['snapshot']['scope'] == 'production_cost_correction_sources'
        assert source_body['snapshot']['excluded_allocation']['entry_id'] == saved['entry_id']
        assert all(row['entry_id'] != saved['entry_id'] for row in source_body['snapshot']['lines'])
        reviewed_command = {**command['review'], 'expected_source_digest': source_body['digest'], 'classifications': [
            {'line_id': row['line_id'], 'role': 'excluded' if delivery == 'concurrent' and row['source'] == 'LATE-COST'
                else 'direct_cost' if row['account'] == '20' else 'overhead', 'evidence': 'Synthetic reviewed correction classification'}
            for row in source_body['snapshot']['lines']]}
        reviewed_response = await api.post(base + '/periods/2026-10/production-overhead-correction-review',
            params={'original_entry_id': saved['entry_id']}, json=reviewed_command)
        assert reviewed_response.status_code == 200, reviewed_response.text
        preview_body = {'original_entry_id': saved['entry_id'], 'review': reviewed_command,
            'expected_review_digest': reviewed_response.json()['digest'], 'method': 'delta',
            'posting_date': '2026-10-31', 'evidence': 'Synthetic explicitly reviewed correction method'}
        preview = await api.post(correction_path, json=preview_body)
        assert preview.status_code == 200, preview.text
        assert preview.headers['cache-control'] == 'private, no-store'
        return preview.json()['snapshot'], preview_body

    unchanged_correction, initial_preview_body = await correction_preview()
    assert unchanged_correction['correction_lines'] == [] and unchanged_correction['creates_entry'] is False
    assert unchanged_correction['posted'] is False and unchanged_correction['confirmation_available'] is True
    actual_builder = production_cost_correction.allocation_lines
    with monkeypatch.context() as patch:
        patch.setattr(production_cost_correction, 'allocation_lines',
            lambda snapshot: [{**row, 'amount': '31.00'} for row in actual_builder(snapshot)])
        forged_preview = await api.post(correction_path, json=initial_preview_body)
        assert forged_preview.status_code == 422 and 'independently calculated ledger costs' in forged_preview.text
    # A mistaken allocation can be removed entirely without inventing a target order.
    excluded_review = {**initial_preview_body['review'], 'orders': [], 'classifications': [
        {**row, 'role': 'excluded', 'evidence': 'All costs excluded by corrected primary evidence'}
        for row in initial_preview_body['review']['classifications']]}
    review_path = base + '/periods/2026-10/production-overhead-correction-review'
    removed_review = await api.post(review_path, params={'original_entry_id': saved['entry_id']}, json=excluded_review)
    assert removed_review.status_code == 200, removed_review.text
    assert removed_review.json()['snapshot']['production_orders'] == []
    assert removed_review.json()['snapshot']['allocations'] == []
    removal = await api.post(correction_path, json={**initial_preview_body, 'review': excluded_review,
        'expected_review_digest': removed_review.json()['digest']})
    assert removal.status_code == 200, removal.text
    assert removal.json()['snapshot']['correction_lines'] == [
        {'account': '20', 'dimensions': {'department': 'SHOP', 'order': 'A'}, 'side': 'credit', 'amount': '30.00'},
        {'account': '25', 'dimensions': {'department': 'SHOP'}, 'side': 'debit', 'amount': '30.00'}]
    assert removal.json()['snapshot']['posted'] is False
    async with factory() as session:
        verify_sql = text('SELECT accounting.verify_production_cost_review(:org, :month, :policy, CAST(:day AS date), '
            'CAST(:reviewed AS jsonb), CAST(:command AS jsonb), ARRAY[CAST(:original AS integer)], :allow_empty)')
        parameters = dict(org=org, month='2026-10', policy=policy_id, day='2026-10-31',
            reviewed=json.dumps(removed_review.json()), command=json.dumps(excluded_review),
            original=saved['entry_id'], allow_empty=True)
        assert await session.scalar(verify_sql, parameters) == []
        delta_sql = text('SELECT accounting.production_cost_delta(:org, CAST(:desired AS jsonb), :entries)')
        applied = [saved['entry_id']]
        assert await session.scalar(delta_sql, dict(org=org, desired='[]', entries=applied)) == [
            ['20', 'credit', {'department': 'SHOP', 'order': 'A'}, 30], ['25', 'debit', {'department': 'SHOP'}, 30]]
        desired = [['20', 'debit', {'department': 'SHOP', 'order': 'A'}, 30], ['25', 'credit', {'department': 'SHOP'}, 30]]
        assert await session.scalar(delta_sql, dict(org=org, desired=json.dumps(desired), entries=applied)) == []
        desired[0][2]['order'] = 'B'
        assert await session.scalar(delta_sql, dict(org=org, desired=json.dumps(desired), entries=applied)) == [
            ['20', 'credit', {'department': 'SHOP', 'order': 'A'}, 30], ['20', 'debit', {'department': 'SHOP', 'order': 'B'}, 30]]
        for invalid_entries in [[], applied * 2, [2147483647]]:
            with pytest.raises(DBAPIError, match='unique existing allocation entries'):
                await session.scalar(delta_sql, dict(org=org, desired='[]', entries=invalid_entries))
            await session.rollback()
        with pytest.raises(DBAPIError, match='unique existing allocation entries'):
            await session.scalar(delta_sql, dict(org=org + 10000, desired='[]', entries=applied))
        await session.rollback()
        with pytest.raises(DBAPIError, match='must each balance'):
            await session.scalar(delta_sql, dict(org=org, desired=json.dumps(desired[:1]), entries=applied))
        await session.rollback()
        # Empty desired amounts are valid only for a correction; the original
        # receipt path must retain its positive-allocation admission contract.
        with pytest.raises(DBAPIError, match='policy or review structure'):
            await session.scalar(verify_sql, {**parameters, 'allow_empty': False})
        await session.rollback()
        forged = json.loads(parameters['reviewed'])
        forged['snapshot']['source']['snapshot']['balances'][0]['closing_byn'] = '999.00'
        with pytest.raises(DBAPIError, match='saved balances differ'):
            await session.scalar(verify_sql, {**parameters, 'reviewed': json.dumps(forged)})
        await session.rollback()
    # Removing the base alone must not allocate a positive pool without owned targets.
    no_base = {**excluded_review, 'classifications': [
        {**row, 'role': 'overhead' if original['role'] == 'overhead' else 'excluded'}
        for row, original in zip(excluded_review['classifications'], initial_preview_body['review']['classifications'], strict=True)]}
    invalid = await api.post(review_path, params={'original_entry_id': saved['entry_id']}, json=no_base)
    assert invalid.status_code == 422 and 'positive direct-cost base' in invalid.text
    ordinary_source = (await api.get(base + '/periods/2026-10/production-cost-sources', params={'policy_id': policy_id})).json()
    initial_without_orders = await api.post(base + '/periods/2026-10/production-cost-review', json={**excluded_review,
        'expected_source_digest': ordinary_source['digest'], 'classifications': [
            {'line_id': row['line_id'], 'role': 'excluded', 'evidence': 'Synthetic excluded initial source'}
            for row in ordinary_source['snapshot']['lines']]})
    assert initial_without_orders.status_code == 422 and 'requires verified production order bindings' in initial_without_orders.text
    assert (await api.post(correction_path, json={**initial_preview_body, 'posting_date': '2026-11-01'})).status_code == 422
    assert (await api.post(correction_path, json={**initial_preview_body, 'posting_date': '2026-10-30'})).status_code == 422
    assert (await api.post(correction_path, json={**initial_preview_body, 'method': 'assumed'})).status_code == 422
    close_evidence = {step: 'Synthetic checked closing step' for step in service.CLOSE_STEPS}
    async with factory() as session:
        generation = (await service.period_for(session, org, '2026-10')).generation
    closed = await api.post(base + '/periods/2026-10/close', json={'expected_generation': generation, 'evidence': close_evidence})
    assert closed.status_code == 200, closed.text
    assert (await api.post(correction_path, json=initial_preview_body)).status_code == 422
    reopened = await api.post(base + '/periods/2026-10/reopen', json={'reason': 'Synthetic late source review'})
    assert reopened.status_code == 200, reopened.text
    async with factory() as session:
        # Direct SQL cannot place a cancellation alongside a posted receipt.
        with pytest.raises(DBAPIError, match='posted overhead request cannot be withdrawn'):
            await session.execute(ProductionOverheadWithdrawal.__table__.insert().values(organization_id=org, month='2026-10',
                request_key=saved['request_key'], command=saved['command'], actor='tester', reason='Forged concurrent withdrawal'))
        await session.rollback()
        if result.json()['withdrawn']:
            receipt = await session.get(ProductionOverheadReceipt, saved['entry_id'])
            forged = {column.name: getattr(receipt, column.name) for column in ProductionOverheadReceipt.__table__.columns}
            forged.update(request_key=command['request_key'], command=command)
            with pytest.raises(DBAPIError, match='withdrawn overhead request cannot be posted'):
                await session.execute(ProductionOverheadReceipt.__table__.insert().values(**forged))
            await session.rollback()
            with pytest.raises(DBAPIError, match='immutable'):
                await session.execute(delete(ProductionOverheadWithdrawal).where(ProductionOverheadWithdrawal.organization_id == org))
            await session.rollback()
        session.add(AccessGrant(id=99101, organization_id=org, subject='cost-reader', role='reader'))
        await service.post(session, org, PostingInput(source='LATE-COST', source_version=1, operation='manual',
            document_date='2026-10-31', operation_date='2026-10-31', posting_date='2026-10-31', policy_id=policy_id,
            rule_version='synthetic', explanation='Late overhead evidence', lines=[
                {'account': '25', 'side': 'credit' if delivery == 'confirm_first' else 'debit',
                    'amount': '30.00' if delivery == 'confirm_first' else '1.00', 'dimensions': {'department': 'SHOP'}},
                {'account': '60', 'side': 'debit' if delivery == 'confirm_first' else 'credit',
                    'amount': '30.00' if delivery == 'confirm_first' else '1.00'}]), 'tester')
        await session.commit()
    late = await api.get(history_path)
    assert late.json()['allocations'] == [{**saved, 'source_state': 'changed'}]
    assert (await api.post(correction_path, json=initial_preview_body)).status_code == 422
    recalculated, _ = await correction_preview()
    if delivery == 'concurrent':
        assert recalculated['correction_lines'] == [] and recalculated['creates_entry'] is False
    else:
        expected = [('20', 'credit', '30.00'), ('25', 'debit', '30.00')] if delivery == 'confirm_first' else [('20', 'debit', '1.00'), ('25', 'credit', '1.00')]
        assert [(row['account'], row['side'], row['amount']) for row in recalculated['correction_lines']] == expected
    assert recalculated['original_posting'] == saved['posting']
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Entry).where(Entry.operation == 'production_overhead')) == 1
    assert (await api.get(history_path, headers={'X-User': 'cost-reader'})).json() == late.json()
    assert (await api.post(withdraw_path, json=withdrawal, headers={'X-User': 'cost-reader', 'X-Expected-Principal': 'cost-reader'})).status_code == 403
    assert (await api.get(history_path.replace(f'organizations/{org}', 'organizations/999'))).status_code == 403
    assert (await api.get(status_path.replace(f'organizations/{org}', 'organizations/999'))).status_code == 403
    async with factory() as session:
        current = await service.period_for(session, org, '2026-10')
        generation = current.generation
        # Even a fresh generation and all manual checklist text cannot bypass stale costing.
        with pytest.raises(DBAPIError, match='Production overhead sources changed'):
            await session.execute(update(Period).where(Period.id == current.id).values(
                closed=True, closed_generation=Period.generation, evidence=close_evidence))
        await session.rollback()
    stale_close = await api.post(base + '/periods/2026-10/close', json={'expected_generation': generation, 'evidence': close_evidence})
    assert stale_close.status_code == 422 and 'Production overhead sources changed' in stale_close.text
    _, reviewed_correction = await correction_preview()
    calculated = (await api.post(correction_path, json=reviewed_correction)).json()
    revision_command = {'request_key': str(uuid4()), 'preview': reviewed_correction, 'expected_preview_digest': calculated['digest']}
    revision_path = base + '/periods/2026-10/production-overhead-correction-confirm'
    readback = base + '/production-overhead-corrections/' + revision_command['request_key']
    assert (await api.get(readback)).status_code == 404
    assert (await api.post(revision_path, json=revision_command, headers={'X-Expected-Principal': 'other'})).status_code == 409
    assert (await api.post(revision_path, json=revision_command, headers={'X-User': 'cost-reader', 'X-Expected-Principal': 'cost-reader'})).status_code == 403
    async with factory() as session:
        future = await service.period_for(session, org, '2026-11')
        future_generation = future.generation
        await session.commit()
    results = await asyncio.gather(*[api.post(revision_path, json=revision_command, headers=headers) for _ in range(2)],
        api.post(base + '/periods/2026-10/close', json={'expected_generation': generation, 'evidence': close_evidence}))
    assert results.pop().status_code == 422
    for response in results:
        assert response.status_code == 201, response.text
    revision = results[0].json()
    assert results[1].json() == revision == (await api.get(readback)).json()
    assert revision['sequence'] == 1 and revision['previous_id'] is None and revision['confirmed'] is True
    assert revision['posted'] is (delivery != 'concurrent')
    assert (revision['entry_id'] is None) is (delivery == 'concurrent')
    assert revision['preview'] == calculated
    assert (await api.post(revision_path, json={**revision_command, 'request_key': str(uuid4())}, headers=headers)).status_code == 409
    assert (await api.get(readback.replace(f'organizations/{org}', 'organizations/999'))).status_code == 403
    async with factory() as session:
        assert (await service.period_for(session, org, '2026-10')).generation == generation + 1
        with pytest.raises(DBAPIError, match='immutable'):
            await session.execute(delete(ProductionOverheadRevision).where(ProductionOverheadRevision.id == revision['id']))
        await session.rollback()
    # A later reviewed zero result is a real revision but never a zero money entry.
    next_preview, next_body = await correction_preview()
    assert next_preview['correction_lines'] == []
    next_calculation = (await api.post(correction_path, json=next_body)).json()
    next_command = {'request_key': str(uuid4()), 'preview': next_body, 'expected_preview_digest': next_calculation['digest']}
    next_result = await api.post(revision_path, json=next_command, headers=headers)
    assert next_result.status_code == 201, next_result.text
    assert next_result.json()['sequence'] == 2 and next_result.json()['previous_id'] == revision['id']
    assert next_result.json()['entry_id'] is None and next_result.json()['posted'] is False
    async with factory() as session:
        future = await service.period_for(session, org, '2026-11')
        assert future.generation == future_generation + 2 and future.evidence == {} and not future.closed
    assert (await api.post(revision_path, json=revision_command, headers=headers)).json() == revision
    history_after = (await api.get(history_path)).json()['allocations'][0]
    assert history_after['source_state'] == 'unchanged'
    assert [row['id'] for row in history_after['corrections']] == [revision['id'], next_result.json()['id']]
    assert history_after['posting'] == saved['posting']
    async with factory() as session:
        generation_after = (await service.period_for(session, org, '2026-10')).generation
        assert generation_after == generation + 2
    closed_after = await api.post(base + '/periods/2026-10/close', json={'expected_generation': generation_after, 'evidence': close_evidence})
    assert closed_after.status_code == 200, closed_after.text
    assert (await api.post(revision_path, json=next_command, headers=headers)).json() == next_result.json()
    assert (await api.post(revision_path, json={**next_command, 'request_key': str(uuid4())}, headers=headers)).status_code == 409
    assert (await api.post(base + '/periods/2026-10/reopen', json={'reason': 'New evidence after approved correction'})).status_code == 200
    late_again = {**saved['posting'], 'source': 'LATE-AFTER-REVISION', 'source_version': 1, 'operation': 'manual',
        'lines': [{'account': '25', 'side': 'debit', 'amount': '2.00', 'dimensions': {'department': 'SHOP'}},
            {'account': '60', 'side': 'credit', 'amount': '2.00'}]}
    assert (await api.post(base + '/entries', json=late_again)).status_code == 201
    assert (await api.get(history_path)).json()['allocations'][0]['source_state'] == 'changed'
    async with factory() as session:
        latest_generation = (await service.period_for(session, org, '2026-10')).generation
    assert (await api.post(base + '/periods/2026-10/close', json={'expected_generation': latest_generation, 'evidence': close_evidence})).status_code == 422
    third_preview, third_body = await correction_preview()
    assert [(row['side'], row['amount']) for row in third_preview['correction_lines']] == [('debit', '2.00'), ('credit', '2.00')]
    third_calculation = (await api.post(correction_path, json=third_body)).json()
    third_command = {'request_key': str(uuid4()), 'preview': third_body, 'expected_preview_digest': third_calculation['digest']}
    forged = json.loads(json.dumps(third_calculation))
    for line in forged['snapshot']['correction_lines']:
        line['amount'] = '3.00'
    forged['digest'] = hashlib.sha256(json.dumps(forged['snapshot'], sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()

    async def forged_calculation(*args, **kwargs):
        return forged

    with monkeypatch.context() as patch:
        patch.setattr(production_cost_correction, 'preview_correction', forged_calculation)
        with pytest.raises(DBAPIError, match='delta or optional entry mismatch'):
            await api.post(revision_path, json={**third_command, 'expected_preview_digest': forged['digest']}, headers=headers)
    assert (await api.get(base + '/production-overhead-corrections/' + third_command['request_key'])).status_code == 404
    third = await api.post(revision_path, json=third_command, headers=headers)
    assert third.status_code == 201, third.text
    assert third.json()['sequence'] == 3 and third.json()['previous_id'] == next_result.json()['id']
    assert third.json()['posting']['correction_of'] == (revision['entry_id'] or saved['entry_id'])
    assert third.json()['posting']['source_version'] == 3
    _, zero_body = await correction_preview()
    zero_preview = (await api.post(correction_path, json=zero_body)).json()
    zero_command = {'request_key': str(uuid4()), 'preview': zero_body, 'expected_preview_digest': zero_preview['digest']}
    async with factory() as session:
        session.add(ProductionOverheadRevision(organization_id=org, original_entry_id=saved['entry_id'], sequence=4,
            previous_id=third.json()['id'], entry_id=None, month='2026-10', request_key=zero_command['request_key'],
            command=zero_command, preview=zero_preview, posting=None, actor='tester'))
        with pytest.raises(DBAPIError, match='invalidate its calculation generation exactly once'):
            await session.commit()
        await session.rollback()
    cancel_path = base + '/periods/2026-10/production-overhead-correction-withdraw'
    request_path = base + '/production-overhead-correction-requests/' + zero_command['request_key']
    cancel = {'command': zero_command, 'reason': 'Replace the pending correction with a newly reviewed request'}
    assert (await api.post(cancel_path, json=cancel, headers={'X-Expected-Principal': 'other'})).status_code == 409
    assert (await api.post(cancel_path, json=cancel, headers={'X-User': 'cost-reader', 'X-Expected-Principal': 'cost-reader'})).status_code == 403
    if delivery == 'concurrent':
        cancelled, zero_saved = await asyncio.gather(api.post(cancel_path, json=cancel, headers=headers),
            api.post(revision_path, json=zero_command, headers=headers))
    elif delivery == 'withdraw_first':
        cancelled = await api.post(cancel_path, json=cancel, headers=headers)
        zero_saved = await api.post(revision_path, json=zero_command, headers=headers)
    else:
        zero_saved = await api.post(revision_path, json=zero_command, headers=headers)
        cancelled = await api.post(cancel_path, json=cancel, headers=headers)
    assert cancelled.status_code == 200, cancelled.text
    outcome = (await api.get(request_path)).json()
    assert outcome == cancelled.json() == (await api.post(cancel_path, json=cancel, headers=headers)).json()
    assert outcome['posted'] is False  # Confirmed zero and withdrawn request are different terminal states.
    assert outcome['confirmed'] is not outcome['withdrawn']
    if outcome['withdrawn']:
        assert zero_saved.status_code == 409
        assert (await api.post(cancel_path, json={**cancel, 'reason': 'Another cancellation reason'}, headers=headers)).status_code == 409
        async with factory() as session:
            with pytest.raises(DBAPIError, match='Withdrawn correction request cannot be confirmed'):
                await session.execute(ProductionOverheadRevision.__table__.insert().values(organization_id=org,
                    original_entry_id=saved['entry_id'], sequence=4, previous_id=third.json()['id'], entry_id=None,
                    month='2026-10', request_key=zero_command['request_key'], command=zero_command, preview=zero_preview, posting=None, actor='tester'))
            await session.rollback()
            with pytest.raises(DBAPIError, match='immutable'):
                await session.execute(delete(ProductionOverheadCorrectionWithdrawal).where(ProductionOverheadCorrectionWithdrawal.organization_id == org))
            await session.rollback()
    else:
        assert zero_saved.status_code == 201 and outcome['entry_id'] is None
        async with factory() as session:
            with pytest.raises(DBAPIError, match='Confirmed correction request cannot be withdrawn'):
                await session.execute(ProductionOverheadCorrectionWithdrawal.__table__.insert().values(organization_id=org,
                    request_key=zero_command['request_key'], month='2026-10', command=zero_command, actor='tester', reason=cancel['reason']))
            await session.rollback()
