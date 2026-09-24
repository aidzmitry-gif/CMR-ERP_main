"""Real PostgreSQL command tombstone; applied effects/concurrency need separate tests."""
import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from core.domain.models import IdentityInvitationRequest, OutboxEvent, User
from modules.procurement.models import PurchaseOrderMilestone, TransportMethod
from modules.procurement.ownership import request_command_hash
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.accounting.test_procurement_order_creation import command as creation_command
from tests.accounting.test_procurement_order_edit_commands import command
from tests.accounting.test_procurement_request_creation_postgres import schedule
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401


async def test_pg_reconcile_blocks_late_command_and_protects_receipt(issuance_pg):  # noqa: F811
    api, factory = issuance_pg
    org = await api.post('/accounting/organizations', json={'name': 'Synthetic edit recovery', 'unp': '999999937'})
    assert org.status_code == 201, org.text
    org_id = org.json()['id']
    endpoint = f'/procurement/organizations/{org_id}/orders/2147483000/edit-commands'
    headers = {'X-Expected-Organization': str(org_id), 'X-Expected-Principal': 'issuer'}
    cmd = command(2147483000)
    first = await api.post(endpoint + '/reconcile', json=cmd, headers=headers)
    assert first.status_code == 409, first.text
    assert first.json()['code'] == 'command_abandoned'
    late = await api.post(endpoint, json=cmd, headers=headers)
    assert late.status_code == 409 and late.json() == first.json()
    racing = command(2147483000)
    results = await asyncio.gather(
        api.post(endpoint, json=racing, headers=headers),
        api.post(endpoint + '/reconcile', json=racing, headers=headers),
    )
    assert [r.status_code for r in results] == [409, 409]
    assert results[0].json() == results[1].json()
    assert results[0].json()['code'] in {'source_unavailable', 'command_abandoned'}
    async with factory() as session:
        assert await session.scalar(text('SELECT count(*) FROM procurement.purchase_order_edit_command')) == 2
        for statement in (
            'UPDATE procurement.purchase_order_edit_command SET actor=actor',
            'DELETE FROM procurement.purchase_order_edit_command',
            'TRUNCATE procurement.purchase_order_edit_command',
        ):
            with pytest.raises(DBAPIError, match='immutable'):
                async with session.begin_nested():
                    await session.execute(text(statement))
        with pytest.raises(DBAPIError, match='identity mismatch'):
            async with session.begin_nested():
                await session.execute(text('''INSERT INTO procurement.purchase_order_edit_command
                    (organization_id,request_key,actor,target_order_id,action,outcome,ownership_id,command,command_hash,result)
                    SELECT organization_id,request_key,actor,target_order_id+1,action,outcome,ownership_id,command,command_hash,result
                    FROM procurement.purchase_order_edit_command'''))


async def test_pg_owned_order_all_edit_actions_replay(issuance_pg):  # noqa: F811
    api, factory = issuance_pg
    # Existing migration 0072 tables, not part of the additive accounting DDL.
    async with factory() as session:
        conn = await session.connection()
        await conn.run_sync(lambda c: TransportMethod.metadata.create_all(c,
            tables=[TransportMethod.__table__, PurchaseOrderMilestone.__table__], checkfirst=True))
        await session.commit()
    org = await api.post('/accounting/organizations', json={'name': 'Synthetic applied edits', 'unp': '999999938'})
    assert org.status_code == 201, org.text
    org_id = org.json()['id']
    prefix = f'/procurement/organizations/{org_id}'
    headers = {'X-Expected-Organization': str(org_id), 'X-Expected-Principal': 'issuer'}
    created = await api.post(prefix + '/orders', json=creation_command(), headers=headers)
    assert created.status_code == 201, created.text
    order_id = created.json()['order_id']
    endpoint = prefix + f'/orders/{order_id}/edit-commands'
    added = None
    saved = []
    for action in ['add_line', 'delete_line', 'header', 'status', 'plan']:
        payload = {'delete_line': {'line_id': added}, 'header': {'freight_byn': '7.13'},
            'status': {'status': 'shipped'},
            'plan': {'transport_method_code': 'truck', 'target_arrival_date': '2026-12-01'}}.get(action)
        cmd = command(order_id, action, payload)
        response = await api.post(endpoint, json=cmd, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()['outcome'] == 'applied'
        if action == 'add_line':
            added = response.json()['effect']['line']['id']
        async with factory() as session:
            event_count = await session.scalar(select(func.count()).select_from(OutboxEvent))
        saved.append((cmd, response.json()))
        for suffix in ['', '/reconcile']:
            replay = await api.post(endpoint + suffix, json=cmd, headers=headers)
            assert replay.status_code == 200 and replay.json() == response.json(), replay.text
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == event_count
    # Replaying the original add after deletion must not resurrect its line.
    replay = await api.post(endpoint, json=saved[0][0], headers=headers)
    assert replay.json() == saved[0][1]
    async with factory() as session:
        assert await session.scalar(text('SELECT count(*) FROM procurement.purchase_order_edit_command')) == 5
        assert await session.scalar(text('SELECT count(*) FROM procurement.purchase_order_line WHERE id=:id'), {'id': added}) == 0
        assert str(await session.scalar(text('SELECT freight_byn FROM procurement.purchase_order WHERE id=:id'), {'id': order_id})) == '7.13'
        assert await session.scalar(text('SELECT status FROM procurement.purchase_order WHERE id=:id'), {'id': order_id}) == 'shipped'
        assert await session.scalar(text('SELECT count(*) FROM procurement.purchase_order_milestone WHERE order_id=:id'), {'id': order_id}) == 6
        # Correctly rehashed historical line effects cannot become new commands.
        for old_cmd, old_result in saved[:2]:
            cloned_cmd, cloned_result = deepcopy(old_cmd), deepcopy(old_result)
            key = str(uuid4())
            cloned_cmd['request_key'] = key
            checksum = request_command_hash(cloned_cmd)
            cloned_result.update(request_key=key, command_hash=checksum)
            with pytest.raises(DBAPIError, match='matching line mutation proof'):
                async with session.begin_nested():
                    await session.execute(text('''INSERT INTO procurement.purchase_order_edit_command
                        (organization_id,request_key,actor,target_order_id,action,outcome,ownership_id,command,command_hash,result)
                        VALUES (:org,:key,'issuer',:order_id,:action,'applied',:owner,CAST(:command AS json),:checksum,CAST(:result AS json))'''),
                        {'org': org_id, 'key': key, 'order_id': order_id, 'action': cloned_cmd['action'],
                         'owner': cloned_result['ownership_id'], 'command': json.dumps(cloned_cmd),
                         'checksum': checksum, 'result': json.dumps(cloned_result)})
        for statement in ('UPDATE procurement.order_line_edit_proof SET snapshot=snapshot',
                          'DELETE FROM procurement.order_line_edit_proof',
                          'TRUNCATE procurement.order_line_edit_proof'):
            with pytest.raises(DBAPIError, match='immutable'):
                async with session.begin_nested():
                    await session.execute(text(statement))
        with pytest.raises(DBAPIError, match='generated by a line trigger'):
            async with session.begin_nested():
                await session.execute(text('''INSERT INTO procurement.order_line_edit_proof
                    SELECT txid_current(),line_id,order_id,action,snapshot
                    FROM procurement.order_line_edit_proof LIMIT 1'''))


async def test_pg_atomic_save_has_one_history_receipt_and_line_proof(issuance_pg):  # noqa: F811
    api, factory = issuance_pg
    async with factory() as session:
        conn = await session.connection()
        await conn.run_sync(lambda c: TransportMethod.metadata.create_all(c,
            tables=[TransportMethod.__table__, PurchaseOrderMilestone.__table__], checkfirst=True))
        await session.commit()
    org = await api.post('/accounting/organizations', json={'name': 'Synthetic atomic save', 'unp': '999999935'})
    assert org.status_code == 201, org.text
    org_id = org.json()['id']
    prefix = f'/procurement/organizations/{org_id}'
    headers = {'X-Expected-Organization': str(org_id), 'X-Expected-Principal': 'issuer'}
    created = await api.post(prefix + '/orders', json=creation_command(), headers=headers)
    assert created.status_code == 201, created.text
    order_id = created.json()['order_id']
    endpoint = prefix + f'/orders/{order_id}/edit-commands'
    cmd = command(order_id, 'save', {'add_line': command(order_id)['payload'],
        'header': {'freight_byn': '7.13'},
        'plan': {'transport_method_code': 'truck', 'target_arrival_date': '2026-12-01'},
        'status': {'status': 'ordered'}})
    saved = await api.post(endpoint, json=cmd, headers=headers)
    assert saved.status_code == 200, saved.text
    assert set(saved.json()['effect']) == set(cmd['payload'])
    history = await api.get(prefix + f'/orders/{order_id}/edit-history')
    assert history.status_code == 200, history.text
    assert len(history.json()['items']) == 1
    assert [x['field'] for x in history.json()['items'][0]['changes']][1:] == ['freight_byn', 'plan', 'status']
    assert (await api.post(endpoint, json=cmd, headers=headers)).json() == saved.json()
    async with factory() as session:
        assert await session.scalar(text('SELECT count(*) FROM procurement.purchase_order_edit_command')) == 1
        assert await session.scalar(text("SELECT count(*) FROM procurement.purchase_order_line WHERE order_id=:id AND sku_code='NEW'"), {'id': order_id}) == 1
        assert str(await session.scalar(text('SELECT freight_byn FROM procurement.purchase_order WHERE id=:id'), {'id': order_id})) == '7.13'
        assert await session.scalar(text('SELECT status FROM procurement.purchase_order WHERE id=:id'), {'id': order_id}) == 'ordered'
        forged_cmd, forged_result = deepcopy(cmd), deepcopy(saved.json())
        forged_cmd['request_key'] = str(uuid4())
        forged_result.update(request_key=forged_cmd['request_key'], command_hash=request_command_hash(forged_cmd))
        with pytest.raises(DBAPIError, match='matching line mutation proof'):
            async with session.begin_nested():
                await session.execute(text('''INSERT INTO procurement.purchase_order_edit_command
                    (organization_id,request_key,actor,target_order_id,action,outcome,ownership_id,command,command_hash,result)
                    VALUES (:org,:key,'issuer',:order_id,'save','applied',:owner,CAST(:command AS json),:checksum,CAST(:result AS json))'''),
                    {'org': org_id, 'key': forged_cmd['request_key'], 'order_id': order_id,
                     'owner': forged_result['ownership_id'], 'command': json.dumps(forged_cmd),
                     'checksum': forged_result['command_hash'], 'result': json.dumps(forged_result)})


@pytest.mark.parametrize('case', ['same', 'changed', 'execute-reconcile', 'reconcile-execute', 'rollback', 'revoke', 'revoke-replay'])
async def test_pg_edit_real_lock_wait(issuance_pg, tmp_path, case):  # noqa: F811
    api, factory = issuance_pg
    organization = await api.post('/accounting/organizations', json={
        'name': 'Synthetic concurrent edit', 'unp': '999999939'})
    assert organization.status_code == 201, organization.text
    org = organization.json()['id']
    prefix = f'/procurement/organizations/{org}'
    api.headers['X-Expected-Organization'] = str(org)
    created = await api.post(prefix + '/orders', json=creation_command(),
        headers={'X-Expected-Principal': 'issuer'})
    assert created.status_code == 201, created.text
    order_id = created.json()['order_id']
    endpoint = prefix + f'/orders/{order_id}/edit-commands'
    cmd = command(order_id)
    first = ('POST', endpoint, cmd)
    second = deepcopy(first)
    if case == 'changed':
        second[2]['payload']['qty'] = '2.00'
    elif case == 'execute-reconcile':
        second = ('POST', endpoint + '/reconcile', cmd)
    elif case == 'reconcile-execute':
        first = ('POST', endpoint + '/reconcile', cmd)
    revocation = case in {'revoke', 'revoke-replay'}
    if revocation:
        if case == 'revoke-replay':
            initial = await api.post(endpoint, json=cmd, headers={'X-Expected-Principal': 'issuer'})
            assert initial.status_code == 200, initial.text
        first = ('POST', endpoint, command(order_id))
        async with factory() as session:
            conn = await session.connection()
            for model in (User, IdentityInvitationRequest):
                await conn.run_sync(lambda c, model=model: model.__table__.create(c, checkfirst=True))
            session.add(User(username='issuer', full_name='Synthetic', keycloak_user_id='issuer',
                role='director', status='active'))
            await session.commit()
    evidence = {'case': case, 'locks': []}
    pg = SimpleNamespace(api=api, factory=factory, org=org, prefix=prefix, evidence=evidence)
    try:
        results = await schedule(pg, first, second, fault=case == 'rollback',
            revoke={'status': 'suspended'} if revocation else None)
        expected = ([200, 403] if revocation else [409, 409] if case == 'reconcile-execute' else [200, 409]
            if case == 'changed' else [422, 200] if case == 'rollback' else [200, 200])
        assert [r['status'] for r in results] == expected, results
        if case in {'same', 'execute-reconcile', 'reconcile-execute'}:
            assert results[0]['body'] == results[1]['body']
        async with factory() as session:
            assert await session.scalar(text('SELECT count(*) FROM procurement.purchase_order_edit_command')) == 1 + int(case == 'revoke-replay')
            assert await session.scalar(text("SELECT count(*) FROM procurement.purchase_order_line WHERE sku_code='NEW'")) == int(case != 'reconcile-execute') + int(case == 'revoke-replay')
        if revocation:
            trace = evidence['locks'][-1]
            assert trace['cached_before']['python_id'] == trace['cached_after']['python_id']
            assert trace['cached_after']['status'] == 'suspended'
    finally:
        (tmp_path / 'edit-lock-evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
