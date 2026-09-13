from copy import deepcopy

import pytest
from sqlalchemy import func, select, text

from modules.accounting import models, service, shipment_commands, shipment_preview
from tests.accounting.test_inventory_cost import move
from tests.accounting.test_shipment_preview import fixture


async def prepared(db, book, posting):
    receipt, raw = await fixture(db, book, posting)
    data = shipment_preview.ShipmentPlanInput(**raw)
    plan = await shipment_preview.prepare(db, book[0], receipt, data)
    return receipt, data, plan


async def test_complete_receipt_replays_without_consuming_stock_again(db, book, posting):
    receipt, data, plan = await prepared(db, book, posting)
    saved = await shipment_commands.confirm(
        db, book[0], receipt, data, plan["basis_digest"], "tester"
    )
    await db.commit()
    count = await db.scalar(select(func.count()).select_from(models.Entry))
    repeated = await shipment_commands.confirm(
        db, book[0], receipt, data, plan["basis_digest"], "tester"
    )
    assert repeated.id == saved.id
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == count
    assert saved.snapshot["mapping"] == plan["mapping"]
    assert saved.snapshot["commercial"] == plan["commercial"]
    assert await db.scalar(select(models.SourceControl.entry_id)) == saved.anchor_entry_id


async def test_replay_rejects_changed_commercial_treatment(db, book, posting):
    receipt, data, plan = await prepared(db, book, posting)
    await shipment_commands.confirm(db, book[0], receipt, data, plan["basis_digest"], "tester")
    await db.commit()
    changed = deepcopy(data)
    changed.explanation = "Different approved basis"
    with pytest.raises(service.AccountingError, match="different content"):
        await shipment_commands.confirm(
            db, book[0], receipt, changed, plan["basis_digest"], "tester"
        )


async def test_confirm_rejects_stale_inventory_basis_without_writes(db, book, posting):
    receipt, data, plan = await prepared(db, book, posting)
    await move(db, book, posting, "late-cost-basis", "3", "10.00")
    count = await db.scalar(select(func.count()).select_from(models.Entry))
    with pytest.raises(service.AccountingError, match="basis changed"):
        await shipment_commands.confirm(db, book[0], receipt, data, plan["basis_digest"], "tester")
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == count
    assert await db.scalar(select(models.SourceControl.entry_id)) is None


async def test_caller_rollback_removes_package_and_restores_pending_source(db, book, posting):
    receipt, data, plan = await prepared(db, book, posting)
    count = await db.scalar(select(func.count()).select_from(models.Entry))
    await shipment_commands.confirm(db, book[0], receipt, data, plan["basis_digest"], "tester")
    await db.rollback()
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == count
    assert await db.scalar(select(func.count()).select_from(models.ShipmentAccountingReceipt)) == 0
    assert await db.scalar(select(models.SourceControl.entry_id)) is None


async def test_replay_checks_actual_lines_even_when_entry_hash_is_unchanged(db, book, posting):
    receipt, data, plan = await prepared(db, book, posting)
    saved = await shipment_commands.confirm(
        db, book[0], receipt, data, plan["basis_digest"], "tester"
    )
    await db.commit()
    # SQLite has no production SQL guards: simulate corruption to test replay verification.
    await db.execute(
        text("UPDATE line SET amount=amount+0.01 WHERE entry_id=:entry"),
        {"entry": saved.anchor_entry_id},
    )
    await db.commit()
    with pytest.raises(service.AccountingError, match="content changed"):
        await shipment_commands.confirm(db, book[0], receipt, data, plan["basis_digest"], "tester")


async def test_unexpected_orphan_page_cannot_be_adopted(db, book, posting):
    receipt, data, plan = await prepared(db, book, posting)
    orphan = posting(plan["source"] + ":part:99", "90.4", "60")
    orphan.policy_id = book[1]
    await service.post(db, book[0], orphan, "tester")
    await db.commit()
    # Obtain a fresh basis; the refusal must be about orphan pages, not staleness.
    plan = await shipment_preview.prepare(db, book[0], receipt, data)
    with pytest.raises(service.AccountingError, match="without a complete receipt"):
        await shipment_commands.confirm(db, book[0], receipt, data, plan["basis_digest"], "tester")
    assert await db.scalar(select(models.SourceControl.entry_id)) is None


@pytest.mark.parametrize("fail_second_page", [False, True])
async def test_multi_page_package_commit_or_caller_rollback(
    db, book, posting, monkeypatch, fail_second_page
):
    receipt, raw = await fixture(db, book, posting)
    await move(db, book, posting, "large-stock", "1500", "5000.00")
    receipt["snapshot"]["lines"] = [
        {
            "source": f"physical-{i}",
            "line_no": i,
            "warehouse": "W",
            "sku_code": "SKU",
            "qty": "1.00",
        }
        for i in range(1, 502)
    ]
    raw["allocations"] = [
        {**raw["allocations"][0], "line_source": f"physical-{i}", "quantity": "1"}
        for i in range(1, 502)
    ]
    raw["commercial_lines"] = [
        {**raw["commercial_lines"][0], "line_no": i, "vat_rate": "0"} for i in range(1, 502)
    ]
    data = shipment_preview.ShipmentPlanInput(**raw)
    plan = await shipment_preview.prepare(db, book[0], receipt, data)
    assert len(plan["postings"]) == 2
    count = await db.scalar(select(func.count()).select_from(models.Entry))
    original_post = service.post

    async def failing_post(session, org_id, body, *args, **kwargs):
        if body.source.endswith(":part:2"):
            raise RuntimeError("Synthetic second page failure")
        return await original_post(session, org_id, body, *args, **kwargs)

    if fail_second_page:
        monkeypatch.setattr(service, "post", failing_post)
        with pytest.raises(RuntimeError, match="second page"):
            await shipment_commands.confirm(
                db, book[0], receipt, data, plan["basis_digest"], "tester"
            )
        await db.rollback()
        assert await db.scalar(select(func.count()).select_from(models.Entry)) == count
        assert (
            await db.scalar(select(func.count()).select_from(models.ShipmentAccountingReceipt)) == 0
        )
        assert await db.scalar(select(models.SourceControl.entry_id)) is None
    else:
        saved = await shipment_commands.confirm(
            db, book[0], receipt, data, plan["basis_digest"], "tester"
        )
        await db.commit()
        repeated = await shipment_commands.confirm(
            db, book[0], receipt, data, plan["basis_digest"], "tester"
        )
        assert repeated.id == saved.id
        assert len(saved.snapshot["pages"]) == 2
        assert await db.scalar(select(func.count()).select_from(models.Entry)) == count + 2
