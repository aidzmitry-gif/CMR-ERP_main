"""Real locks and replay for numeric CRM leads, on the guarded synthetic DB."""
import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select, text

from core.db.base import Base
from core.domain.models import OutboxEvent, Sku, User
from core.services.crm_access import CrmAccess
from core.services.eventbus import EventContext
from modules.leads.models import Lead, LeadItem
from modules.leads.routes import convert_lead, create_lead, replace_items, route
from modules.leads.schemas import LeadCreate, LeadItemIn, RouteIn
from modules.sales.crm_client_lookup import SalesCrmClientLookup
from modules.sales.models import CrmClient, CrmClientContact, Deal, DealItem, PriceQuote
from tests.integration.test_crm_owner_conversion_postgres import (
    _conversion_core,
    _finish_tasks,
    _pause_first_commit,
    _wait_for_lock,
)
from tests.integration.test_crm_owner_conversion_postgres import (
    owner_factory as owner_factory,
)

ACCESS = CrmAccess('own', 901)


@pytest_asyncio.fixture
async def own_factory(owner_factory):
    async with owner_factory.kw['bind'].begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[Base.metadata.tables["ref_nomenclature_category"], Sku.__table__, CrmClientContact.__table__,
                                                            DealItem.__table__, PriceQuote.__table__])
    yield owner_factory


async def seed(factory):
    async with factory() as session:
        session.add(User(username='own-pg', full_name='Numeric owner', employee_id=901,
                         department='Продажи', role='sales', status='active', deal_visibility='own'))
        clients = [CrmClient(name=f'PG buyer{i}', name_key=f'pg{i}', owner_id=901,
                             request_key=f'pg-client{i}', request_hash='0' * 64, created_by='own-pg') for i in (1, 2)]
        sku = Sku(code='OWN-PG-SKU', title='Synthetic component', unit='шт')
        session.add_all([*clients, sku])
        await session.flush()
        contact = CrmClientContact(crm_client_id=clients[0].id, full_name='PG contact',
                                  contact_key='0' * 64, request_key='pg-contact', request_hash='0' * 64)
        session.add(contact)
        await session.flush()
        lead = Lead(owner_id=901, crm_client_id=clients[0].id, crm_contact_id=contact.id,
                    assigned_to='Numeric owner', company=clients[0].name, status='routed',
                    next_step_note='Confirm order')
        session.add(lead)
        await session.flush()
        session.add_all([LeadItem(lead_id=lead.id, sku_id=sku.id, sku_code=sku.code, qty=1, price=p) for p in (125.5, 0)])
        await session.commit()
        return SimpleNamespace(clients=[c.id for c in clients], lead=lead.id, sku=sku.id, contact=contact.id)


def core():
    result = _conversion_core()
    result.services.crm_clients = SalesCrmClientLookup()
    return result


@pytest.mark.parametrize('different_client', [False, True])
async def test_create_replay_serializes_or_conflicts_without_partial_row(own_factory, monkeypatch, different_client):
    data = await seed(own_factory)
    async with own_factory() as first, own_factory() as second:
        one = two = None
        reached, release = _pause_first_commit(first, monkeypatch)
        try:
            first_pid = await first.scalar(text('SELECT pg_backend_pid()'))
            second_pid = await second.scalar(text('SELECT pg_backend_pid()'))
            async def create(session, client_id):
                try:
                    result = await create_lead(LeadCreate(crm_client_id=client_id, request_key='pg-replay-key'),
                                               core=core(), session=session, access=ACCESS)
                    return result.id
                finally:
                    await session.rollback()
            one = asyncio.create_task(create(first, data.clients[0]))
            await asyncio.wait_for(reached.wait(), 10)
            two = asyncio.create_task(create(second, data.clients[int(different_client)]))
            await _wait_for_lock(own_factory, first_pid, second_pid, two)
            release.set()
            created = await asyncio.wait_for(one, 10)
            if different_client:
                with pytest.raises(HTTPException) as error:
                    await asyncio.wait_for(two, 10)
                assert error.value.status_code == 409
            else:
                repeated = await asyncio.wait_for(two, 10)
                assert repeated == created
        finally:
            release.set()
            await _finish_tasks(one, two)
    async with own_factory() as verify:
        assert await verify.scalar(select(func.count()).select_from(Lead).where(Lead.request_key == 'pg-replay-key')) == 1
        assert await verify.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.event_type == 'leads.lead.received')) == 1


@pytest.mark.parametrize('contender', ['convert', 'items'])
async def test_conversion_serializes_same_lead_and_preserves_snapshot(own_factory, monkeypatch, contender):
    data = await seed(own_factory)
    bus = core()
    async with own_factory() as first, own_factory() as second:
        one = two = None
        reached, release = _pause_first_commit(first, monkeypatch)
        try:
            first_pid = await first.scalar(text('SELECT pg_backend_pid()'))
            second_pid = await second.scalar(text('SELECT pg_backend_pid()'))
            async def convert(session):
                try:
                    return await convert_lead(data.lead, core=bus, session=session, access=ACCESS)
                finally:
                    await session.rollback()
            async def change():
                try:
                    return await replace_items(data.lead, [LeadItemIn(sku_id=data.sku, price=999)], session=second, access=ACCESS)
                finally:
                    await second.rollback()
            one = asyncio.create_task(convert(first))
            await asyncio.wait_for(reached.wait(), 10)
            two = asyncio.create_task(convert(second) if contender == 'convert' else change())
            await _wait_for_lock(own_factory, first_pid, second_pid, two)
            release.set()
            if contender == 'items':
                with pytest.raises(HTTPException) as error:
                    await asyncio.wait_for(two, 10)
                assert error.value.status_code == 409
            else:
                assert (await asyncio.wait_for(two, 10)).status == 'converted'
            assert (await asyncio.wait_for(one, 10)).deal_id is not None
        finally:
            release.set()
            await _finish_tasks(one, two)
    async with own_factory() as verify:
        lead = await verify.get(Lead, data.lead)
        deal = await verify.get(Deal, lead.deal_id)
        assert (deal.owner_id, deal.crm_client_id, deal.crm_contact_id) == (901, data.clients[0], data.contact)
        assert deal.funnel == 'new_clients' and deal.stage == 'new'
        assert float(deal.amount) == 125.5
        assert list(map(float, (await verify.scalars(select(DealItem.unit_price).order_by(DealItem.id))).all())) == [125.5, 0]
        assert await verify.scalar(select(func.count()).select_from(Deal)) == 1
        assert await verify.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.event_type == 'leads.lead.converted')) == 1


async def test_owned_conversion_does_not_deliver_unrelated_pending_event(own_factory):
    data = await seed(own_factory)
    bus = core()
    touched = []
    bus.event_bus.subscribe('intake.lead.received', lambda payload: touched.append(payload))
    async with own_factory() as session:
        bus.event_bus.emit(session, 'intake.lead.received', {'private': 'synthetic unrelated'})
        await session.commit()
        result = await convert_lead(data.lead, core=bus, session=session, access=ACCESS)
        assert result.deal_id is not None and touched == []
        pending = await session.scalar(select(OutboxEvent).where(OutboxEvent.event_type == 'intake.lead.received'))
        assert pending.processed_at is None
        # Lost reply retry does not emit another conversion or process other types.
        assert (await convert_lead(data.lead, core=bus, session=session, access=ACCESS)).deal_id == result.deal_id
        assert touched == []
        assert await bus.event_bus.relay_once(session, EventContext(session, bus.services), event_types={'sales.deal.created'}) == 0


async def test_route_timezone_and_next_step_limit_before_pg_commit(own_factory):
    data = await seed(own_factory)
    async with own_factory() as session:
        lead = await session.get(Lead, data.lead)
        lead.status = 'qualified'
        await session.commit()
        with pytest.raises(HTTPException) as error:
            await route(data.lead, RouteIn(next_step_note='x' * 129, next_step_at='2026-09-15T10:00:00+03:00'),
                        core=core(), session=session, access=ACCESS)
        assert error.value.status_code == 422
        await session.rollback()
        assert (await session.get(Lead, data.lead)).status == 'qualified'
        await route(data.lead, RouteIn(next_step_note='Confirm', next_step_at='2026-09-15T10:00:00+03:00'),
                    core=core(), session=session, access=ACCESS)
        assert (await session.get(Lead, data.lead)).next_step_at == datetime(2026, 9, 15, 7)
