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
