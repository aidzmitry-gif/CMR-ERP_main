from copy import deepcopy
from uuid import uuid4

from sqlalchemy import select

from modules.accounting.models import OpeningImportReceipt


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
