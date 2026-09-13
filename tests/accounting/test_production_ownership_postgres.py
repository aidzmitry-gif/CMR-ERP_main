# ruff: noqa: F811 -- existing disposable database fixtures
import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from core.services.auth import CurrentUser
from modules.accounting.gateway import AccountingService
from modules.production.accounting_ownership import (
    OwnershipCommand,
    ProductionOrderOwnership,
    assign_order,
    order_snapshot,
)
from modules.production.models import ProductionOrder
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401


async def test_output_accounting_source_sql_binding(issuance_pg, pg_book):
    from uuid import uuid4

    from core.domain.models import OutboxEvent, Sku
    from modules.accounting.models import Period, SourceControl
    from modules.production.output_documents import (
        OutputCommand,
        OutputConfirmation,
        confirm_output,
        prepare_output,
    )
    from modules.wms.models import Location

    api, factory = issuance_pg
    warehouse = api._transport.app.state.core.services.wms_reservations
    gateway, user = AccountingService(), CurrentUser('tester', ['director'])
    async with factory() as session:
        order = ProductionOrder(number='SOURCE-GUARD', product='Synthetic output', qty=1)
        place = Location(warehouse='Main', code='SOURCE-GUARD')
        session.add_all([order, place, Sku(code='SOURCE-GUARD', title='Synthetic output', unit='шт')])
        await session.flush()
        digest = order_snapshot(order)[1]
        await assign_order(session, gateway, pg_book[0], user, OwnershipCommand(
            order_id=order.id, expected_digest=digest, evidence='Synthetic reviewed owner'))
        document = await prepare_output(session, gateway, pg_book[0], user, OutputCommand(
            request_id=uuid4(), order_id=order.id, expected_order_digest=digest,
            operation_date='2026-09-12', sku_code='SOURCE-GUARD', quantity='1.00', warehouse='Main',
            location_id=place.id, lot='SOURCE-LOT', evidence='Synthetic output source'), warehouse_gateway=warehouse)
        await session.commit()

    class MissingSource(AccountingService):
        async def source_changed(self, *args, **kwargs):
            pass  # Simulates a caller bypassing application completeness registration.

    async with factory() as session:
        with pytest.raises(DBAPIError, match='requires its pending accounting source'):
            await confirm_output(session, MissingSource(), pg_book[0], user, document.id, document.digest,
                warehouse_gateway=warehouse)
        await session.rollback()
        assert await session.scalar(select(func.count()).select_from(OutputConfirmation)) == 0
        assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 0
        assert await session.scalar(select(func.count()).select_from(SourceControl)) == 0
    async with factory() as session:
        await confirm_output(session, gateway, pg_book[0], user, document.id, document.digest, warehouse_gateway=warehouse)
        await session.commit()
    for sql, message in [
        ("UPDATE accounting.source_control SET version=2, month='2026-10'", 'differs from its document'),
        ("TRUNCATE accounting.source_control", 'cannot be truncated'),
    ]:
        async with factory() as session:
            with pytest.raises(DBAPIError, match=message):
                await session.execute(text(sql))
                await session.commit()
            await session.rollback()
    async with factory() as session:
        await confirm_output(session, gateway, pg_book[0], user, document.id, document.digest, warehouse_gateway=warehouse)
        await session.commit()
        control = await session.scalar(select(SourceControl))
        period = await session.scalar(select(Period).where(Period.month == '2026-09'))
        assert control.source == f'production:output:{document.id}' and control.version == 1
        assert control.month == '2026-09' and control.entry_id is None and period.generation == 1


async def test_production_ownership_exact_concurrent_replay_and_stale_snapshot(pg_factory, pg_book):
    gateway, user = AccountingService(), CurrentUser("tester", ["director"])
    async with pg_factory() as session:
        order = ProductionOrder(number="SYN-PRO-1", product="Synthetic product", qty=3)
        session.add(order)
        await session.flush()
        order_id = order.id
        snapshot, digest = order_snapshot(order)
        await session.commit()
    command = OwnershipCommand(order_id=order_id, expected_digest=digest, evidence="Synthetic ownership reviewed")

    async def assign():
        async with pg_factory() as session:
            row = await assign_order(session, gateway, pg_book[0], user, command)
            await session.commit()
            return row.order_id, row.snapshot, row.digest

    first, second = await asyncio.gather(assign(), assign())
    assert first == second == (order_id, snapshot, digest)
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProductionOrderOwnership)) == 1

        with pytest.raises(HTTPException) as conflict:
            await assign_order(session, gateway, pg_book[0], user, command.model_copy(update={"evidence": "Other reviewed decision"}))
        assert conflict.value.status_code == 409
        with pytest.raises(HTTPException) as unauthorized:
            await assign_order(session, gateway, pg_book[0] + 999, user, command)
        assert unauthorized.value.status_code == 403
        other = ProductionOrder(number="SYN-PRO-2", product="Before", qty=1)
        session.add(other)
        await session.flush()
        stale = OwnershipCommand(order_id=other.id, expected_digest=order_snapshot(other)[1], evidence="Synthetic old snapshot")
        other.product = "After"
        await session.commit()
        with pytest.raises(HTTPException) as changed:
            await assign_order(session, gateway, pg_book[0], user, stale)
        assert changed.value.status_code == 409
        assert await session.get(ProductionOrderOwnership, other.id) is None
    for statement in ("UPDATE production.order_ownership SET actor='changed'",
                      "DELETE FROM production.order_ownership", "TRUNCATE production.order_ownership CASCADE"):
        async with pg_factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(text(statement))
            await session.rollback()
    async with pg_factory() as session:
        with pytest.raises(DBAPIError, match="snapshot does not match"):
            await session.execute(text("INSERT INTO production.order_ownership "
                "(order_id,organization_id,snapshot,digest,evidence,actor) "
                "SELECT :other,organization_id,snapshot,digest,evidence,actor FROM production.order_ownership WHERE order_id=:original"),
                {"other": other.id, "original": order_id})
        await session.rollback()
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProductionOrderOwnership)) == 1


async def test_production_ownership_public_review_and_confirm(issuance_pg, pg_book):
    api, factory = issuance_pg
    api.headers["X-User"] = "tester"
    async with factory() as session:
        order = ProductionOrder(number="SYN-API", product="Synthetic product", qty=2)
        session.add(order)
        await session.commit()
        order_id = order.id
    base = f"/production/organizations/{pg_book[0]}"
    preview = await api.get(f"{base}/orders/{order_id}/ownership-preview")
    assert preview.status_code == 200, preview.text
    assert preview.json()["principal"] == "tester" and not preview.json()["assigned"]
    command = {"order_id": order_id, "expected_digest": preview.json()["digest"], "evidence": "Synthetic reviewed organization"}
    assert (await api.post(base + "/order-ownership", json=command)).status_code == 422
    assert (await api.post(base + "/order-ownership", json=command, headers={"X-Expected-Principal": "other"})).status_code == 409
    posted = await api.post(base + "/order-ownership", json=command, headers={"X-Expected-Principal": "tester"})
    assert posted.status_code == 200, posted.text
    assert posted.headers["cache-control"] == "private, no-store"
    repeated = await api.post(base + "/order-ownership", json=command, headers={"X-Expected-Principal": "tester"})
    assert repeated.status_code == 200 and repeated.json() == posted.json(), repeated.text
    current = await api.get(f"{base}/orders/{order_id}/ownership-preview")
    assert current.status_code == 200 and current.json()["assigned"], current.text
    assert current.json()["ownership"] == posted.json()
    assert (await api.patch(f'/production/orders/{order_id}', json={'stage': 'done'})).status_code == 409
    path = base + f'/orders/{order_id}'
    headers = {'X-Expected-Principal': 'tester'}
    assert (await api.patch(path, json={'stage': 'invalid'}, headers=headers)).status_code == 422
    assert (await api.patch(path, json={'stage': 'done'}, headers={'X-Expected-Principal': 'other'})).status_code == 409
    first, second = await asyncio.gather(*[api.patch(path, json={'stage': 'done'}, headers=headers) for _ in range(2)])
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    assert first.json() == second.json()
    async with factory() as session:
        from core.domain.models import OutboxEvent

        events = (await session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == 'production.completed'))).all()
        assert len(events) == 1 and events[0].payload['organization_id'] == pg_book[0]


async def test_production_ownership_public_company_and_role_isolation(issuance_pg, pg_book):
    from modules.accounting.models import AccessGrant, Organization

    api, factory = issuance_pg
    api.headers['X-User'] = 'tester'
    async with factory() as session:
        other = Organization(id=999, name='Synthetic other company', unp='987654321')
        order = ProductionOrder(number='SYN-PRIVATE', product='Private product', qty=2)
        session.add_all([other, order])
        await session.flush()
        other_id, order_id = other.id, order.id
        session.add(AccessGrant(id=999, organization_id=other_id, subject='tester', role='chief'))
        await session.commit()
    base = f'/production/organizations/{pg_book[0]}'
    path = f'/orders/{order_id}/ownership-preview'
    preview = await api.get(base + path)
    assert preview.status_code == 200, preview.text
    command = dict(order_id=order_id, expected_digest=preview.json()['digest'], evidence='Synthetic reviewed assignment')
    assigned = await api.post(base + '/order-ownership', json=command, headers={'X-Expected-Principal': 'tester'})
    assert assigned.status_code == 200, assigned.text
    from modules.production.models import ProductionPlan

    async with factory() as session:
        conn = await session.connection()
        await conn.run_sync(lambda c: ProductionPlan.__table__.create(c, checkfirst=True))
        session.add(ProductionPlan(year=2026, product='Original plan', month=1, plan_qty=5))
        await session.commit()
    assert (await api.put('/production/plan/cell', json=dict(year=2026, product='Original plan', month=1, plan_qty=99))).status_code == 409
    assert (await api.post('/production/plan/position', json=dict(year=2026, product='Original plan', monthly=[99] * 12))).status_code == 409
    assert (await api.delete('/production/plan/position', params=dict(year=2026, product='Original plan'))).status_code == 409
    async with factory() as session:
        rows = (await session.scalars(select(ProductionPlan))).all()
        assert len(rows) == 1 and rows[0].plan_qty == 5
    for legacy_path in ('/production/orders', '/production/board', '/production/plan', '/production/analytics'):
        legacy = await api.get(legacy_path)
        assert legacy.status_code == 409, (legacy_path, legacy.text)
        assert 'Private product' not in legacy.text
    foreign = await api.get(f'/production/organizations/{other_id}' + path)
    assert foreign.status_code == 404 and 'Private product' not in foreign.text
    headers = {'X-Expected-Principal': 'tester'}
    foreign_write = await api.patch(f'/production/organizations/{other_id}/orders/{order_id}',
        json={'stage': 'done'}, headers=headers)
    assert foreign_write.status_code == 404 and 'Private product' not in foreign_write.text
    api.headers['X-User'] = 'unassigned-user'
    denied = await api.get(base + path)
    assert denied.status_code == 403 and 'Private product' not in denied.text
    async with factory() as session:
        grant = await session.scalar(select(AccessGrant).where(
            AccessGrant.organization_id == pg_book[0], AccessGrant.subject == 'tester'))
        grant.role = 'reader'
        await session.commit()
    api.headers['X-User'] = 'tester'
    assert (await api.get(base + path)).status_code == 403
    assert (await api.post(base + '/order-ownership', json=command,
        headers={'X-Expected-Principal': 'tester'})).status_code == 403
    assert (await api.patch(base + f'/orders/{order_id}', json={'stage': 'done'}, headers=headers)).status_code == 403
    async with factory() as session:
        unmapped = ProductionOrder(number='UNMAPPED', product='Unassigned product', qty=1)
        session.add(unmapped)
        await session.commit()
        unmapped_id = unmapped.id
    for inaccessible_id in (unmapped_id, 999999):
        rejected = await api.patch(f'/production/organizations/{other_id}/orders/{inaccessible_id}',
            json={'stage': 'done'}, headers=headers)
        assert rejected.status_code == 404, rejected.text
    listing = await api.get(base + '/orders')
    assert listing.status_code == 200, listing.text
    access = await api.get(base + '/access')
    assert access.status_code == 200, access.text
    assert access.json() == dict(organization_id=pg_book[0], principal='tester', can_create=False, can_change_stage=False)
    assert access.headers['cache-control'] == 'private, no-store'
    companies = await api.get('/production/order-organizations')
    assert companies.status_code == 200, companies.text
    assert {row['id'] for row in companies.json()} == {pg_book[0], other_id}
    assert companies.headers['cache-control'] == 'private, no-store'
    assert [row['id'] for row in listing.json()] == [order_id]
    assert listing.headers['cache-control'] == 'private, no-store'
    board = await api.get(base + '/board')
    assert board.status_code == 200, board.text
    assert [card['id'] for stage in board.json()['stages'] for card in stage['cards']] == [order_id]
    assert (await api.get(f'/production/organizations/{other_id}/orders')).json() == []
    api.headers['X-User'] = 'unassigned-user'
    assert (await api.get(base + '/orders')).status_code == 403
    assert (await api.get(base + '/access')).status_code == 403
    assert (await api.get(base + '/board')).status_code == 403
    companies = await api.get('/production/order-organizations')
    assert companies.status_code == 200 and companies.json() == []
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProductionOrderOwnership)) == 1
        assert (await session.get(ProductionOrder, order_id)).stage == 'queue'
        assert (await session.get(ProductionOrder, unmapped_id)).stage == 'queue'
        from core.domain.models import OutboxEvent

        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.event_type == 'production.completed')) == 0



async def test_production_completion_concurrent_replay_emits_once(issuance_pg):
    from core.domain.models import OutboxEvent
    from core.services.eventbus import EventContext, OutboxEventBus
    from modules.wms.events import on_goods_received
    from modules.wms.models import Receipt, ReceiptLine, StockMovement

    api, factory = issuance_pg
    async with factory() as session:
        order = ProductionOrder(number='SYN-OUTPUT', product='Synthetic output', qty=3, stage='packing')
        session.add(order)
        await session.commit()
        order_id = order.id
    path = f'/production/orders/{order_id}'
    first, second = await asyncio.gather(
        api.patch(path, json={'stage': 'done'}), api.patch(path, json={'stage': 'done'}))
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    assert first.json() == second.json()
    replay = await api.patch(path, json={'stage': 'done'})
    assert replay.status_code == 200 and replay.json() == first.json()
    assert (await api.patch(path, json={'stage': 'packing'})).status_code == 409
    async with factory() as session:
        rows = (await session.scalars(select(OutboxEvent).where(
            OutboxEvent.event_type == 'production.completed'))).all()
        assert len(rows) == 1
        assert rows[0].payload['qty'] == 3
        stored = await session.get(ProductionOrder, order_id)
        assert stored.stage == 'done' and stored.made_qty == 3
        event_id, payload = rows[0].id, rows[0].payload
    async with factory() as session:
        with pytest.raises(ValueError, match='differs from its stored source event'):
            await on_goods_received({**payload, 'qty': 999}, EventContext(session, None, event_id=event_id))
        await session.rollback()
        assert await session.scalar(select(func.count()).select_from(Receipt)) == 0
    bus = OutboxEventBus()
    bus.subscribe('production.completed', on_goods_received)
    assert await bus.relay_pending(factory, None, event_types=('production.completed',)) == 1
    assert await bus.relay_pending(factory, None, event_types=('production.completed',)) == 0

    async def redeliver():
        async with factory() as session:
            await on_goods_received(payload, EventContext(session, None, event_id=event_id))
            await session.commit()

    await asyncio.gather(redeliver(), redeliver())
    for changed in ({**payload, 'qty': 999}, {**payload, 'organization_id': 999}):
        async with factory() as session:
            with pytest.raises(ValueError, match='differs from its stored source event'):
                await on_goods_received(changed, EventContext(session, None, event_id=event_id))
            await session.rollback()
    async with factory() as session:
        receipts = (await session.scalars(select(Receipt))).all()
        lines = (await session.scalars(select(ReceiptLine))).all()
        assert len(receipts) == len(lines) == 1
        assert receipts[0].source_event_id == event_id and receipts[0].status == 'pending_qc'
        assert receipts[0].source == 'production' and receipts[0].entity_ref == f'production:{order_id}'
        assert lines[0].expected_qty == 3 and lines[0].accepted_qty is None
        assert await session.scalar(select(func.count()).select_from(StockMovement)) == 0

async def test_production_completion_database_failure_rolls_back_then_retries(issuance_pg):
    from core.domain.models import OutboxEvent

    api, factory = issuance_pg
    async with factory() as session:
        order = ProductionOrder(number='SYN-ROLLBACK', product='Synthetic output', qty=4, stage='packing')
        session.add(order)
        await session.commit()
        order_id = order.id
        await session.execute(text("""
            CREATE FUNCTION reject_synthetic_production_event() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.event_type = 'production.completed' THEN
                    RAISE EXCEPTION 'synthetic production outbox failure';
                END IF;
                RETURN NEW;
            END $$
        """))
        await session.execute(text('CREATE TRIGGER reject_synthetic_production_event BEFORE INSERT ON outbox_event '
            'FOR EACH ROW EXECUTE FUNCTION reject_synthetic_production_event()'))
        await session.commit()
    path = f'/production/orders/{order_id}'
    with pytest.raises(DBAPIError, match='synthetic production outbox failure'):
        await api.patch(path, json={'stage': 'done'})
    async with factory() as session:
        stored = await session.get(ProductionOrder, order_id)
        assert stored.stage == 'packing' and stored.completed_at is None
        assert stored.made_qty == 0
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.event_type == 'production.completed')) == 0
        await session.execute(text('DROP TRIGGER reject_synthetic_production_event ON outbox_event'))
        await session.execute(text('DROP FUNCTION reject_synthetic_production_event()'))
        await session.commit()
    result = await api.patch(path, json={'stage': 'done'})
    assert result.status_code == 200, result.text
    async with factory() as session:
        stored = await session.get(ProductionOrder, order_id)
        assert stored.stage == 'done' and stored.made_qty == 4 and stored.completed_at is not None
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.event_type == 'production.completed')) == 1


async def test_production_creation_atomic_replay(pg_factory, pg_book):
    from uuid import uuid4

    from modules.production.models import ProductionNorm
    from modules.production.order_creation import (
        CreateOrderCommand,
        OrderCreationReceipt,
        create_order,
    )

    async with pg_factory() as session:
        conn = await session.connection()
        await conn.run_sync(lambda c: ProductionNorm.__table__.create(c, checkfirst=True))
        await session.commit()
    gateway, user = AccountingService(), CurrentUser('tester', ['director'])
    command = CreateOrderCommand(request_id=uuid4(), product='Synthetic atomic order', quantity=2,
        evidence='Synthetic reviewed creation')
    async with pg_factory() as session:
        await create_order(session, gateway, pg_book[0], user, command)
        await session.rollback()
    async with pg_factory() as session:
        for model in (ProductionOrder, ProductionOrderOwnership, OrderCreationReceipt):
            assert await session.scalar(select(func.count()).select_from(model)) == 0

    async def create():
        async with pg_factory() as session:
            result = await create_order(session, gateway, pg_book[0], user, command)
            await session.commit()
            return result

    first, second = await asyncio.gather(create(), create())
    assert first == second and first['qty'] == 2
    for statement in ('UPDATE production.order_creation_receipt SET actor=actor',
        'DELETE FROM production.order_creation_receipt', 'TRUNCATE production.order_creation_receipt'):
        async with pg_factory() as session:
            with pytest.raises(DBAPIError, match='immutable'):
                await session.execute(text(statement))
            await session.rollback()
    async with pg_factory() as session:
        with pytest.raises(DBAPIError, match='does not match its source'):
            await session.execute(text("INSERT INTO production.order_creation_receipt "
                "(order_id,organization_id,request_id,digest,actor,command,result) "
                "SELECT order_id,organization_id,request_id,digest,actor,command, "
                "result::jsonb || jsonb_build_object('qty',999) FROM production.order_creation_receipt"))
        await session.rollback()
    async with pg_factory() as session:
        for model in (ProductionOrder, ProductionOrderOwnership, OrderCreationReceipt):
            assert await session.scalar(select(func.count()).select_from(model)) == 1
        with pytest.raises(HTTPException) as conflict:
            await create_order(session, gateway, pg_book[0], user, command.model_copy(update={'quantity': 3}))
        assert conflict.value.status_code == 409
        order = await session.get(ProductionOrder, first['id'])
        order.stage = 'assembly'
        await session.commit()
    assert await create() == first


async def test_production_creation_public_replay(issuance_pg, pg_book):
    from uuid import uuid4

    from modules.production.models import ProductionNorm
    from modules.production.order_creation import OrderCreationReceipt

    api, factory = issuance_pg
    api.headers['X-User'] = 'tester'
    async with factory() as session:
        conn = await session.connection()
        await conn.run_sync(lambda c: ProductionNorm.__table__.create(c, checkfirst=True))
        await session.commit()
    path = f'/production/organizations/{pg_book[0]}/orders'
    access = await api.get(f'/production/organizations/{pg_book[0]}/access')
    assert access.status_code == 200 and access.json()['principal'] == 'tester'
    assert access.json()['can_create'] and access.json()['can_change_stage']
    command = dict(request_id=str(uuid4()), product='HTTP creation', quantity=3, evidence='Synthetic approved creation')
    assert (await api.post(path, json=command)).status_code == 422
    assert (await api.post(path, json=command, headers={'X-Expected-Principal': 'other'})).status_code == 409
    headers = {'X-Expected-Principal': 'tester'}
    first, second = await asyncio.gather(*[api.post(path, json=command, headers=headers) for _ in range(2)])
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    assert first.json() == second.json() and first.headers['cache-control'] == 'private, no-store'
    assert (await api.post(path, json={**command, 'quantity': 4}, headers=headers)).status_code == 409
    assert (await api.get(path)).json()[0]['id'] == first.json()['id']
    replay = await api.post(path, json=command, headers=headers)
    assert replay.status_code == 200 and replay.json() == first.json()
    receipt_path = f"/production/organizations/{pg_book[0]}/order-creations/{command['request_id']}"
    receipt = await api.get(receipt_path)
    assert receipt.status_code == 200, receipt.text
    assert receipt.headers['cache-control'] == 'private, no-store'
    assert receipt.json()['command'] == command and receipt.json()['result'] == first.json()
    assert receipt.json()['actor'] == 'tester' and receipt.json()['organization_id'] == pg_book[0]
    assert (await api.get(f'/production/organizations/{pg_book[0]}/order-creations/{uuid4()}')).status_code == 404
    changed = await api.patch(path + f"/{first.json()['id']}", json={'stage': 'assembly'}, headers=headers)
    assert changed.status_code == 200, changed.text
    assert (await api.get(receipt_path)).json() == receipt.json()
    api.headers['X-User'] = 'other'
    assert (await api.get(receipt_path)).status_code == 403
    assert (await api.post(path, json=command, headers={'X-Expected-Principal': 'other'})).status_code == 403
    async with factory() as session:
        for model in (ProductionOrder, ProductionOrderOwnership, OrderCreationReceipt):
            assert await session.scalar(select(func.count()).select_from(model)) == 1

async def test_production_receipt_unknown_sku_cannot_enter_stock(issuance_pg, pg_book):
    from modules.wms.models import Receipt, ReceiptLine, StockMovement, Task

    api, factory = issuance_pg
    api.headers['X-User'] = 'tester'
    async with factory() as session:
        receipt = Receipt(organization_id=pg_book[0], source='production', entity_ref='production:synthetic', warehouse='Main', status='pending_qc')
        session.add(receipt)
        await session.flush()
        receipt_id = receipt.id
        session.add(ReceiptLine(receipt_id=receipt_id, sku_code='UNKNOWN-SYNTHETIC', expected_qty=2, accepted_qty=2, rejected_qty=0))
        await session.commit()
    response = await api.post(f'/wms/receipts/{receipt_id}/accept')
    assert response.status_code == 409 and 'catalog SKU' in response.text, response.text
    async with factory() as session:
        assert (await session.get(Receipt, receipt_id)).status == 'pending_qc'
        for model in (StockMovement, Task):
            assert await session.scalar(select(func.count()).select_from(model)) == 0

async def test_production_receipt_explicit_qc_partial_acceptance(issuance_pg, pg_book):
    from core.domain.models import Sku
    from modules.wms.models import Receipt, ReceiptLine, StockMovement, Task

    api, factory = issuance_pg
    api.headers['X-User'] = 'tester'
    async with factory() as session:
        session.add(Sku(code='SYN-OUTPUT', title='Synthetic output'))
        receipt = Receipt(organization_id=pg_book[0], number='SYN-QC-1', source='production', entity_ref='production:synthetic', warehouse='Main', status='pending_qc')
        session.add(receipt)
        await session.flush()
        receipt_id = receipt.id
        line = ReceiptLine(receipt_id=receipt_id, sku_code='SYN-OUTPUT', expected_qty=3)
        session.add(line)
        await session.commit()
        line_id = line.id
    path = f'/wms/receipts/{receipt_id}'
    missing = await api.post(path + '/accept')
    assert missing.status_code == 409 and 'explicit QC' in missing.text, missing.text
    detail = await api.get(path)
    assert detail.status_code == 200, detail.text
    qc = await api.post(path + '/qc', json={'expected_revision': detail.json()['qc_revision'],
        'decisions': [{'line_id': line_id, 'accepted_qty': '2.00', 'rejected_qty': '1.00', 'reject_reason': 'Synthetic defect'}]})
    assert qc.status_code == 200, qc.text
    first, second = await asyncio.gather(api.post(path + '/accept'), api.post(path + '/accept'))
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    async with factory() as session:
        moves = (await session.scalars(select(StockMovement))).all()
        tasks = (await session.scalars(select(Task))).all()
        assert len(moves) == len(tasks) == 1
        assert moves[0].qty == tasks[0].qty == 2
        assert moves[0].organization_id == tasks[0].organization_id == pg_book[0]
        stored = await session.get(ReceiptLine, line_id)
        assert stored.rejected_qty == 1 and stored.accepted_qty == 2
        assert (await session.get(Receipt, receipt_id)).status == 'accepted'

async def test_production_output_preview_uses_explicit_catalog_and_stable_order(issuance_pg, pg_book):
    from uuid import uuid4

    from core.domain.models import Sku
    from modules.production.output_documents import (
        OutputCommand,
        OutputDocument,
        prepare_output,
        preview_output,
    )
    from modules.wms.models import Location
    from modules.wms.reservation_gateway import WmsReservationService

    _, factory = issuance_pg
    gateway, user = AccountingService(), CurrentUser('tester', ['director'])
    async with factory() as session:
        order = ProductionOrder(number='SYN-OUTPUT-PREVIEW', product='Planning title', qty=3)
        location = Location(warehouse='Main', code='RECEIVING', is_active=True)
        session.add_all([order, location, Sku(code='OUTPUT-SKU', title='Catalog product', unit='шт')])
        await session.flush()
        digest = order_snapshot(order)[1]
        await assign_order(session, gateway, pg_book[0], user, OwnershipCommand(order_id=order.id,
            expected_digest=digest, evidence='Synthetic approved owner'))
        command = OutputCommand(request_id=uuid4(), order_id=order.id, expected_order_digest=digest,
            operation_date='2026-09-12', sku_code='OUTPUT-SKU', quantity='2.00', warehouse='Main', location_id=location.id, lot='LOT-1', evidence='Synthetic reviewed output')
        wms = WmsReservationService()
        await session.commit()
        result = await preview_output(session, gateway, pg_book[0], user, command, warehouse_gateway=wms)
        assert result['receiving_place']['location_id'] == location.id
        with pytest.raises(HTTPException) as wrong_place:
            await preview_output(session, gateway, pg_book[0], user, command.model_copy(update={'warehouse': 'Other'}), warehouse_gateway=wms)
        assert wrong_place.value.status_code == 409
        assert result['sku_snapshot']['title'] == 'Catalog product'
        assert result['order_snapshot']['product'] == 'Planning title'
        assert result['command']['quantity'] == '2.00' and not result['confirmation_available']
        document = await prepare_output(session, gateway, pg_book[0], user, command, warehouse_gateway=wms)
        assert document.snapshot == result and document.registered_at is not None
        repeated = await prepare_output(session, gateway, pg_book[0], user, command, warehouse_gateway=wms)
        assert repeated.id == document.id
        with pytest.raises(HTTPException) as conflict:
            await prepare_output(session, gateway, pg_book[0], user, command.model_copy(update={'lot': 'Other lot'}), warehouse_gateway=wms)
        assert conflict.value.status_code == 409
        order.product = 'Changed planning title'
        await session.flush()
        with pytest.raises(HTTPException) as stale:
            await preview_output(session, gateway, pg_book[0], user, command)
        assert stale.value.status_code == 409
        assert (await prepare_output(session, gateway, pg_book[0], user, command, warehouse_gateway=wms)).snapshot == result
        await session.rollback()
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(OutputDocument)) == 0

    async def persist():
        async with factory() as session:
            row = await prepare_output(session, gateway, pg_book[0], user, command, warehouse_gateway=wms)
            await session.commit()
            return row.id, row.digest, row.snapshot, row.registered_at

    first, second = await asyncio.gather(persist(), persist())
    assert first == second and first[2] == result
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(OutputDocument)) == 1
        from core.domain.models import OutboxEvent
        from modules.wms.models import StockMovement

        assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 0
        assert await session.scalar(select(func.count()).select_from(StockMovement)) == 0
    assert await persist() == first
    from copy import deepcopy

    for section, field, forged in (
        ('order_snapshot', 'quantity', 999),
        ('order_snapshot', 'created_at', '2000-01-01T00:00:00+00:00'),
        ('sku_snapshot', 'title', 'Forged catalog title'),
        ('receiving_place', 'warehouse', 'Other'),
    ):
        forged_command = command.model_dump(mode='json')
        forged_command['request_id'] = str(uuid4())
        forged_snapshot = deepcopy(result)
        forged_snapshot['command'] = forged_command
        forged_snapshot[section][field] = forged
        async with factory() as session:
            session.add(OutputDocument(organization_id=pg_book[0], order_id=command.order_id,
                request_id=forged_command['request_id'], command=forged_command,
                snapshot=forged_snapshot, digest='0' * 64, actor=result['principal']))
            with pytest.raises(DBAPIError, match='does not match its source'):
                await session.flush()
            await session.rollback()
    assert await persist() == first
    for statement in (
        "UPDATE production.output_document SET snapshot='{}'::json",
        "DELETE FROM production.output_document",
        "TRUNCATE production.output_document CASCADE",
    ):
        async with factory() as session:
            with pytest.raises(DBAPIError, match='immutable'):
                await session.execute(text(statement))
            await session.rollback()
    assert await persist() == first

@pytest.mark.parametrize('value', [True, 2, 2.5, 'NaN', 'Infinity', '-1', '0', '1.001', '1000000000000'])
def test_output_command_rejects_inexact_or_invalid_physical_quantity(value):
    from uuid import uuid4

    from pydantic import ValidationError

    from modules.production.output_documents import OutputCommand

    with pytest.raises(ValidationError):
        OutputCommand(request_id=uuid4(), order_id=1, expected_order_digest='a' * 64,
            operation_date='2026-09-12', sku_code='OUTPUT-SKU', quantity=value,
            warehouse='Main', location_id=1, lot='LOT-1', evidence='Synthetic reviewed output')


@pytest.mark.parametrize('value, expected', [('2.000', '2.00'), ('1E+2', '100.00'), ('0.01', '0.01')])
def test_output_command_serializes_exact_quantity_for_sql(value, expected):
    from uuid import uuid4

    from modules.production.output_documents import OutputCommand

    command = OutputCommand(request_id=uuid4(), order_id=1, expected_order_digest='a' * 64,
        operation_date='2026-09-12', sku_code='OUTPUT-SKU', quantity=value,
        warehouse='Main', location_id=1, lot='LOT-1', evidence='Synthetic reviewed output')
    assert command.model_dump(mode='json')['quantity'] == expected


async def test_output_public_prepare_readback_and_principal_isolation(issuance_pg, pg_book):
    from uuid import uuid4

    from core.domain.models import OutboxEvent, Sku
    from modules.production.output_documents import OutputDocument
    from modules.wms.models import Location, StockMovement

    api, factory = issuance_pg
    api.headers['X-User'] = 'tester'
    async with factory() as session:
        order = ProductionOrder(number='SYN-OUTPUT-API', product='Planning product', qty=4)
        place = Location(warehouse='Main', code='OUTPUT-API')
        session.add_all([order, place, Sku(code='OUTPUT-API', title='Catalog product', unit='шт')])
        session.add_all([Sku(code='OUTPUT-API-INACTIVE', title='Inactive', unit='шт', is_active=False),
            Location(warehouse='Main', code='OUTPUT-API-INACTIVE', is_active=False)])
        await session.flush()
        digest = order_snapshot(order)[1]
        await assign_order(session, AccountingService(), pg_book[0], CurrentUser('tester', ['director']),
            OwnershipCommand(order_id=order.id, expected_digest=digest, evidence='Synthetic reviewed owner'))
        await session.commit()
    command = dict(request_id=str(uuid4()), order_id=order.id, expected_order_digest=digest,
        operation_date='2026-09-12', sku_code='OUTPUT-API', quantity='2.000',
        warehouse='Main', location_id=place.id, lot='API-LOT', evidence='Synthetic reviewed output')
    base = f'/production/organizations/{pg_book[0]}'
    headers = {'X-Expected-Principal': 'tester'}
    sku_options = await api.get(base + '/output-skus', params={'q': 'OUTPUT-API'})
    assert sku_options.status_code == 200 and [row['code'] for row in sku_options.json()] == ['OUTPUT-API']
    assert (await api.get(base + '/output-skus', params={'q': '%'})).json() == []
    places = await api.get(base + '/output-places', params={'q': 'OUTPUT-API'})
    assert places.status_code == 200 and [row['location_id'] for row in places.json()] == [place.id]
    assert (await api.get(base + '/output-places', params={'q': '%'})).json() == []
    source = await api.get(base + f'/orders/{order.id}/output-source')
    assert source.status_code == 200 and source.json()['digest'] == digest
    assert source.headers['cache-control'] == 'private, no-store'
    assert (await api.post(base + '/output-documents', json=command)).status_code == 422
    assert (await api.post(base + '/output-documents', json=command,
        headers={'X-Expected-Principal': 'other'})).status_code == 409
    preview = await api.post(base + '/output-preview', json=command, headers=headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()['command']['quantity'] == '2.00'
    assert preview.json()['posted'] is False
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(OutputDocument)) == 0
    first, repeated = await asyncio.gather(*[
        api.post(base + '/output-documents', json=command, headers=headers) for _ in range(2)])
    assert first.status_code == repeated.status_code == 200, (first.text, repeated.text)
    assert first.json() == repeated.json()
    path = base + '/output-documents/' + command['request_id']
    readback = await api.get(path)
    assert readback.status_code == 200 and readback.json() == first.json()
    assert readback.headers['cache-control'] == 'private, no-store'
    assert (await api.post(base + '/output-documents', json={**command, 'lot': 'OTHER'}, headers=headers)).status_code == 409
    api.headers['X-User'] = 'unassigned-user'
    assert (await api.get(path)).status_code == 403
    for endpoint in ('output-skus?q=OUTPUT', 'output-places?q=Main', f'orders/{order.id}/output-source'):
        assert (await api.get(base + '/' + endpoint)).status_code == 403
    assert (await api.post(base + '/output-documents', json=command, headers=headers)).status_code == 403
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(OutputDocument)) == 1
        assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 0
        assert await session.scalar(select(func.count()).select_from(StockMovement)) == 0

    from modules.production.output_documents import (
        OutputCommand,
        OutputConfirmation,
        confirm_output,
        prepare_output,
    )
    from modules.wms.reservation_gateway import WmsReservationService

    gateway, user, warehouse = AccountingService(), CurrentUser('tester', ['director']), WmsReservationService()
    async with factory() as session:
        second = await prepare_output(session, gateway, pg_book[0], user,
            OutputCommand.model_validate({**command, 'request_id': str(uuid4()), 'quantity': '3.00'}),
            warehouse_gateway=warehouse)
        await session.commit()

    async def confirm(document_id, digest):
        request_id = command['request_id'] if document_id == first.json()['id'] else second.request_id
        result = await api.post(base + f'/output-documents/{request_id}/confirm',
            json={'expected_digest': digest}, headers=headers)
        assert result.status_code in (200, 409), result.text
        return result.json()['document_id'] if result.status_code == 200 else None

    async with factory() as session:
        await confirm_output(session, gateway, pg_book[0], user, second.id, second.digest, warehouse_gateway=warehouse)
        await session.rollback()
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(OutputConfirmation)) == 0
        assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 0
    confirm_path = base + f"/output-documents/{command['request_id']}/confirm"
    assert (await api.post(confirm_path, json={'expected_digest': first.json()['digest']}, headers=headers)).status_code == 403
    api.headers['X-User'] = 'tester'
    assert (await api.post(confirm_path, json={'expected_digest': first.json()['digest']})).status_code == 422
    assert (await api.post(confirm_path, json={'expected_digest': first.json()['digest']},
        headers={'X-Expected-Principal': 'other'})).status_code == 409
    assert (await api.post(confirm_path, json={'expected_digest': 'f' * 64}, headers=headers)).status_code == 409
    assert (await api.get(base + f"/output-confirmations/{command['request_id']}")).status_code == 404
    results = await asyncio.gather(confirm(first.json()['id'], first.json()['digest']), confirm(second.id, second.digest))
    assert sum(value is not None for value in results) == 1
    winner = next(value for value in results if value is not None)
    winner_digest = first.json()['digest'] if winner == first.json()['id'] else second.digest
    assert await confirm(winner, winner_digest) == winner
    winner_request = command['request_id'] if winner == first.json()['id'] else second.request_id
    read_confirmation = await api.get(base + f'/output-confirmations/{winner_request}')
    assert read_confirmation.status_code == 200 and read_confirmation.json()['document_id'] == winner
    assert read_confirmation.headers['cache-control'] == 'private, no-store'
    replay_confirmation = await api.post(base + f'/output-documents/{winner_request}/confirm',
        json={'expected_digest': winner_digest}, headers=headers)
    assert replay_confirmation.json() == read_confirmation.json()
    register = await api.get(base + '/output-documents')
    assert register.status_code == 200, register.text
    assert len(register.json()) == 2
    assert sum(row['confirmation'] is not None for row in register.json()) == 1
    assert all(row['document']['organization_id'] == pg_book[0] for row in register.json())
    api.headers['X-User'] = 'unassigned-user'
    assert (await api.get(base + '/output-documents')).status_code == 403
    assert (await api.get(base + f'/output-confirmations/{winner_request}')).status_code == 403
    api.headers['X-User'] = 'tester'
    assert (await api.patch(base + f'/orders/{order.id}', json={'stage': 'done'}, headers=headers)).status_code == 409
    before_delivery = await api.get(base + f'/orders/{order.id}/output-reconciliation')
    assert before_delivery.status_code == 200, before_delivery.text
    assert before_delivery.json()['documents'][0]['state'] == 'awaiting_delivery'
    assert before_delivery.json()['documents'][0]['accepted_quantity'] is None
    assert before_delivery.json()['pending_quantity'] == read_confirmation.json()['quantity']
    from types import SimpleNamespace

    from core.services.eventbus import EventContext, OutboxEventBus
    from modules.production.output_documents import ProductionOutputService
    from modules.wms.events import on_goods_received
    from modules.wms.models import Receipt, ReceiptLine

    services = SimpleNamespace(production_output=ProductionOutputService())
    bus = OutboxEventBus()
    bus.subscribe('production.output.confirmed', on_goods_received)
    assert await bus.relay_pending(factory, services, event_types=('production.output.confirmed',)) == 1
    assert await bus.relay_pending(factory, services, event_types=('production.output.confirmed',)) == 0
    before_qc = await api.get(base + f'/orders/{order.id}/output-reconciliation')
    assert before_qc.status_code == 200 and before_qc.json()['documents'][0]['state'] == 'pending_qc'
    assert before_qc.json()['documents'][0]['accepted_quantity'] is None
    async with factory() as session:
        confirmation = await session.get(OutputConfirmation, winner)
        source_event = await session.get(OutboxEvent, confirmation.event_id)
        assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 1
        await on_goods_received(source_event.payload, EventContext(session, services, event_id=source_event.id))
        await session.commit()
        receipt = await session.scalar(select(Receipt))
        line = await session.scalar(select(ReceiptLine))
        assert receipt.organization_id == pg_book[0] and receipt.status == 'pending_qc'
        assert receipt.entity_ref == f'production_output:{winner}'
        assert line.expected_qty == confirmation.quantity and line.accepted_qty is None
        assert line.location_id == place.id and line.batch_ref == 'API-LOT'
        receipt_id, line_id, confirmed_qty = receipt.id, line.id, confirmation.quantity
        assert await session.scalar(select(func.count()).select_from(Receipt)) == 1
        assert await session.scalar(select(func.count()).select_from(StockMovement)) == 0
        forged_event = OutboxEvent(event_type='production.output.confirmed', version=1, payload=source_event.payload)
        session.add(forged_event)
        await session.flush()
        with pytest.raises(ValueError, match='not bound to a confirmation'):
            await on_goods_received(forged_event.payload, EventContext(session, services, event_id=forged_event.id))
        await session.rollback()
    production_board = await api.get(base + '/board')
    assert production_board.status_code == 200, production_board.text
    cards = [card for stage in production_board.json()['stages'] for card in stage['cards']]
    output_card = next(card for card in cards if card['id'] == order.id)
    assert output_card['progress'] is None
    assert f'Подтверждён выпуск: {confirmed_qty:.2f} шт' in output_card['tags']
    assert 'По наряду: 4' in output_card['tags']
    from decimal import Decimal

    from modules.wms.primary_receipts import validate_primary_acceptance

    for target, field, value in (
        ('line', 'expected_qty', Decimal('99')), ('line', 'batch_ref', 'OTHER'),
        ('line', 'location_id', None), ('line', 'sku_code', 'OTHER'),
    ):
        async with factory() as session:
            stored_receipt = await session.get(Receipt, receipt_id)
            stored_line = await session.get(ReceiptLine, line_id)
            stored_line.accepted_qty, stored_line.rejected_qty = confirmed_qty, Decimal('0')
            setattr(stored_line if target == 'line' else stored_receipt, field, value)
            with pytest.raises(HTTPException) as mismatch:
                await validate_primary_acceptance(session, SimpleNamespace(services=services), stored_receipt, [stored_line])
            assert mismatch.value.status_code == 409
            await session.rollback()
    path = f'/wms/receipts/{receipt_id}'
    detail = await api.get(path)
    assert detail.status_code == 200, detail.text
    qc = await api.post(path + '/qc', json={'expected_revision': detail.json()['qc_revision'],
        'decisions': [{'line_id': line_id, 'accepted_qty': str(confirmed_qty - 1),
            'rejected_qty': '1.00', 'reject_reason': 'Synthetic output defect'}]})
    assert qc.status_code == 200, qc.text
    accepted = await api.post(path + '/accept')
    assert accepted.status_code == 200, accepted.text
    assert (await api.post(path + '/accept')).status_code == 200
    reconciled = await api.get(base + f'/orders/{order.id}/output-reconciliation')
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()['accepted_quantity'] == format(confirmed_qty - 1, '.2f')
    assert reconciled.json()['rejected_quantity'] == '1.00' and reconciled.json()['pending_quantity'] == '0.00'
    assert reconciled.json()['unit'] == 'шт' and reconciled.json()['accounting_final'] is False
    assert len(reconciled.json()['documents'][0]['movement_ids']) == 1
    async with factory() as session:
        movement = await session.scalar(select(StockMovement))
        with pytest.raises(DBAPIError, match='movement is immutable'):
            await session.execute(text('UPDATE wms.stock_movement SET qty=qty+1 WHERE id=:id'), {'id': movement.id})
        await session.rollback()
    from modules.wms.production_arrivals import ProductionArrival

    async with factory() as session:
        await session.execute(text("""INSERT INTO wms.stock_movement
            (organization_id,sku_code,warehouse,kind,qty,reason,doc_ref,location_id,batch_ref)
            SELECT organization_id,sku_code,warehouse,kind,qty,reason,doc_ref,location_id,batch_ref
            FROM wms.stock_movement LIMIT 1"""))
        with pytest.raises(DBAPIError, match='extra movements'):
            await session.commit()
        await session.rollback()
    async with factory() as session:
        arrival = await session.get(ProductionArrival, receipt_id)
        assert arrival.line_id == line_id and arrival.organization_id == pg_book[0]
        assert arrival.accepted_quantity == confirmed_qty - 1 and arrival.rejected_quantity == 1
        assert arrival.movement_id == reconciled.json()['documents'][0]['movement_ids'][0]
    for statement in ('UPDATE wms.production_arrival SET accepted_quantity=99',
        'DELETE FROM wms.production_arrival', 'TRUNCATE wms.production_arrival',
        'DELETE FROM wms.stock_movement', 'TRUNCATE wms.stock_movement CASCADE'):
        async with factory() as session:
            with pytest.raises(DBAPIError, match='immutable'):
                await session.execute(text(statement))
            await session.rollback()
    async with factory() as session:
        moves = (await session.scalars(select(StockMovement))).all()
        assert len(moves) == 1 and moves[0].qty == confirmed_qty - 1
        assert moves[0].organization_id == pg_book[0]
    for statement in (
        "UPDATE wms.receipt_line SET accepted_qty=99 WHERE id=:line",
        "UPDATE wms.receipt_line SET rejected_qty=0 WHERE id=:line",
        "UPDATE wms.receipt_line SET sku_code='OTHER',batch_ref='OTHER' WHERE id=:line",
        "DELETE FROM wms.receipt_line WHERE id=:line",
        "INSERT INTO wms.receipt_line (receipt_id,sku_code,expected_qty) VALUES (:receipt,'OTHER',1)",
        "TRUNCATE wms.receipt_line CASCADE",
    ):
        async with factory() as session:
            with pytest.raises(DBAPIError, match='lines are immutable'):
                await session.execute(text(statement), {'receipt': receipt_id, 'line': line_id})
            await session.rollback()
    async with factory() as session:
        preserved = await session.get(ReceiptLine, line_id)
        assert preserved.accepted_qty == confirmed_qty - 1 and preserved.rejected_qty == 1
        assert preserved.batch_ref == 'API-LOT' and preserved.sku_code == 'OUTPUT-API'
    for statement in (
        "UPDATE wms.receipt SET source_event_id=NULL,entity_ref='',source='manual' WHERE id=:receipt",
        "UPDATE wms.receipt SET organization_id=999 WHERE id=:receipt",
        "UPDATE wms.receipt SET warehouse='OTHER' WHERE id=:receipt",
        "UPDATE wms.receipt SET number='OTHER' WHERE id=:receipt",
        "UPDATE wms.receipt SET status='pending_qc' WHERE id=:receipt",
        "DELETE FROM wms.receipt WHERE id=:receipt",
        "TRUNCATE wms.receipt CASCADE",
    ):
        async with factory() as session:
            with pytest.raises(DBAPIError, match='source is immutable'):
                await session.execute(text(statement), {'receipt': receipt_id})
            await session.rollback()
    async with factory() as session:
        assert (await session.get(Receipt, receipt_id)).status == 'accepted'
        assert await session.scalar(select(func.count()).select_from(StockMovement)) == 1
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(OutputConfirmation)) == 1
        assert await session.scalar(select(func.sum(OutputConfirmation.quantity))) <= 4
    for statement in ('UPDATE production.output_confirmation SET quantity=1',
        'DELETE FROM production.output_confirmation', 'TRUNCATE production.output_confirmation'):
        async with factory() as session:
            with pytest.raises(DBAPIError, match='immutable'):
                await session.execute(text(statement))
            await session.rollback()


@pytest.mark.parametrize('fully_rejected', [True, False])
async def test_production_output_final_qc_and_completion(issuance_pg, pg_book, fully_rejected):
    from uuid import uuid4

    from core.domain.models import Sku
    from modules.production.output_documents import OutputCommand, confirm_output, prepare_output
    from modules.wms.models import Location, Receipt, ReceiptLine, StockMovement
    from modules.wms.production_arrivals import ProductionArrival

    api, factory = issuance_pg
    api.headers['X-User'] = 'tester'
    core = api._transport.app.state.core
    gateway, user = AccountingService(), CurrentUser('tester', ['director'])
    async with factory() as session:
        order = ProductionOrder(number='FULL-REJECT', product='Synthetic rejected output', qty=1)
        place = Location(warehouse='Main', code='FULL-REJECT')
        session.add_all([order, place, Sku(code='FULL-REJECT', title='Synthetic output', unit='шт')])
        await session.flush()
        digest = order_snapshot(order)[1]
        await assign_order(session, gateway, pg_book[0], user,
            OwnershipCommand(order_id=order.id, expected_digest=digest, evidence='Synthetic reviewed owner'))
        document = await prepare_output(session, gateway, pg_book[0], user,
            OutputCommand(request_id=uuid4(), order_id=order.id, expected_order_digest=digest,
                operation_date='2026-09-12', sku_code='FULL-REJECT', quantity='1.00', warehouse='Main',
                location_id=place.id, lot='REJECT-LOT', evidence='Synthetic rejected output'),
            warehouse_gateway=core.services.wms_reservations)
        await confirm_output(session, gateway, pg_book[0], user, document.id, document.digest,
            warehouse_gateway=core.services.wms_reservations)
        await session.commit()
    assert await core.event_bus.relay_pending(factory, core.services, event_types=('production.output.confirmed',)) == 1
    async with factory() as session:
        receipt = await session.scalar(select(Receipt))
        line = await session.scalar(select(ReceiptLine))
        receipt_id, line_id = receipt.id, line.id
    path = f'/wms/receipts/{receipt_id}'
    detail = await api.get(path)
    qc = await api.post(path + '/qc', json={'expected_revision': detail.json()['qc_revision'], 'decisions': [
        {'line_id': line_id, 'accepted_qty': '0.00' if fully_rejected else '1.00',
            'rejected_qty': '1.00' if fully_rejected else '0.00', 'reject_reason': 'Synthetic QC decision'}]})
    assert qc.status_code == 200, qc.text
    accepted = await api.post(path + '/accept')
    assert accepted.status_code == 200, accepted.text
    assert (await api.post(path + '/accept')).status_code == 200
    async with factory() as session:
        binding = await session.get(ProductionArrival, receipt_id)
        assert (binding.movement_id is None) == fully_rejected
        assert binding.accepted_quantity == (0 if fully_rejected else 1)
        assert binding.rejected_quantity == (1 if fully_rejected else 0)
        assert await session.scalar(select(func.count()).select_from(StockMovement)) == (0 if fully_rejected else 1)
    report = await api.get(f'/production/organizations/{pg_book[0]}/orders/{order.id}/output-reconciliation')
    assert report.status_code == 200, report.text
    assert report.json()['accepted_quantity'] == ('0.00' if fully_rejected else '1.00')
    assert report.json()['rejected_quantity'] == ('1.00' if fully_rejected else '0.00')
    from core.domain.models import OutboxEvent
    from modules.production.order_completion import (
        CompletionCommand,
        OrderCompletion,
        complete_order,
        preview_completion,
    )

    async with factory() as session:
        if fully_rejected:
            with pytest.raises(HTTPException) as blocked:
                await preview_completion(session, pg_book[0], order.id, core.services.wms_reservations)
            assert blocked.value.status_code == 409
            return
        preview = await preview_completion(session, pg_book[0], order.id, core.services.wms_reservations)
        command = CompletionCommand(expected_digest=preview['digest'], operation_date='2026-09-12', evidence='Synthetic complete output')
        await complete_order(session, gateway, pg_book[0], user, order.id, command, core.services.wms_reservations)
        await session.rollback()
    async with factory() as session:
        assert await session.get(OrderCompletion, order.id) is None
        assert (await session.get(ProductionOrder, order.id)).stage != 'done'

    from copy import deepcopy

    for changed in ('product', 'movement', 'date'):
        snapshot = deepcopy(preview['snapshot'])
        if changed == 'product':
            snapshot['order']['product'] = 'Forged product'
        elif changed == 'movement':
            snapshot['reconciliation']['documents'][0]['movement_ids'] = [999999]
        else:
            snapshot['minimum_date'] = '2000-01-01'
        async with factory() as session:
            session.add(OrderCompletion(order_id=order.id, organization_id=pg_book[0], actor='tester',
                command=command.model_dump(mode='json'), snapshot=snapshot))
            with pytest.raises(DBAPIError, match='snapshot differs from its sources'):
                await session.flush()
            await session.rollback()

    async def finish():
        result = await api.post(f'/production/organizations/{pg_book[0]}/orders/{order.id}/completion',
            json=command.model_dump(mode='json'), headers={'X-Expected-Principal': 'tester'})
        assert result.status_code == 200, result.text
        return result.json()
    completion_path = f'/production/organizations/{pg_book[0]}/orders/{order.id}/completion'
    assert (await api.get(completion_path)).status_code == 404
    public_preview = await api.get(completion_path + '-preview')
    assert public_preview.status_code == 200 and public_preview.json()['digest'] == command.expected_digest
    first, repeated = await asyncio.gather(finish(), finish())
    assert first == repeated and await finish() == first
    stored_result = await api.get(completion_path)
    assert stored_result.status_code == 200 and stored_result.json() == first
    assert stored_result.headers['cache-control'] == 'private, no-store'
    assert (await api.post(completion_path, json={**command.model_dump(mode='json'), 'evidence': 'Different decision'},
        headers={'X-Expected-Principal': 'tester'})).status_code == 409
    async with factory() as session:
        finished = await session.get(ProductionOrder, order.id)
        assert finished.stage == 'done' and finished.made_qty == 1 and finished.progress == 100
        assert finished.completed_at.date().isoformat() == '2026-09-12'
        assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 1
        assert await session.scalar(select(func.count()).select_from(StockMovement)) == 1
        with pytest.raises(DBAPIError, match='immutable'):
            await session.execute(text('DELETE FROM production.order_completion'))
        await session.rollback()
