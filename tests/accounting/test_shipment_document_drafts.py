from uuid import uuid4

from sqlalchemy import func, select, update

from modules.accounting import routes
from modules.accounting.models import AccessGrant, Entry, ShipmentPreparationDraft


def receipt(organization_id, source_key, digest="a" * 64):
    return {"receipt": {
        "act_id": 17,
        "source_key": source_key,
        "digest": digest,
        "snapshot": {
            "organization_id": organization_id,
            "document_id": 81,
            "document_version": 2,
            "operation_date": "2026-09-13",
            "lines": [{
                "line_no": 1,
                "sku_code": "A",
                "warehouse": "W",
                "qty": "1.00",
                "source": "sales:document:81:line:1",
            }],
        },
    }}


def body(digest="a" * 64, *, expected_revision=0, request_key=None, **field_changes):
    fields = {
        "sender_legal_entity": "ООО Альфа",
        "recipient_legal_entity": "ООО Бета",
        "contract_reference": "Договор 12",
        "document_number": "Черновик 12",
        "document_date": "2026-09-13",
        "carrier": "Перевозчик",
        "vehicle_registration": "1234 AB-7",
        "driver": "Иванов И.И.",
        "route": "Минск — Брест",
        "loading_point": "Минск",
        "unloading_point": "Брест",
        "items": [{"line_no": 1, "unit": "шт", "unit_price": "12.50", "vat_basis": "20%"}],
    }
    fields.update(field_changes)
    return {
        "kind": "ttn",
        "request_key": str(request_key or uuid4()),
        "expected_revision": expected_revision,
        "source_digest": digest,
        "fields": fields,
    }


async def connect_source(monkeypatch, organization_id, source_key, digest="a" * 64):
    async def verified(_session, _org, _key, _core):
        return receipt(organization_id, source_key, digest)

    monkeypatch.setattr(routes, "verified_shipment_source", verified)


async def test_tn_ttn_draft_versions_replay_history_and_conflict_without_posting(client, db, book, monkeypatch):
    organization_id = book[0]
    source_key = str(uuid4())
    await connect_source(monkeypatch, organization_id, source_key)
    url = f"/accounting/organizations/{organization_id}/shipments/{source_key}/tn-ttn-draft"

    initial = await client.get(f"{url}?kind=ttn")
    assert initial.status_code == 200, initial.text
    assert initial.json()["saved_revision"] == 0
    assert initial.json()["can_issue"] is False
    first_body = body()
    first = await client.post(url, json=first_body)
    assert first.status_code == 200, first.text
    assert first.json()["saved_revision"] == 1
    assert first.json()["saved_by"] == "tester"
    assert first.json()["saved_at"].endswith("Z")
    assert first.json()["history"][0]["actor"] == "tester"
    assert first.json()["can_issue"] is False

    replay = await client.post(url, json=first_body)
    assert replay.status_code == 200, replay.text
    assert replay.json()["saved_revision"] == 1
    assert await db.scalar(select(func.count()).select_from(ShipmentPreparationDraft)) == 1

    stale = await client.post(url, json=body(expected_revision=0, recipient_legal_entity="ООО Другая"))
    assert stale.status_code == 409
    second = await client.post(url, json=body(expected_revision=1, sender_legal_entity="ООО Гамма"))
    assert second.status_code == 200, second.text
    change = next(item for item in second.json()["history"][1]["changes"] if item["field"] == "sender_legal_entity")
    assert (change["before"], change["after"]) == ("ООО Альфа", "ООО Гамма")
    assert second.json()["history"][1]["actor"] == "tester"
    assert second.json()["history"][1]["created_at"].endswith("Z")
    assert await db.scalar(select(func.count()).select_from(ShipmentPreparationDraft)) == 2
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0

    await connect_source(monkeypatch, organization_id, source_key, "b" * 64)
    stale_source = await client.post(url, json=body(expected_revision=2))
    assert stale_source.status_code == 409
    assert await db.scalar(select(func.count()).select_from(ShipmentPreparationDraft)) == 2


async def test_tn_ttn_draft_rejects_foreign_source_lines_and_reader_writes(client, db, book, monkeypatch):
    organization_id = book[0]
    source_key = str(uuid4())
    await connect_source(monkeypatch, organization_id, source_key)
    url = f"/accounting/organizations/{organization_id}/shipments/{source_key}/tn-ttn-draft"
    invalid_line = body(items=[{"line_no": 999, "unit": "шт", "unit_price": "1", "vat_basis": ""}])
    assert (await client.post(url, json=invalid_line)).status_code == 409
    assert await db.scalar(select(func.count()).select_from(ShipmentPreparationDraft)) == 0

    await db.execute(update(AccessGrant).where(AccessGrant.organization_id == organization_id).values(role="reader"))
    await db.commit()
    assert (await client.get(f"{url}?kind=ttn")).status_code == 200
    assert (await client.post(url, json=body())).status_code == 403


async def test_tn_draft_rejects_ttn_only_fields(client, book, monkeypatch):
    organization_id = book[0]
    source_key = str(uuid4())
    await connect_source(monkeypatch, organization_id, source_key)
    url = f"/accounting/organizations/{organization_id}/shipments/{source_key}/tn-ttn-draft"
    data = body()
    data["kind"] = "tn"
    assert (await client.post(url, json=data)).status_code == 422
