"""Opt-in browser -> actual HTTP API -> disposable PostgreSQL, with startup migrations disabled."""
# ruff: noqa: F811 -- imported disposable fixtures
import asyncio
import os
import socket
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest
import uvicorn
from sqlalchemy import func, select

from core.domain.models import OutboxEvent, Sku
from core.services.auth import CurrentUser
from modules.accounting import service as accounting
from modules.accounting.gateway import AccountingService
from modules.accounting.models import Period, SourceControl
from modules.accounting.schemas import CloseInput
from modules.production.accounting_ownership import OwnershipCommand, assign_order, order_snapshot
from modules.production.models import ProductionOrder
from modules.production.order_completion import OrderCompletion
from modules.production.output_documents import OutputConfirmation, OutputDocument
from modules.wms.models import Location, Receipt, ReceiptLine, StockMovement
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401


@pytest.mark.skipif(os.environ.get('ACCOUNTING_BROWSER_TEST') != '1', reason='Explicit local browser opt-in required')
async def test_browser_output_to_postgres(issuance_pg, pg_book):
    api, factory = issuance_pg
    api.headers['X-User'] = 'tester'
    async with factory() as session:
        order = ProductionOrder(number='BROWSER-ORDER', product='Synthetic browser output', qty=3)
        session.add_all([order, Sku(code='BROWSER-OUTPUT', title='Browser product', unit='шт'),
            Location(warehouse='Browser warehouse', code='BROWSER-RECEIVING')])
        await session.flush()
        await assign_order(session, AccountingService(), pg_book[0], CurrentUser('tester', ['director']),
            OwnershipCommand(order_id=order.id, expected_digest=order_snapshot(order)[1], evidence='Synthetic browser ownership'))
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
        root = Path(__file__).resolve().parents[2]
        result = await asyncio.to_thread(subprocess.run, ['node', '.harness/tools/production_output_live_browser.mjs',
            f'http://127.0.0.1:{port}', str(pg_book[0]), str(order.id)], cwd=root,
            capture_output=True, text=True, encoding='utf-8', timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(OutputDocument)) == 1
            assert await session.scalar(select(func.count()).select_from(OutputConfirmation)) == 1
            assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 1
            assert await session.scalar(select(func.count()).select_from(StockMovement)) == 0
            document = await session.scalar(select(OutputDocument))
            control = await session.scalar(select(SourceControl).where(SourceControl.source == f'production:output:{document.id}'))
            assert control.organization_id == pg_book[0] and control.month == '2026-09'
            assert control.version == 1 and control.entry_id is None
            period = await session.scalar(select(Period).where(Period.organization_id == pg_book[0], Period.month == '2026-09'))
            assert period.generation == 1
            with pytest.raises(accounting.AccountingError, match='Unposted primary documents prevent closing'):
                await accounting.validate_close_period(session, pg_book[0], '2026-09', CloseInput(
                    expected_generation=period.generation,
                    evidence={step: 'Synthetic closing review' for step in accounting.CLOSE_STEPS}))
        assert await app.state.core.event_bus.relay_pending(factory, app.state.core.services,
            event_types=('production.output.confirmed',)) == 1
        async with factory() as session:
            receipt = await session.scalar(select(Receipt))
            line = await session.scalar(select(ReceiptLine))
            assert receipt.organization_id == pg_book[0] and receipt.status == 'pending_qc'
            assert line.expected_qty == Decimal('3.00') and line.batch_ref == 'BROWSER-LOT'
            assert await session.scalar(select(func.count()).select_from(StockMovement)) == 0
            receipt_id, line_id = receipt.id, line.id
        path = f'/wms/receipts/{receipt_id}'
        detail = await api.get(path)
        assert detail.status_code == 200, detail.text
        qc = await api.post(path + '/qc', json={'expected_revision': detail.json()['qc_revision'], 'decisions': [
            {'line_id': line_id, 'accepted_qty': '3.00', 'rejected_qty': '0.00', 'reject_reason': ''}]})
        assert qc.status_code == 200, qc.text
        accepted = await api.post(path + '/accept')
        assert accepted.status_code == 200, accepted.text
        completion = await asyncio.to_thread(subprocess.run, ['node', '.harness/tools/production_output_live_browser.mjs',
            f'http://127.0.0.1:{port}', str(pg_book[0]), str(order.id), 'completion'], cwd=root,
            capture_output=True, text=True, encoding='utf-8', timeout=90)
        assert completion.returncode == 0, completion.stdout + completion.stderr
        async with factory() as session:
            final_order = await session.get(ProductionOrder, order.id)
            stored = await session.get(OrderCompletion, order.id)
            assert final_order.stage == 'done' and final_order.made_qty == 3 and final_order.progress == 100
            assert stored.actor == 'tester' and stored.organization_id == pg_book[0]
            assert stored.command['operation_date'] == '2026-09-12'
            assert await session.scalar(select(func.count()).select_from(OrderCompletion)) == 1
            assert await session.scalar(select(func.count()).select_from(StockMovement)) == 1
            assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 1
            assert await session.scalar(select(func.count()).select_from(SourceControl)) == 1
            period = await session.scalar(select(Period).where(Period.organization_id == pg_book[0], Period.month == '2026-09'))
            assert period.generation == 1 and not period.closed
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=10)
        listener.close()
