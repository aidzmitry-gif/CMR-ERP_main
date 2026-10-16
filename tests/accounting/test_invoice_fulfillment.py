import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from core.services.auth import CurrentUser
from modules.accounting import service
from modules.accounting.gateway import AccountingService
from modules.accounting.models import Entry, Line


async def read(db, book, document=17):
    return await AccountingService().invoice_fulfillment_snapshot(
        db, book[0], CurrentUser("tester", ["director"]), document,
    )


async def test_empty_ledger_is_not_complete_fulfillment_coverage(db, book):
    result = await read(db, book)
    assert result["facts"]["entries"] == []
    assert result["facts"]["coverage_complete"] is False
    assert result == await read(db, book)


async def test_exact_references_and_both_correction_directions(db, book, posting):
    unrelated = await service.post(db, book[0], posting(source="sales:document:170"), "tester")
    root = await service.post(db, book[0], posting(source="legacy-original"), "tester")
    linked = await service.post(db, book[0], posting(
        source="sales:document:17", correction_of=root.id,
    ), "tester")
    correction = await service.post(db, book[0], posting(
        source="correction-without-invoice-ref", correction_of=linked.id,
        debit="60", credit="41",
    ), "tester")
    result = await read(db, book)
    assert [row["id"] for row in result["facts"]["entries"]] == [root.id, linked.id, correction.id]
    assert unrelated.id not in {line["entry_id"] for line in result["facts"]["lines"]}
    assert len(result["facts"]["lines"]) == 6
    assert result["facts"]["coverage_complete"] is False
    assert result["facts"]["missing_correction_ids"] == []


async def test_manual_analytical_match_changes_digest_and_is_not_net_dropped(db, book, posting):
    before = await read(db, book)
    data = posting(source="manual-ref")
    data.lines[0].dimensions = {"settlement_document": "sales:document:17"}
    entry = await service.post(db, book[0], data, "tester")
    after = await read(db, book)
    assert before["digest"] != after["digest"]
    assert [row["id"] for row in after["facts"]["entries"]] == [entry.id]
    assert after["facts"]["lines"][0]["amount"] == "100.00"
    await db.rollback()
    assert (await read(db, book))["facts"]["entries"] == []


@pytest.mark.parametrize("document", [0, -1, True, "17"])
async def test_rejects_ambiguous_invoice_id(db, book, document):
    with pytest.raises(HTTPException) as rejected:
        await read(db, book, document)
    assert rejected.value.status_code == 422


async def test_foreign_org_cannot_read_evidence(db, book):
    with pytest.raises(HTTPException) as rejected:
        await AccountingService().invoice_fulfillment_snapshot(
            db, book[0], CurrentUser("stranger", ["director"]), 17,
        )
    assert rejected.value.status_code == 403


async def test_unposted_source_and_queue_invalidate_review_before_ledger_entry(db, book, posting):
    before = await read(db, book)
    gateway = AccountingService()
    await gateway.source_changed(db, book[0], CurrentUser("tester", ["director"]),
                                 "sales:document:17", 1, "2026-09-01")
    data = posting(source="imported-manual")
    data.lines[0].dimensions = {"settlement_document": "sales:document:17"}
    queued = await service.receive(db, book[0], "test-queue-17", "2026-09", data.model_dump(mode="json"))
    await service.receive(db, book[0], "test-queue-other", "2026-09", posting().model_dump(mode="json"))
    after = await read(db, book)
    assert after["digest"] != before["digest"]
    assert after["facts"]["entries"] == []
    assert [row["id"] for row in after["facts"]["inbox"]] == [queued.id]
    assert after["facts"]["source_controls"][0]["entry_id"] is None


async def test_reloads_sql_facts_and_correction_parent_despite_identity_map(db, book, posting):
    parent = await service.post(db, book[0], posting(source="old-parent"), "tester")
    child = await service.post(db, book[0], posting(source="sales:document:17"), "tester")
    held_lines = (await db.scalars(select(Line).where(Line.entry_id == child.id))).all()
    before = await read(db, book)
    await db.execute(update(Entry).where(Entry.id == child.id).values(correction_of=parent.id)
                     .execution_options(synchronize_session=False))
    await db.execute(update(Line).where(Line.id == held_lines[0].id)
                     .values(dimensions={"contract": "actual SQL value"})
                     .execution_options(synchronize_session=False))
    assert child.correction_of is None
    assert held_lines[0].dimensions == {}
    after = await read(db, book)
    assert after["digest"] != before["digest"]
    assert [row["id"] for row in after["facts"]["entries"]] == [parent.id, child.id]
    assert next(row for row in after["facts"]["lines"] if row["id"] == held_lines[0].id)["dimensions"] == {
        "contract": "actual SQL value",
    }


async def test_queued_correction_without_direct_invoice_reference_changes_snapshot(db, book, posting):
    original = await service.post(db, book[0], posting(source="sales:document:17"), "tester")
    before = await read(db, book)
    correction = posting(source="correction-in-review", correction_of=original.id)
    queued = await service.receive(db, book[0], "queued-correction", "2026-09",
                                   correction.model_dump(mode="json"))
    assert queued.error is None and queued.entry_id is None
    after = await read(db, book)
    assert after["digest"] != before["digest"]
    assert [row["id"] for row in after["facts"]["inbox"]] == [queued.id]
