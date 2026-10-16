# ruff: noqa: F811 -- disposable PostgreSQL fixtures
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_production_cost_policy import body, seed
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401


async def test_production_policy_public_postgres_version(issuance_pg, pg_book):
    api, factory = issuance_pg
    api.headers['X-User'] = 'tester'
    async with factory() as session:
        # pg_book copies explicit IDs from SQLite; advance only this disposable fixture's sequences.
        await session.execute(text("SELECT setval(pg_get_serial_sequence('accounting.account','id'), (SELECT max(id) FROM accounting.account))"))
        await session.execute(text("SELECT setval(pg_get_serial_sequence('accounting.policy','id'), (SELECT max(id) FROM accounting.policy))"))
        await seed(session, pg_book[0])
    path = f'/accounting/organizations/{pg_book[0]}/policies'
    created = await api.post(path, json=body())
    assert created.status_code == 201, created.text
    assert created.json()['production_costing'] == body()['production_costing']
    versions = await api.get(path)
    assert versions.status_code == 200, versions.text
    assert next(p for p in versions.json() if p['id'] == pg_book[1])['production_costing'] is None
    async with factory() as session:
        with pytest.raises(DBAPIError, match='immutable'):
            await session.execute(text("UPDATE accounting.policy SET production_costing=NULL WHERE id=:id"),
                {'id': created.json()['id']})
        await session.rollback()


async def test_production_cost_sources_on_postgres(issuance_pg, pg_book, monkeypatch):
    from tests.accounting.test_production_cost_sources import (
        test_dated_cost_sources_keep_opening_credits_and_document_evidence as scenario,
    )

    api, factory = issuance_pg
    api.headers['X-User'] = 'tester'
    async with factory() as session:
        await session.execute(text("SELECT setval(pg_get_serial_sequence('accounting.account','id'), (SELECT max(id) FROM accounting.account))"))
        await session.execute(text("SELECT setval(pg_get_serial_sequence('accounting.policy','id'), (SELECT max(id) FROM accounting.policy))"))
        await session.commit()
        await scenario(api, session, pg_book)
    from core.services.auth import CurrentUser
    from modules.accounting.gateway import AccountingService
    from modules.production.accounting_ownership import (
        OwnershipCommand,
        assign_order,
        order_snapshot,
    )
    from modules.production.models import ProductionOrder
    async with factory() as session:
        order = ProductionOrder(number='COST-REVIEW', product='Synthetic cost target', qty=5)
        session.add(order)
        await session.flush()
        await assign_order(session, AccountingService(), pg_book[0], CurrentUser('tester', ['director']),
            OwnershipCommand(order_id=order.id, expected_digest=order_snapshot(order)[1], evidence='Reviewed synthetic cost owner'))
        await session.commit()
    prefix = f'/accounting/organizations/{pg_book[0]}'
    policies = (await api.get(prefix + '/policies')).json()
    policy_id = next(p['id'] for p in policies if p['production_costing'])
    source = (await api.get(prefix + f'/periods/2026-10/production-cost-sources?policy_id={policy_id}')).json()
    command = {'policy_id': policy_id, 'expected_source_digest': source['digest'],
        'classifications': [{'line_id': line['line_id'], 'role': 'direct_cost' if line['source'] == 'materials'
            else 'overhead' if line['source'] == 'overhead' else 'excluded', 'evidence': 'Synthetic reviewed line purpose'}
            for line in source['snapshot']['lines']],
        'orders': [{'analytical_order': '7', 'order_id': order.id, 'evidence': 'Synthetic accounting to production mapping'}]}
    path = prefix + '/periods/2026-10/production-cost-review'
    from sqlalchemy import func, select

    from modules.accounting.models import Entry
    async with factory() as session:
        before_count = await session.scalar(select(func.count()).select_from(Entry))
    result = await api.post(path, json=command)
    assert result.status_code == 200, result.text
    assert result.headers['cache-control'] == 'private, no-store'
    snapshot = result.json()['snapshot']
    assert snapshot['production_orders'][0]['order_id'] == order.id
    assert snapshot['allocations'][0]['allocation']['shares'][0]['amount_byn'] == '33.33'
    assert snapshot['posted'] is False and snapshot['final_cost_certified'] is False
    for broken in [
        {**command, 'expected_source_digest': '0' * 64},
        {**command, 'classifications': command['classifications'][1:]},
        {**command, 'orders': [{**command['orders'][0], 'order_id': 999999}]},
    ]:
        response = await api.post(path, json=broken)
        assert response.status_code == 422, response.text
    invalid_opening = [dict(row) for row in command['classifications']]
    opening_line = next(line['line_id'] for line in source['snapshot']['lines'] if line['opening'])
    next(row for row in invalid_opening if row['line_id'] == opening_line)['role'] = 'direct_cost'
    response = await api.post(path, json={**command, 'classifications': invalid_opening})
    assert response.status_code == 422 and 'Opening and earlier' in response.text
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Entry)) == before_count
    from uuid import uuid4

    from modules.accounting.models import ProductionOverheadReceipt
    from modules.accounting.production_cost_posting import (
        ProductionOverheadConfirm,
        confirm_overhead,
    )
    from modules.accounting.service import AccountingError
    confirm = ProductionOverheadConfirm(request_key=uuid4(), review=command, expected_review_digest=result.json()['digest'],
        posting_date='2026-10-31', evidence='Synthetic reviewed overhead confirmation')
    production = api._transport.app.state.core.services.production_output
    from datetime import date
    async with factory() as session:
        with pytest.raises(AccountingError, match='cannot precede'):
            await confirm_overhead(session, pg_book[0], '2026-10', confirm.model_copy(update={'posting_date': date(2026, 10, 1)}), 'tester', production)
        await session.rollback()
    async with factory() as session:
        await confirm_overhead(session, pg_book[0], '2026-10', confirm, 'tester', production)
        await session.rollback()
        assert await session.scalar(select(func.count()).select_from(Entry)) == before_count
        assert await session.scalar(select(func.count()).select_from(ProductionOverheadReceipt)) == 0
    from decimal import Decimal

    from modules.accounting import production_cost_posting as posting_module
    original_candidate = posting_module.posting_candidate
    original_review = posting_module.review_costs
    for field, message in [('balance', 'saved balances differ'), ('basis', 'saved allocation differs')]:
        async def forged_display(*args, changed=field):
            reviewed = await original_review(*args)
            snapshot = reviewed['snapshot']
            if changed == 'balance':
                snapshot['source']['snapshot']['balances'][0]['closing_byn'] = '999.99'
            else:
                snapshot['allocations'][0]['allocation']['shares'][0]['basis_amount'] = '999.000000'
            return reviewed
        with monkeypatch.context() as patch:
            patch.setattr(posting_module, 'review_costs', forged_display)
            async with factory() as session:
                with pytest.raises(DBAPIError, match=message):
                    await confirm_overhead(session, pg_book[0], '2026-10', confirm, 'tester', production)
                    await session.commit()
                await session.rollback()
    async def forged_order_review(*args):
        reviewed = await original_review(*args)
        reviewed['snapshot']['production_orders'][0]['product'] = 'Forged product title'
        return reviewed
    with monkeypatch.context() as patch:
        patch.setattr(posting_module, 'review_costs', forged_order_review)
        async with factory() as session:
            with pytest.raises(DBAPIError, match='order snapshot differs from its source'):
                await confirm_overhead(session, pg_book[0], '2026-10', confirm, 'tester', production)
                await session.commit()
            await session.rollback()
    def forged_balanced_candidate(*args):
        candidate = original_candidate(*args)
        return candidate.model_copy(update={'lines': [line.model_copy(update={'amount': Decimal('99.99')}) for line in candidate.lines]})
    with monkeypatch.context() as patch:
        patch.setattr(posting_module, 'posting_candidate', forged_balanced_candidate)
        async with factory() as session:
            with pytest.raises(DBAPIError, match='independently allocated ledger costs'):
                await confirm_overhead(session, pg_book[0], '2026-10', confirm, 'tester', production)
                await session.commit()
            await session.rollback()
            assert await session.scalar(select(func.count()).select_from(Entry)) == before_count
    async with factory() as session:
        receipt = await confirm_overhead(session, pg_book[0], '2026-10', confirm, 'tester', production)
        await session.commit()
        entry_id = receipt.entry_id
    async with factory() as session:
        replay = await confirm_overhead(session, pg_book[0], '2026-10', confirm, 'tester', production)
        assert replay.entry_id == entry_id
        await session.commit()
        assert await session.scalar(select(func.count()).select_from(Entry)) == before_count + 1
        with pytest.raises(AccountingError, match='already allocated'):
            await confirm_overhead(session, pg_book[0], '2026-10', confirm.model_copy(update={'request_key': uuid4()}), 'tester', production)
        await session.rollback()
    async with factory() as session:
        with pytest.raises(DBAPIError, match='immutable'):
            await session.execute(text('DELETE FROM accounting.production_overhead_receipt'))
        await session.rollback()
