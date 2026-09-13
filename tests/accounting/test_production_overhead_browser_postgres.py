"""Actual accountant form -> local HTTP -> PostgreSQL, including lost commit response."""
# ruff: noqa: F811 -- imported disposable fixtures
import asyncio
import os
import socket
import subprocess
from pathlib import Path

import pytest
import uvicorn
from sqlalchemy import func, select, text

from core.services.auth import CurrentUser
from modules.accounting import service
from modules.accounting.gateway import AccountingService
from modules.accounting.models import (
    Entry,
    Line,
    Period,
    ProductionOverheadReceipt,
    ProductionOverheadRevision,
    ProductionOverheadWithdrawal,
)
from modules.accounting.schemas import PostingInput
from modules.production.accounting_ownership import OwnershipCommand, assign_order, order_snapshot
from modules.production.models import ProductionOrder
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_production_cost_policy import body, seed
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401


@pytest.mark.skipif(os.environ.get('ACCOUNTING_BROWSER_TEST') != '1', reason='Explicit local browser opt-in required')
@pytest.mark.parametrize('mode', ['confirm', 'withdraw', 'correction'])
async def test_browser_overhead_confirmation_recovery(issuance_pg, pg_book, mode):
    api, factory = issuance_pg
    api.headers['X-User'] = 'tester'
    async with factory() as session:
        await session.execute(text("SELECT setval(pg_get_serial_sequence('accounting.account','id'), (SELECT max(id) FROM accounting.account))"))
        await session.execute(text("SELECT setval(pg_get_serial_sequence('accounting.policy','id'), (SELECT max(id) FROM accounting.policy))"))
        await seed(session, pg_book[0])
    policy = await api.post(f'/accounting/organizations/{pg_book[0]}/policies', json=body())
    assert policy.status_code == 201, policy.text
    policy_id = policy.json()['id']
    async with factory() as session:
        order = ProductionOrder(number='ПР-7', product='Учебный блок управления', qty=1)
        session.add(order)
        await session.flush()
        await assign_order(session, AccountingService(), pg_book[0], CurrentUser('tester', ['director']),
            OwnershipCommand(order_id=order.id, expected_digest=order_snapshot(order)[1], evidence='Synthetic browser cost target'))
        for account, amount, day in [('20', '100.01', '02'), ('25', '33.33', '03')]:
            dimensions = {'department': 'Сборочный участок'} | ({'order': 'ЗАК-7'} if account == '20' else {})
            await service.post(session, pg_book[0], PostingInput(source=f'BROWSER-COST-{account}', source_version=1,
                operation='manual', document_date=f'2026-10-{day}', operation_date=f'2026-10-{day}', posting_date=f'2026-10-{day}',
                policy_id=policy_id, rule_version='synthetic', explanation='Synthetic browser cost source', lines=[
                    {'account': account, 'side': 'debit', 'amount': amount, 'dimensions': dimensions},
                    {'account': '60', 'side': 'credit', 'amount': amount}]), 'tester')
        generation = (await service.period_for(session, pg_book[0], '2026-10')).generation
        await session.commit()
    app = api._transport.app
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, lifespan='off', log_level='error'))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        for _ in range(100):
            if server.started:
                break
            if task.done():
                await task
                pytest.fail('HTTP test server stopped before readiness')
            await asyncio.sleep(.05)
        assert server.started
        result = await asyncio.to_thread(subprocess.run, ['node', '.harness/tools/production_overhead_browser.mjs',
            f'http://127.0.0.1:{port}', str(pg_book[0]), str(policy_id), str(order.id), mode],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, encoding='utf-8', timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
        async with factory() as session:
            if mode == 'withdraw':
                assert await session.scalar(select(func.count()).select_from(ProductionOverheadReceipt)) == 0
                assert await session.scalar(select(func.count()).select_from(Entry).where(Entry.operation == 'production_overhead')) == 0
                assert await session.scalar(select(func.count()).select_from(ProductionOverheadWithdrawal)) == 1
                withdrawal = await session.scalar(select(ProductionOverheadWithdrawal))
                assert withdrawal.organization_id == pg_book[0] and withdrawal.actor == 'tester'
                assert withdrawal.command['review']['policy_id'] == policy_id
                assert withdrawal.reason == 'Запрос отозван для повторной проверки документов'
                period = await session.scalar(select(Period).where(Period.organization_id == pg_book[0], Period.month == '2026-10'))
                assert period.generation == generation and not period.closed
                return
            assert await session.scalar(select(func.count()).select_from(ProductionOverheadReceipt)) == 1
            receipt = await session.scalar(select(ProductionOverheadReceipt))
            assert receipt.organization_id == pg_book[0] and receipt.actor == 'tester' and receipt.month == '2026-10'
            assert receipt.command['posting_date'] == '2026-10-31'
            assert receipt.command['review']['orders'][0]['order_id'] == order.id
            assert receipt.command['review']['policy_id'] == policy_id
            assert await session.scalar(select(func.count()).select_from(Entry).where(Entry.operation == 'production_overhead')) == 1
            lines = (await session.scalars(select(Line).where(Line.entry_id == receipt.entry_id))).all()
            assert sorted((line.account_code, line.side, str(line.amount)) for line in lines) == [('20', 'debit', '33.33'), ('25', 'credit', '33.33')]
            debit = next(line for line in lines if line.side == 'debit')
            assert debit.dimensions == {'department': 'Сборочный участок', 'order': 'ЗАК-7'}
            period = await session.scalar(select(Period).where(Period.organization_id == pg_book[0], Period.month == '2026-10'))
            assert period.generation == generation + (4 if mode == 'correction' else 1) and not period.closed
            if mode == 'correction':
                assert await session.scalar(select(func.count()).select_from(Entry)) == 5
                revisions = (await session.scalars(select(ProductionOverheadRevision).order_by(ProductionOverheadRevision.sequence))).all()
                assert len(revisions) == 2 and revisions[1].entry_id is None and revisions[1].previous_id == revisions[0].id
                correction_lines = (await session.scalars(select(Line).where(Line.entry_id == revisions[0].entry_id))).all()
                assert sorted((line.account_code, line.side, str(line.amount)) for line in correction_lines) == [('20', 'credit', '33.33'), ('25', 'debit', '33.33')]
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=10)
        listener.close()
