"""Real ledger verification, immutable legacy reviews, and guarded0200 rollback."""
# ruff: noqa: F811 -- disposable PostgreSQL fixtures
import asyncio
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from core.services.auth import CurrentUser
from modules.accounting import production_cost_review as review_module
from modules.accounting import service
from modules.accounting.gateway import AccountingService
from modules.accounting.models import Account
from modules.accounting.production_cost_correction import (
    ProductionOverheadCorrectionConfirm,
    ProductionOverheadCorrectionPreview,
    confirm_correction,
    preview_correction,
)
from modules.accounting.production_cost_posting import ProductionOverheadConfirm, confirm_overhead
from modules.accounting.production_cost_review import ProductionCostReviewInput, review_costs
from modules.accounting.production_cost_sources import cost_sources
from modules.accounting.schemas import PostingInput
from modules.production.accounting_ownership import OwnershipCommand, assign_order, order_snapshot
from modules.production.models import ProductionOrder
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_production_cost_policy import body, seed
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]


def migration():
    spec = importlib.util.spec_from_file_location('overhead0200', ROOT / 'migrations/versions/0200_overhead_policy_settings.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


async def migrate(factory, action, revision, *, error=None):
    async with factory() as session:
        target = session.bind.url.render_as_string(hide_password=False)
        before = await session.scalar(text('SELECT version_num FROM alembic_version'))
    result = await asyncio.to_thread(subprocess.run, [sys.executable, '-m', 'alembic', action, revision],
        env={**os.environ, 'AIOS_DATABASE_URL': target, 'AIOS_ENVIRONMENT': 'dev'}, cwd=ROOT,
        capture_output=True, text=True, timeout=60)
    if error is None:
        assert result.returncode == 0, result.stderr[-3000:]
    else:
        assert result.returncode != 0 and error in result.stderr, result.stderr[-3000:]
    async with factory() as session:
        assert await session.scalar(text('SELECT version_num FROM alembic_version')) == (before if error else revision)


async def verifier_body(factory, *, close=False):
    async with factory() as session:
        return await session.scalar(text('SELECT prosrc FROM pg_proc WHERE oid=to_regprocedure(:signature)'),
                                    {'signature': migration()._CLOSE_SIGNATURE if close else migration()._SIGNATURE})


async def prepare(api, factory, book, material):
    api.headers['X-User'] = 'tester'
    async with factory() as session:
        for table in ['account', 'policy']:
            await session.execute(text(f"SELECT setval(pg_get_serial_sequence('accounting.{table}','id'), (SELECT max(id) FROM accounting.{table}))"))
        await seed(session, book[0])
        if material is not None:
            session.add(Account(organization_id=book[0], code=material, title='Synthetic material stock',
                category='asset', valid_from=date(2026, 1, 1), required_dimensions=['warehouse', 'sku', 'lot'],
                cash=False, currency_tracking=False, quantity_tracking=True, normative_ref='Synthetic'))
            await session.commit()
    policy = body()
    if material is not None:
        policy['production_costing']['material_inventory_account'] = material
    response = await api.post(f'/accounting/organizations/{book[0]}/policies', json=policy)
    assert response.status_code == 201, response.text
    policy_id = response.json()['id']
    async with factory() as session:
        order = ProductionOrder(number='POLICY-SHAPE', product='Synthetic owned cost target', qty=1)
        session.add(order)
        await session.flush()
        await assign_order(session, AccountingService(), book[0], CurrentUser('tester', ['director']),
            OwnershipCommand(order_id=order.id, expected_digest=order_snapshot(order)[1],
                             evidence='Synthetic reviewed cost target ownership'))
        for account, amount in [('20', '1.00'), ('25', '3.33')]:
            await service.post(session, book[0], PostingInput(source=f'SHAPE-{account}', source_version=1,
                operation='manual', document_date='2026-10-02', operation_date='2026-10-02', posting_date='2026-10-02',
                policy_id=policy_id, rule_version='synthetic', explanation='Synthetic overhead policy source', lines=[
                    {'account': account, 'side': 'debit', 'amount': amount,
                     'dimensions': {'department': 'SHOP'} | ({'order': f'ORDER-{order.id}'} if account == '20' else {})},
                    {'account': '60', 'side': 'credit', 'amount': amount}]), 'tester')
        await session.commit()
    return policy_id, order.id, api._transport.app.state.core.services.production_output


async def reviewed(factory, org, policy, order, production, *, source_reader=cost_sources, correction_of=None):
    async with factory() as session:
        source = await source_reader(session, org, '2026-10', policy, correction_of=correction_of)
        command = ProductionCostReviewInput(policy_id=policy, expected_source_digest=source['digest'],
            classifications=[{'line_id': line['line_id'], 'role': 'direct_cost' if line['account'] == '20' else 'overhead',
                              'evidence': 'Synthetic reviewed source classification'} for line in source['snapshot']['lines']],
            orders=[{'analytical_order': f'ORDER-{order}', 'order_id': order, 'evidence': 'Synthetic reviewed owned order binding'}])
        result = await review_costs(session, org, '2026-10', command, production, correction_of=correction_of)
    return command, result


async def verify(factory, org, policy, command, result, excluded=()):
    async with factory() as session:
        matrix = await session.scalar(text('SELECT accounting.verify_production_cost_review(:org, :month, :policy, '
            "DATE '2026-10-31', CAST(:reviewed AS jsonb), CAST(:command AS jsonb), :excluded, false)::text"),
            {'org': org, 'month': '2026-10', 'policy': policy, 'reviewed': json.dumps(result),
             'command': command.model_dump_json(), 'excluded': list(excluded)})
        return json.loads(matrix)


async def raw_history(factory):
    async with factory() as session:
        return (await session.execute(text('SELECT review::text, command::text, posting::text '
                                           'FROM accounting.production_overhead_receipt ORDER BY entry_id'))).all()


@pytest.mark.parametrize('accounting_pg_revision', ['0199'], indirect=True)
async def test_0200_empty_roundtrip_and_unknown_function_refusal(pg_factory):
    old_body = await verifier_body(pg_factory)
    old_close = await verifier_body(pg_factory, close=True)
    module = migration()
    close_source = (ROOT / 'modules/accounting/production_cost_guards.sql').read_text(encoding='utf-8')
    close_function = re.search(r'CREATE OR REPLACE FUNCTION accounting\.assert_production_overhead_current\(.*?\$\$;', close_source, re.S)
    assert close_function.group(0) == module.CLOSE_SQL
    # The published migration is frozen; the application and additive migration
    # must describe the same replacement function, including every ledger check.
    source = (ROOT / 'modules/accounting/production_cost_verification.sql').read_text(encoding='utf-8')
    function = re.search(r'CREATE OR REPLACE FUNCTION accounting\.verify_production_cost_review\(.*?\$\$;', source, re.S)
    assert function.group(0) == module.VERIFIER_SQL
    assert old_body.strip() == module.PREVIOUS_VERIFIER_SQL.split('AS $$', 1)[1].rsplit('$$;', 1)[0].strip()
    unexpected = module.PREVIOUS_VERIFIER_SQL.replace('Invalid production overhead policy or review structure', 'Unexpected synthetic verifier')
    async with pg_factory() as session:
        await session.execute(text(unexpected.replace(':', r'\:')))
        await session.commit()
    await migrate(pg_factory, 'upgrade', '0200', error='Unexpected production overhead verifier')
    async with pg_factory() as session:
        await session.execute(text(module.PREVIOUS_VERIFIER_SQL.replace(':', r'\:')))
        await session.commit()
    unexpected_close = module.PREVIOUS_CLOSE_SQL.replace('AS $$', 'AS $$\n-- Synthetic unknown close guard')
    async with pg_factory() as session:
        await session.execute(text(unexpected_close.replace(':', r'\:')))
        await session.commit()
    await migrate(pg_factory, 'upgrade', '0200', error='Unexpected production overhead verifier')
    async with pg_factory() as session:
        await session.execute(text(module.PREVIOUS_CLOSE_SQL.replace(':', r'\:')))
        await session.commit()
    await migrate(pg_factory, 'upgrade', '0200')
    new_body = await verifier_body(pg_factory)
    new_close = await verifier_body(pg_factory, close=True)
    assert new_close != old_close and 'material_inventory_account' in new_close
    assert new_body != old_body and 'saved_settings' in new_body
    await migrate(pg_factory, 'downgrade', '0199')
    assert await verifier_body(pg_factory) == old_body
    assert await verifier_body(pg_factory, close=True) == old_close
    await migrate(pg_factory, 'upgrade', '0200')
    assert await verifier_body(pg_factory) == new_body
    assert await verifier_body(pg_factory, close=True) == new_close


@pytest.mark.parametrize('material', [None, '10.01'])
async def test_policy_shape_strict_verification_and_new_history_blocks_downgrade(issuance_pg, pg_book, material):
    api, factory = issuance_pg
    policy, order, production = await prepare(api, factory, pg_book, material)
    command, result = await reviewed(factory, pg_book[0], policy, order, production)
    settings = result['snapshot']['source']['snapshot']['settings']
    assert len(settings) == 8 and settings['material_inventory_account'] == material
    expected = [['20', 'debit', {'department': 'SHOP', 'order': f'ORDER-{order}'}, 3.33],
                ['25', 'credit', {'department': 'SHOP'}, 3.33]]
    assert await verify(factory, pg_book[0], policy, command, result) == expected
    for shape, accepted in [('legacy', material is None), ('wrong_material', False), ('unknown_key', False),
                            ('missing_reference', False), ('missing_finished_goods', False)]:
        changed = deepcopy(result)
        saved = changed['snapshot']['source']
        variant = saved['snapshot']['settings']
        if shape == 'legacy':
            del variant['material_inventory_account']
        elif shape == 'wrong_material':
            variant['material_inventory_account'] = '10.99'
        elif shape == 'unknown_key':
            variant['unapproved_role'] = None
        elif shape == 'missing_reference':
            del variant['reference']
        else:
            del variant['finished_goods_account']
        saved['digest'] = sha(saved['snapshot'])
        changed_command = command.model_copy(update={'expected_source_digest': saved['digest']})
        changed['snapshot']['review'] = changed_command.model_dump(mode='json')
        changed['digest'] = sha(changed['snapshot'])
        if accepted:
            assert await verify(factory, pg_book[0], policy, changed_command, changed) == expected
        else:
            with pytest.raises(DBAPIError, match='Invalid production overhead policy or review structure'):
                await verify(factory, pg_book[0], policy, changed_command, changed)
    confirmation = ProductionOverheadConfirm(request_key=uuid4(), review=command, expected_review_digest=result['digest'],
        posting_date='2026-10-31', evidence='Synthetic reviewed current overhead policy')
    async with factory() as session:
        row = await confirm_overhead(session, pg_book[0], '2026-10', confirmation, 'tester', production)
        entry_id = row.entry_id
        await session.commit()
    async with factory() as session:
        await session.execute(text('SELECT accounting.assert_production_overhead_current(:org, :month)'),
                              {'org': pg_book[0], 'month': '2026-10'})
    before = await raw_history(factory)
    before_body = await verifier_body(factory)
    await migrate(factory, 'downgrade', '0199', error='Material-role overhead history prevents downgrade')
    assert await raw_history(factory) == before
    assert await verifier_body(factory) == before_body
    async with factory() as session:
        replay = await confirm_overhead(session, pg_book[0], '2026-10', confirmation, 'tester', production)
        assert replay.entry_id == entry_id
        await session.commit()
    assert await raw_history(factory) == before
    # Saved review bytes are still protected by the original immutable trigger.
    async with factory() as session:
        with pytest.raises(DBAPIError):
            await session.execute(text("UPDATE accounting.production_overhead_receipt SET review='{}'::json"))
        await session.rollback()


@pytest.mark.parametrize('accounting_pg_revision', ['0199'], indirect=True)
async def test_legacy_review_survives_upgrade_roundtrip_and_new_revision_blocks_downgrade(issuance_pg, pg_book, monkeypatch):
    api, factory = issuance_pg
    policy, order, production = await prepare(api, factory, pg_book, None)

    async def legacy_sources(*args, **kwargs):
        # Reproduce the frozen seven-field source format using the real ledger,
        # not a forged receipt or disabled admission/immutability trigger.
        source = await cost_sources(*args, **kwargs)
        assert source['snapshot']['settings'].pop('material_inventory_account') is None
        source['digest'] = sha(source['snapshot'])
        return source

    with monkeypatch.context() as patch:
        patch.setattr(review_module, 'cost_sources', legacy_sources)
        command, result = await reviewed(factory, pg_book[0], policy, order, production, source_reader=legacy_sources)
        confirmation = ProductionOverheadConfirm(request_key=uuid4(), review=command, expected_review_digest=result['digest'],
            posting_date='2026-10-31', evidence='Synthetic reviewed legacy overhead policy')
        async with factory() as session:
            row = await confirm_overhead(session, pg_book[0], '2026-10', confirmation, 'tester', production)
            entry_id = row.entry_id
            await session.commit()
    async with factory() as session:
        await session.execute(text('SELECT accounting.assert_production_overhead_current(:org, :month)'),
                              {'org': pg_book[0], 'month': '2026-10'})
    before = await raw_history(factory)
    assert len(before) == 1
    assert 'material_inventory_account' not in json.loads(before[0][0])['snapshot']['source']['snapshot']['settings']
    old_body = await verifier_body(factory)
    await migrate(factory, 'upgrade', '0200')
    new_body = await verifier_body(factory)
    async with factory() as session:
        await session.execute(text('SELECT accounting.assert_production_overhead_current(:org, :month)'),
                              {'org': pg_book[0], 'month': '2026-10'})
    assert await verify(factory, pg_book[0], policy, command, result, excluded=[entry_id]) == [
        ['20', 'debit', {'department': 'SHOP', 'order': f'ORDER-{order}'}, 3.33],
        ['25', 'credit', {'department': 'SHOP'}, 3.33]]
    async with factory() as session:
        assert (await confirm_overhead(session, pg_book[0], '2026-10', confirmation, 'tester', production)).entry_id == entry_id
        await session.commit()
    assert await raw_history(factory) == before
    await migrate(factory, 'downgrade', '0199')
    assert await verifier_body(factory) == old_body and await raw_history(factory) == before
    await migrate(factory, 'upgrade', '0200')
    assert await verifier_body(factory) == new_body and await raw_history(factory) == before
    # A new zero-delta revision has eight-field evidence even though its original
    # receipt is legacy. The revision alone must prevent an unsafe downgrade.
    updated_command, updated_review = await reviewed(factory, pg_book[0], policy, order, production, correction_of=entry_id)
    preview_command = ProductionOverheadCorrectionPreview(original_entry_id=entry_id, review=updated_command,
        expected_review_digest=updated_review['digest'], method='delta', posting_date='2026-10-31',
        evidence='Synthetic reviewed unchanged overhead correction')
    async with factory() as session:
        preview = await preview_correction(session, pg_book[0], '2026-10', preview_command, production)
        assert preview['snapshot']['correction_lines'] == []
        correction = ProductionOverheadCorrectionConfirm(request_key=uuid4(), preview=preview_command,
                                                         expected_preview_digest=preview['digest'])
        revision = await confirm_correction(session, pg_book[0], '2026-10', correction, 'tester', production)
        assert revision.entry_id is None
        await session.commit()
    await migrate(factory, 'downgrade', '0199', error='Material-role overhead history prevents downgrade')
    assert await verifier_body(factory) == new_body and await raw_history(factory) == before
    async with factory() as session:
        assert await session.scalar(text('SELECT count(*) FROM accounting.production_overhead_revision')) == 1
