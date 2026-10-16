import asyncio
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from core.domain.models import Sku
from core.domain.reference import NomenclatureCategory
from modules.accounting.models import Organization
from modules.procurement import events as procurement_events
from modules.procurement.deal_demands import (
    AllocationCreate,
    DealProcurementAllocation,
    DealProcurementDemand,
    DemandCreate,
    _allocate,
    _create_demand,
)
from modules.procurement.expected_reservations import ExpectedReservation, ExpectedReservationEvent
from modules.procurement.models import PurchaseOrder, PurchaseOrderLine
from modules.procurement.ownership import PurchaseOwnership
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.models import Deal, DealItem
from tests.accounting.test_postgres import pg_factory  # noqa: F401

pytestmark = pytest.mark.integration


async def _prepare(factory, org_id: int):
    async with factory() as session:
        # The shared PostgreSQL fixture intentionally starts from the accounting proposal
        # baseline and does not create the public SKU or sales deal-item tables.
        await session.run_sync(lambda sync_session: NomenclatureCategory.__table__.create(sync_session.connection(), checkfirst=True))
        await session.run_sync(lambda sync_session: Sku.__table__.create(sync_session.connection(), checkfirst=True))
        await session.run_sync(lambda sync_session: DealItem.__table__.create(sync_session.connection(), checkfirst=True))
        session.add(Organization(id=org_id, name="PG demand org", unp="987654321"))
        sku = Sku(code="PG-DEMAND-SKU", title="PG demand", unit="шт", is_active=True)
        deal = Deal(number="PG-DEMAND-DEAL", title="PG demand", counterparty="Buyer", stage="invoice")
        session.add_all([sku, deal])
        await session.flush()
        item = DealItem(deal_id=deal.id, sku_id=sku.id, qty=Decimal("10.00"))
        order = PurchaseOrder(number="PG-DEMAND-PO", supplier="Supplier", status="ordered")
        session.add_all([item, order])
        await session.flush()
        line = PurchaseOrderLine(order_id=order.id, sku_code=sku.code, qty=Decimal("12.00"))
        session.add(line)
        await session.flush()
        session.add_all([
            DealOwnership(deal_id=deal.id, organization_id=org_id, snapshot={}, evidence="Synthetic", actor="tester"),
            PurchaseOwnership(organization_id=org_id, kind="order", source_id=order.id,
                              snapshot={}, evidence="Synthetic", actor="tester"),
        ])
        await session.commit()
        return deal.id, item.id, order.id, line.id


def _demand(item_id: int, qty: str):
    return DemandCreate(
        deal_item_id=item_id,
        qty=qty,
        request_key=str(uuid4()),
        evidence="PG demand",
    )


async def test_pg_demand_competition_and_immutable_history(pg_factory):  # noqa: F811
    org_id = 1
    deal_id, item_id, order_id, line_id = await _prepare(pg_factory, org_id)

    async def writer(qty: str):
        async with pg_factory() as session:
            try:
                demand, replayed = await _create_demand(session, org_id, "tester", deal_id, _demand(item_id, qty))
                await session.commit()
                return 201, replayed, demand
            except HTTPException as exc:
                await session.rollback()
                return exc.status_code, False, None

    results = await asyncio.gather(writer("6.00"), writer("6.00"))
    assert sorted(row[0] for row in results) == [201, 409]
    async with pg_factory() as session:
        demand = await session.scalar(select(DealProcurementDemand))
        assert demand is not None
        demand_id = demand.id
        allocated, replayed = await _allocate(
            session,
            org_id,
            "tester",
            demand_id,
            AllocationCreate(
                order_id=order_id,
                order_line_id=line_id,
                qty="5.00",
                request_key=str(uuid4()),
                evidence="PG allocation",
            ),
        )
        assert replayed is False and allocated["ordered_qty"] == "5.00"
        await session.commit()
        assert await session.scalar(select(func.count()).select_from(ExpectedReservation)) == 1
        loss_payload = {"organization_id": org_id, "deal_id": deal_id,
                        "resolution_id": str(uuid4()), "by": "tester"}
        await procurement_events.on_deal_loss_finalized(loss_payload, SimpleNamespace(session=session))
        await session.commit()
        await procurement_events.on_deal_loss_finalized(loss_payload, SimpleNamespace(session=session))
        await session.commit()
        assert await session.scalar(select(func.count()).select_from(ExpectedReservationEvent)) == 1
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(text("UPDATE procurement.deal_procurement_demand SET evidence='tampered'"))
        await session.rollback()
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(text("DELETE FROM procurement.deal_procurement_allocation"))
        await session.rollback()
        await session.execute(update(PurchaseOrderLine).where(PurchaseOrderLine.id == line_id).values(qty=Decimal("4.00")))
        await session.commit()
        reallocated, replayed = await _allocate(
            session,
            org_id,
            "tester",
            demand_id,
            AllocationCreate(
                order_id=order_id,
                order_line_id=line_id,
                qty="4.00",
                request_key=str(uuid4()),
                evidence="PG allocation after release projection",
            ),
        )
        assert replayed is False and reallocated["ordered_qty"] == "4.00"
        await session.commit()
        with pytest.raises(DBAPIError, match="client allocations"):
            await session.execute(text("DELETE FROM procurement.purchase_order_line WHERE id=:line_id"), {"line_id": line_id})
        await session.rollback()
        assert await session.scalar(select(func.count()).select_from(DealProcurementAllocation)) == 2
