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


@pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)
async def test_opening_stock_pg_http_access_preview_confirm_and_replay(pg_factory, pg_book, monkeypatch):
    from types import SimpleNamespace

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from core.domain.models import OutboxEvent, User
    from core.runtime.deps import get_session
    from core.services.eventbus import OutboxEventBus
    from modules.accounting import routes
    from modules.accounting.models import AccessGrant, OpeningImportReceipt

    document = (await _stock_document(pg_factory, pg_book)).model_dump(mode="json")
    document["rows"] = document["rows"][:1]
    async with pg_factory() as session:
        session.add_all([User(username=name, full_name="Synthetic opening user", role="director", status=status)
                         for name, status in (("tester", "active"), ("opening-reader", "active"),
                                              ("opening-outside", "active"), ("opening-inactive", "blocked"))])
        next_id = (await session.scalar(select(func.max(AccessGrant.id)))) + 1
        session.add_all([AccessGrant(id=next_id + offset, organization_id=pg_book[0], subject=name, role=role)
                         for offset, (name, role) in enumerate((("opening-reader", "reader"),
                                                                ("opening-inactive", "chief")))])
        await session.commit()
    settings = SimpleNamespace(auth_mode="dev")
    monkeypatch.setattr("core.services.auth.get_settings", lambda: settings)
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    app = FastAPI()
    app.include_router(routes.router, prefix="/accounting")
    app.state.core = SimpleNamespace(services=SimpleNamespace(event_bus=OutboxEventBus()))

    async def sessions():
        async with pg_factory() as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    url = f"/accounting/organizations/{pg_book[0]}/opening-stock/"
    chief = {"X-User": "tester", "X-User-Roles": "director"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://synthetic-local") as client:
        context = await client.get(url + "context?on=2026-07-01", headers=chief)
        assert context.status_code == 200, context.text
        assert context.headers["cache-control"] == "private, no-store"
        preview = await client.post(url + "preview", json=document, headers=chief)
        assert preview.status_code == 200, preview.text
        assert preview.headers["cache-control"] == "private, no-store"
        command = {"document": document, "preview_digest": preview.json()["preview_digest"],
                   "acknowledge_addition": True}
        for name, get_detail, post_detail in (
            ("opening-reader", "Chief accountant access required", "Read-only accounting access"),
            ("opening-outside", "No access to this organization's books", "No access to this organization's books"),
            ("opening-inactive", "Accounting access denied", "Accounting access denied"),
        ):
            headers = {"X-User": name, "X-User-Roles": "director"}
            denied = await client.get(url + "context?on=2026-07-01", headers=headers)
            assert denied.status_code == 403 and denied.json()["detail"] == get_detail
            for suffix, payload in (("preview", document), ("confirm", command)):
                denied = await client.post(url + suffix, json=payload, headers=headers)
                assert denied.status_code == 403 and denied.json()["detail"] == post_detail
        async with pg_factory() as session:
            assert await session.scalar(select(func.count()).select_from(Entry)) == 0
            assert await session.scalar(select(func.count()).select_from(Line)) == 0
        confirmed = await client.post(url + "confirm", json=command, headers=chief)
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.headers["cache-control"] == "private, no-store"
        assert confirmed.json()["confirmed"] is True and len(confirmed.json()["entry_ids"]) == 1
        assert confirmed.json()["physical_stock_updated"] is confirmed.json()["cutover_finalized"] is False
        async with pg_factory() as session:
            events = await session.scalar(select(func.count()).select_from(OutboxEvent))
        replay = await client.post(url + "confirm", json=command, headers=chief)
        assert replay.status_code == 200, replay.text
        assert replay.json()["entry_ids"] == confirmed.json()["entry_ids"]
        async with pg_factory() as session:
            assert await session.scalar(select(func.count()).select_from(Entry)) == 1
            assert await session.scalar(select(func.count()).select_from(Line)) == 2
            assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == events
            assert await session.scalar(select(func.count()).select_from(StockMovement)) == 0
            assert await session.scalar(select(func.count()).select_from(OpeningImportReceipt)) == 0


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
