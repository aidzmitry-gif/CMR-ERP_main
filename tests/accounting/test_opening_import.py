from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from modules.accounting import opening_import, service
from modules.accounting.models import Entry, Line, OpeningImportReceipt
from modules.accounting.schemas import ImportInput


async def test_opening_import_protocol_preview_confirm_and_list(client, db, book, posting, opening_package):
    prefix = f"/accounting/organizations/{book[0]}"
    data = opening_package([posting("opening", "51", "80", "100.00", opening=True)], batch="protocol-1")

    preview = await client.post(prefix + "/imports/preview", json=data)
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["confirmed"] is False
    assert preview_body["control_totals"] == {
        "entry_count": 1, "line_count": 2, "debit_byn": "100.00", "credit_byn": "100.00",
    }
    assert preview_body["source_digest"] == "a" * 64
    assert len(preview_body["command_digest"]) == 64

    confirmed = await client.post(prefix + "/imports/confirm", json=data)
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["confirmed"] is True
    assert body["control_totals"]["debit_byn"] == "100.00"
    assert body["entry_ids"]
    assert body["snapshot"]["entries"][0]["entry_id"] == body["entry_ids"][0]

    replay = await client.post(prefix + "/imports/confirm", json=data)
    assert replay.status_code == 200
    assert replay.json()["receipt_id"] == body["receipt_id"]
    assert await db.scalar(select(OpeningImportReceipt.id)) == body["receipt_id"]

    listed = await client.get(prefix + "/imports")
    assert listed.status_code == 200
    assert listed.json()[0]["request_key"] == data["request_key"]


async def test_opening_import_rejects_control_total_and_cutover_mismatch(client, book, posting, opening_package):
    prefix = f"/accounting/organizations/{book[0]}"
    invalid_total = opening_package([posting("opening", "51", "80", opening=True)], batch="bad-total")
    invalid_total["expected_debit_byn"] = "101.00"
    response = await client.post(prefix + "/imports/preview", json=invalid_total)
    assert response.status_code == 422

    first = posting("opening-a", "51", "80", opening=True)
    second = posting("opening-b", "51", "80", posting_date="2026-10-01",
                    document_date="2026-10-01", operation_date="2026-10-01", opening=True)
    mixed = opening_package([first, second], batch="mixed-cutover")
    response = await client.post(prefix + "/imports/preview", json=mixed)
    assert response.status_code == 422


async def test_opening_import_same_package_cannot_use_another_request_key(client, book, posting, opening_package):
    prefix = f"/accounting/organizations/{book[0]}"
    data = opening_package([posting("opening", "51", "80", opening=True)], batch="duplicate-package")
    assert (await client.post(prefix + "/imports/confirm", json=data)).status_code == 200
    other_key = deepcopy(data)
    other_key["request_key"] = str(uuid4())
    response = await client.post(prefix + "/imports/confirm", json=other_key)
    assert response.status_code == 422


async def test_opening_import_rejects_second_package_for_same_cutover(client, db, book, posting, opening_package):
    prefix = f"/accounting/organizations/{book[0]}"
    first = opening_package([posting("opening-first", "51", "80", opening=True)], batch="first")
    second = opening_package([posting("opening-second", "51", "80", opening=True)], batch="second")
    accepted = await client.post(prefix + "/imports/confirm", json=first)
    assert accepted.status_code == 200, accepted.text

    preview = await client.post(prefix + "/imports/preview", json=second)
    confirm = await client.post(prefix + "/imports/confirm", json=second)
    assert preview.status_code == 422
    assert confirm.status_code == 422
    assert "cutover date" in confirm.text
    receipts = (await db.scalars(select(OpeningImportReceipt))).all()
    assert len(receipts) == 1
    assert receipts[0].id == accepted.json()["receipt_id"]


async def test_accepted_opening_import_freezes_manual_opening_entries(client, book, posting, opening_package):
    prefix = f"/accounting/organizations/{book[0]}"
    package = opening_package([posting("package-opening", "51", "80", opening=True)])
    accepted = await client.post(prefix + "/imports/confirm", json=package)
    assert accepted.status_code == 200, accepted.text

    extra = posting("manual-extra-opening", "51", "80", opening=True)
    response = await client.post(prefix + "/entries", json=extra.model_dump(mode="json"))
    assert response.status_code == 422
    assert "frozen after the accepted import" in response.text

    replay = await client.post(prefix + "/imports/confirm", json=package)
    assert replay.status_code == 200
    assert replay.json()["receipt_id"] == accepted.json()["receipt_id"]


async def test_opening_import_rejects_unlisted_existing_opening_entries(client, book, posting, opening_package):
    prefix = f"/accounting/organizations/{book[0]}"
    extra = posting("manual-opening-outside-package", "51", "80", opening=True)
    manual = await client.post(prefix + "/entries", json=extra.model_dump(mode="json"))
    assert manual.status_code == 201, manual.text

    package = opening_package([posting("package-opening", "51", "80", opening=True)])
    preview = await client.post(prefix + "/imports/preview", json=package)
    confirm = await client.post(prefix + "/imports/confirm", json=package)
    assert preview.status_code == 422
    assert confirm.status_code == 422
    assert "omits existing opening entries" in confirm.text


async def test_opening_import_can_include_identical_existing_opening_entry(client, book, posting, opening_package):
    prefix = f"/accounting/organizations/{book[0]}"
    entry = posting("manual-opening-in-package", "51", "80", opening=True)
    manual = await client.post(prefix + "/entries", json=entry.model_dump(mode="json"))
    assert manual.status_code == 201, manual.text

    package = opening_package([entry])
    accepted = await client.post(prefix + "/imports/confirm", json=package)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["entry_ids"] == [manual.json()["id"]]


async def test_opening_import_rejects_duplicate_entry_identity(client, book, posting, opening_package):
    prefix = f"/accounting/organizations/{book[0]}"
    entry = posting("same-opening", "51", "80", opening=True)
    package = opening_package([entry, entry])
    response = await client.post(prefix + "/imports/preview", json=package)
    assert response.status_code == 422
    assert "distinct posting identities" in response.text


def _large_opening_package(posting, opening_package, line_count):
    """Synthetic cash/equity lines exercise package capacity, not stock identities."""
    sizes = []
    while line_count > 1000:
        sizes.append(1000)
        line_count -= 1000
    if line_count == 1:
        sizes[-1] -= 1
        line_count += 1
    sizes.append(line_count)
    entries = []
    for index, size in enumerate(sizes):
        entry = posting(f"large-opening-{index}", "51", "80", f"{size - 1}.00", opening=True)
        debit = entry.lines[0].model_copy(update={"amount": Decimal("1.00")})
        entry.lines = [debit.model_copy() for _ in range(size - 1)] + [entry.lines[1]]
        entries.append(entry)
    return opening_package(entries, batch="synthetic-large-opening")


async def test_large_atomic_opening_import_confirm_readback_and_replay(
    client, db, book, posting, opening_package
):
    prefix = f"/accounting/organizations/{book[0]}"
    data = _large_opening_package(posting, opening_package, 1195)
    preview = await client.post(prefix + "/imports/preview", json=data)
    assert preview.status_code == 200, preview.text
    assert preview.json()["control_totals"]["line_count"] == 1195
    confirmed = await client.post(prefix + "/imports/confirm", json=data)
    assert confirmed.status_code == 200, confirmed.text
    receipt = confirmed.json()
    assert receipt["confirmed"] is True
    assert receipt["control_totals"] == {
        "entry_count": 2, "line_count": 1195,
        "debit_byn": "1193.00", "credit_byn": "1193.00",
    }
    assert len(receipt["entry_ids"]) == 2
    assert await db.scalar(select(func.count()).select_from(Line)) == 1195
    listed = await client.get(prefix + "/imports")
    assert listed.status_code == 200
    assert listed.json()[0]["receipt_id"] == receipt["receipt_id"]
    replay = await client.post(prefix + "/imports/confirm", json=data)
    assert replay.status_code == 200
    assert replay.json()["receipt_id"] == receipt["receipt_id"]
    assert await db.scalar(select(func.count()).select_from(OpeningImportReceipt)) == 1
    assert await db.scalar(select(func.count()).select_from(Line)) == 1195


async def test_large_atomic_opening_import_rolls_back_late_post_failure(
    client, db, book, posting, opening_package, monkeypatch
):
    data = _large_opening_package(posting, opening_package, 1195)
    original_post = opening_import.service.post
    posted = []

    async def fail_second_post(*args, **kwargs):
        if posted:
            raise service.AccountingError("Synthetic late posting failure")
        entry = await original_post(*args, **kwargs)
        posted.append(entry.id)
        return entry

    monkeypatch.setattr(opening_import.service, "post", fail_second_post)
    response = await client.post(f"/accounting/organizations/{book[0]}/imports/confirm", json=data)
    assert response.status_code == 422, response.text
    assert "Synthetic late posting failure" in response.text
    assert len(posted) == 1
    for model in (Entry, Line, OpeningImportReceipt):
        assert await db.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize("line_count,accepted", [(10000, True), (10001, False)])
def test_opening_import_total_line_capacity_boundary(posting, opening_package, line_count, accepted):
    data = _large_opening_package(posting, opening_package, line_count)
    if accepted:
        assert ImportInput.model_validate(data).expected_line_count == line_count
    else:
        with pytest.raises(ValidationError) as error:
            ImportInput.model_validate(data)
        assert any(e["loc"] == ("expected_line_count",) for e in error.value.errors())


def test_large_opening_import_rejects_false_declared_line_count(posting, opening_package):
    data = _large_opening_package(posting, opening_package, 1195)
    data["expected_line_count"] = 1000
    with pytest.raises(ValidationError, match="line count does not match"):
        ImportInput.model_validate(data)


def test_large_opening_import_retains_per_entry_line_limit(posting, opening_package):
    data = _large_opening_package(posting, opening_package, 1000)
    data["entries"][0]["lines"].insert(0, deepcopy(data["entries"][0]["lines"][0]))
    data["expected_line_count"] = 1001
    with pytest.raises(ValidationError) as error:
        ImportInput.model_validate(data)
    assert any(e["loc"] == ("entries", 0, "lines") for e in error.value.errors())
