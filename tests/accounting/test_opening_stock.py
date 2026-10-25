from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from core.domain.models import Sku
from modules.accounting import inventory_cost, opening_stock, service
from modules.accounting.models import (
    AccessGrant,
    Account,
    Entry,
    Line,
    OpeningImportReceipt,
    Policy,
)
from modules.accounting.schemas import InventoryLotQuery


@pytest.fixture
async def stock(db, book):
    account = await db.scalar(select(Account).where(Account.organization_id == book[0], Account.code == "41"))
    db.add(Account(organization_id=book[0], code="41", title=account.title, category="asset",
                   valid_from=date(2026, 6, 1), required_dimensions=["warehouse", "sku", "lot"],
                   quantity_tracking=True, currency_tracking=False, cash=False, normative_ref="synthetic"))
    db.add(Sku(code="TEST-STOCK", title="Synthetic stock item", unit="шт", is_active=True))
    await db.commit()
    return {"request_key": str(uuid4()), "opening_date": "2026-07-01", "policy_id": book[1],
            "inventory_account": "41", "counter_account": "80", "evidence": "Synthetic opening report",
            "rows": [{"sku": "TEST-STOCK", "warehouse": "warehouse1", "lot": "opening-layer-1",
                      "quantity": "3", "amount_byn": "12.34"}]}


async def enter(client, book, data):
    url = f"/accounting/organizations/{book[0]}/opening-stock/"
    preview = await client.post(url + "preview", json=data)
    assert preview.status_code == 200, preview.text
    response = await client.post(url + "confirm", json={"document": data,
        "preview_digest": preview.json()["preview_digest"], "acknowledge_addition": True})
    assert response.status_code == 200, response.text
    return response.json(), preview.json()


async def test_stock_preview_is_read_only_and_confirmation_costs_read_back(client, db, book, stock):
    url = f"/accounting/organizations/{book[0]}/opening-stock/"
    preview = await client.post(url + "preview", json=stock)
    assert preview.status_code == 200, preview.text
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0
    assert preview.json()["rows"][0]["sku_title"] == "Synthetic stock item"
    receipt, _ = await enter(client, book, stock)
    assert receipt["total_byn"] == "12.34"
    assert receipt["physical_stock_updated"] is receipt["cutover_finalized"] is False
    assert await db.scalar(select(func.count()).select_from(OpeningImportReceipt)) == 0
    lots = await inventory_cost.available_lots(db, book[0], InventoryLotQuery(
        policy_id=book[1], account="41", warehouse="warehouse1", sku="TEST-STOCK", posting_date=date(2026, 7, 1)))
    assert lots["lots"][0]["book_quantity"] == "3.000000"
    assert lots["lots"][0]["book_value_byn"] == "12.34"


async def test_stock_1384_rows_atomic_parts_and_replay_after_directory_change(client, db, book, stock):
    stock["rows"] = [{**stock["rows"][0], "lot": f"layer-{i}"} for i in range(1384)]
    receipt, preview = await enter(client, book, stock)
    assert len(receipt["entry_ids"]) == 3
    assert receipt["row_count"] == 1384
    assert receipt["total_byn"] == "17078.56"
    assert await db.scalar(select(func.count()).select_from(Line)) == 2768
    sku = await db.scalar(select(Sku).where(Sku.code == "TEST-STOCK"))
    sku.is_active = False
    await db.commit()
    url = f"/accounting/organizations/{book[0]}/opening-stock/confirm"
    replay = await client.post(url, json={"document": stock, "preview_digest": preview["preview_digest"], "acknowledge_addition": True})
    assert replay.status_code == 200, replay.text
    assert replay.json()["entry_ids"] == receipt["entry_ids"]
    assert await db.scalar(select(func.count()).select_from(Entry)) == 3
    stock["rows"].pop()
    changed = await client.post(url, json={"document": stock, "preview_digest": preview["preview_digest"], "acknowledge_addition": True})
    assert changed.status_code == 422


async def test_stock_second_part_failure_rolls_back_whole_document(db, book, stock, monkeypatch):
    stock["rows"] = [{**stock["rows"][0], "lot": f"layer-{i}"} for i in range(501)]
    data = opening_stock.StockInput.model_validate(stock)
    preview = await opening_stock.preview(db, book[0], data)
    original = service.post
    async def fail_second(*args, **kwargs):
        if args[2].source.endswith(":001"):
            raise service.AccountingError("synthetic second-part failure")
        return await original(*args, **kwargs)
    monkeypatch.setattr(service, "post", fail_second)
    with pytest.raises(service.AccountingError, match="second-part"):
        await opening_stock.confirm(db, book[0], opening_stock.StockConfirm(
            document=data, preview_digest=preview["preview_digest"], acknowledge_addition=True), "tester")
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0
    assert await db.scalar(select(func.count()).select_from(Line)) == 0


async def test_stock_policy_change_invalidates_preview(client, db, book, stock):
    data = opening_stock.StockInput.model_validate(stock)
    preview = await opening_stock.preview(db, book[0], data)
    policy = await db.get(Policy, book[1])
    db.add(Policy(organization_id=book[0], effective_from=date(2026, 6, 1), reference="NEW TEST ONLY",
                  inventory_method="fifo", allocation_basis=policy.allocation_basis,
                  depreciation_method=policy.depreciation_method, normative_reference="synthetic",
                  normative_verified=True, approved_by="tester"))
    await db.commit()
    response = await client.post(f"/accounting/organizations/{book[0]}/opening-stock/confirm", json={
        "document": stock, "preview_digest": preview["preview_digest"], "acknowledge_addition": True})
    assert response.status_code == 422
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0


@pytest.mark.parametrize("change", [
    {"quantity": "0"}, {"quantity": 1.1}, {"amount_byn": "0"}, {"amount_byn": "1.001"},
    {"lot": " "}, {"sku": "UNKNOWN"}, {"warehouse": "foreign-warehouse"},
])
async def test_stock_invalid_rows_fail_without_writes(client, db, book, stock, change):
    stock["rows"][0].update(change)
    response = await client.post(f"/accounting/organizations/{book[0]}/opening-stock/preview", json=stock)
    assert response.status_code == 422
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0


async def test_stock_requires_chief_and_addition_acknowledgement(client, db, book, stock):
    data = opening_stock.StockInput.model_validate(stock)
    preview = await opening_stock.preview(db, book[0], data)
    url = f"/accounting/organizations/{book[0]}/opening-stock/"
    response = await client.post(url + "confirm", json={"document": stock,
        "preview_digest": preview["preview_digest"], "acknowledge_addition": False})
    assert response.status_code == 422
    grant = await db.scalar(select(AccessGrant).where(AccessGrant.organization_id == book[0]))
    grant.role = "reader"
    await db.commit()
    assert (await client.post(url + "preview", json=stock)).status_code == 403
    assert (await client.get(url + "context?on=2026-07-01")).status_code == 403


async def test_stock_new_document_adds_and_preserves_other_opening(client, db, book, stock, posting):
    other = await service.post(db, book[0], posting("other-opening", "51", "80", "99.00",
        posting_date="2026-07-01", document_date="2026-07-01", operation_date="2026-07-01", opening=True), "tester")
    await db.commit()
    await enter(client, book, stock)
    stock["request_key"] = str(uuid4())
    await enter(client, book, stock)
    assert await db.scalar(select(func.count()).select_from(Entry)) == 3
    assert (await db.get(Entry, other.id)).digest == service.digest(posting("other-opening", "51", "80", "99.00",
        posting_date="2026-07-01", document_date="2026-07-01", operation_date="2026-07-01", opening=True))
    lots = await inventory_cost.available_lots(db, book[0], InventoryLotQuery(
        policy_id=book[1], account="41", warehouse="warehouse1", sku="TEST-STOCK", posting_date=date(2026, 7, 1)))
    assert lots["lots"][0]["book_quantity"] == "6.000000"


async def test_stock_refuses_ordinary_postings_and_generic_bypass(client, db, book, stock, posting):
    data = opening_stock.StockInput.model_validate(stock)
    _, commands = await opening_stock._prepare(db, book[0], data)
    response = await client.post(f"/accounting/organizations/{book[0]}/entries", json=commands[0].model_dump(mode="json"))
    assert response.status_code == 422
    await service.post(db, book[0], posting("ordinary", "51", "80"), "tester")
    await db.commit()
    response = await client.get(f"/accounting/organizations/{book[0]}/opening-stock/context?on=2026-07-01")
    assert response.status_code == 422


async def test_stock_corrupted_persisted_line_blocks_replay(client, db, book, stock):
    _, preview = await enter(client, book, stock)
    line = await db.scalar(select(Line).where(Line.side == "debit"))
    await db.execute(update(Line).where(Line.id == line.id).values(amount=Decimal("13.00")))
    await db.commit()
    response = await client.post(f"/accounting/organizations/{book[0]}/opening-stock/confirm", json={
        "document": stock, "preview_digest": preview["preview_digest"], "acknowledge_addition": True})
    assert response.status_code == 422


async def test_stock_context_excludes_accounts_with_unsupported_analytics(db, book, stock):
    db.add(Account(organization_id=book[0], code="60.01", title="Synthetic settlements", category="liability",
                   valid_from=date(2026, 1, 1), required_dimensions=["counterparty"],
                   quantity_tracking=False, currency_tracking=False, cash=False, normative_ref="synthetic"))
    await db.commit()
    result = await opening_stock.context(db, book[0], date(2026, 7, 1))
    assert "60.01" not in {a["code"] for a in result["counter_accounts"]}


async def test_stock_replay_survives_final_import_but_new_key_is_blocked(client, db, book, stock, opening_package):
    receipt, preview = await enter(client, book, stock)
    entry = await db.get(Entry, receipt["entry_ids"][0])
    lines = (await db.scalars(select(Line).where(Line.entry_id == entry.id).order_by(Line.id))).all()
    package = opening_package([opening_stock._posting_from_entry(entry, lines)])
    response = await client.post(f"/accounting/organizations/{book[0]}/imports/confirm", json=package)
    assert response.status_code == 200, response.text
    command = {"document": stock, "preview_digest": preview["preview_digest"], "acknowledge_addition": True}
    url = f"/accounting/organizations/{book[0]}/opening-stock/confirm"
    replay = await client.post(url, json=command)
    assert replay.status_code == 200, replay.text
    assert replay.json()["entry_ids"] == receipt["entry_ids"]
    stock["request_key"] = str(uuid4())
    assert (await client.post(url, json=command)).status_code == 422
    assert await db.scalar(select(func.count()).select_from(Entry)) == 1
