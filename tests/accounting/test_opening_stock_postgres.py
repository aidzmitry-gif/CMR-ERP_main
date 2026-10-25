# ruff: noqa: F811 -- pytest discovers imported fixtures by parameter name.
"""Real registered-head PostgreSQL evidence for typed stock-only opening documents."""
import asyncio
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from core.domain.models import Sku
from modules.accounting import inventory_cost, opening_stock, service
from modules.accounting.models import Account, Entry, Line, Organization
from modules.accounting.schemas import InventoryLotQuery
from modules.wms.models import StockMovement
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401

pytestmark = pytest.mark.integration


async def _stock_document(factory, book):
    async with factory() as session:
        await service.lock_organization(session, book[0])
        # pg_book copies chart IDs explicitly. Preserve that fixture instead of
        # assuming its PostgreSQL identity sequence has advanced.
        next_id = (await session.scalar(select(func.max(Account.id)))) + 1
        session.add(Account(id=next_id, organization_id=book[0], code="41", title="Synthetic stock",
                            category="asset", valid_from=date(2026, 6, 1),
                            required_dimensions=["warehouse", "sku", "lot"], quantity_tracking=True,
                            currency_tracking=False, cash=False, normative_ref="Synthetic opening test"))
        session.add(Sku(code="OPENING-TEST-SKU", title="Synthetic opening stock item", unit="шт", is_active=True))
        await session.commit()
    return opening_stock.StockInput.model_validate({
        "request_key": str(uuid4()), "opening_date": "2026-07-01", "policy_id": book[1],
        "inventory_account": "41", "counter_account": "80", "evidence": "Synthetic stock report only",
        "rows": [{"sku": "OPENING-TEST-SKU", "warehouse": "warehouse1", "lot": f"opening-{i:04}",
                  "quantity": "2.123456", "amount_byn": "12.34"} for i in range(501)],
    })


@pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)
async def test_opening_stock_pg_concurrent_retry_is_one_atomic_batch(pg_factory, pg_book):
    document = await _stock_document(pg_factory, pg_book)
    async with pg_factory() as session:
        preview = await opening_stock.preview(session, pg_book[0], document)
        assert await session.scalar(select(func.count()).select_from(Entry)) == 0
        await session.commit()
    command = opening_stock.StockConfirm(document=document, preview_digest=preview["preview_digest"],
                                         acknowledge_addition=True)

    async def confirm():
        async with pg_factory() as session:
            receipt = await opening_stock.confirm(session, pg_book[0], command, "tester")
            await session.commit()
            return receipt

    first, second = await asyncio.wait_for(asyncio.gather(confirm(), confirm()), timeout=90)
    assert first["entry_ids"] == second["entry_ids"] and len(first["entry_ids"]) == 2
    assert first["row_count"] == second["row_count"] == 501
    assert first["total_byn"] == second["total_byn"] == format(Decimal("12.34") * 501, ".2f")
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Entry)) == 2
        assert await session.scalar(select(func.count()).select_from(Line)) == 1002
        assert await session.scalar(select(func.count()).select_from(StockMovement)) == 0
        lots = await inventory_cost.available_lots(session, pg_book[0], InventoryLotQuery(
            policy_id=pg_book[1], posting_date=date(2026, 7, 1), account="41", warehouse="warehouse1",
            sku="OPENING-TEST-SKU", search="opening-0000"))
        assert lots["lots"] == [{"lot": "opening-0000", "book_quantity": "2.123456",
                                  "book_value_byn": "12.34", "selectable": True, "reason": None}]


@pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)
async def test_opening_stock_pg_second_part_failure_rolls_back_everything(pg_factory, pg_book, monkeypatch):
    document = await _stock_document(pg_factory, pg_book)
    async with pg_factory() as session:
        preview = await opening_stock.preview(session, pg_book[0], document)
        before = (await session.get(Organization, pg_book[0])).generation
        await session.commit()
    command = opening_stock.StockConfirm(document=document, preview_digest=preview["preview_digest"],
                                         acknowledge_addition=True)
    original = service.post

    async def fail_second(*args, **kwargs):
        if args[2].source.endswith(":001"):
            raise service.AccountingError("Synthetic failure after the first persisted part")
        return await original(*args, **kwargs)

    monkeypatch.setattr(service, "post", fail_second)
    async with pg_factory() as session:
        with pytest.raises(service.AccountingError, match="after the first persisted part"):
            await opening_stock.confirm(session, pg_book[0], command, "tester")
        await session.commit()
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Entry)) == 0
        assert await session.scalar(select(func.count()).select_from(Line)) == 0
        assert (await session.get(Organization, pg_book[0])).generation == before
        assert await session.scalar(select(func.count()).select_from(StockMovement)) == 0
