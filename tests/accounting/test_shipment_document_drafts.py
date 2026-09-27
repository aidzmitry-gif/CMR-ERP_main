from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, update

from core.domain.models import Counterparty
from modules.accounting import routes
from modules.accounting.models import AccessGrant, Entry, ShipmentPreparationDraft
from modules.accounting.shipment_document_drafts import _verified_recipient_identity


def receipt(organization_id, source_key, digest="a" * 64):
    return {"receipt": {
        "act_id": 17,
        "source_key": source_key,
        "digest": digest,
        "snapshot": {
            "organization_id": organization_id,
            "document_id": 81,
            "document_version": 2,
            "content_sha256": "c" * 64,
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
        "recipient_counterparty_id": 1,
        "recipient_counterparty_revision": 1,
        "contract_source": "sales",
        "contract_id": 12,
        "contract_number": "Договор 12",
        "contract_title": "Договор продажи",
        "contract_version": 3,
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


def test_tn_ttn_source_recipient_requires_the_issued_invoice_buyer_and_company():
    invoice_snapshot = {
        "deal_id": 9,
        "buyer": {"counterparty_id": 31, "revision": 4, "name": "ООО Покупатель", "unp": "123456789"},
    }
    source_snapshot = {
        "organization_id": 1, "document_id": 81, "document_version": 2,
        "content_sha256": "c" * 64,
    }
    document = SimpleNamespace(
        id=81, deal_id=9, kind="invoice", version=2, content_sha256="c" * 64,
        snapshot_json=invoice_snapshot,
    )
    owner = SimpleNamespace(organization_id=1)
    binding = SimpleNamespace(organization_id=1, counterparty_id=31)
    counterparty = SimpleNamespace(
        id=31, is_active=True, merged_into_id=None, legal_name="ООО Покупатель",
        name="Покупатель", unp="123456789", revision=5,
    )
    identity = _verified_recipient_identity(
        1, source_snapshot, document, owner, binding, counterparty, object(),
    )
    assert identity == {
        "reference": "core.counterparties", "id": 31, "name": "ООО Покупатель",
        "unp": "123456789", "revision": 5, "directory_current": True,
        "source_document_id": 81, "source_document_version": 2,
    }
    archived = _verified_recipient_identity(
        1, source_snapshot, document, owner, binding,
        SimpleNamespace(id=31, is_active=False, merged_into_id=None), object(),
    )
    assert archived["name"] == "ООО Покупатель"
    assert archived["revision"] == 4
    assert archived["directory_current"] is False

    with pytest.raises(HTTPException, match="exact counterparty directory record"):
        _verified_recipient_identity(
            1, source_snapshot, document, owner,
            SimpleNamespace(organization_id=1, counterparty_id=32), counterparty, object(),
        )
    with pytest.raises(HTTPException, match="immutable CRM issuance receipt"):
        _verified_recipient_identity(1, source_snapshot, document, owner, binding, counterparty, None)
    with pytest.raises(HTTPException, match="one exact invoice version"):
        _verified_recipient_identity(
            2, source_snapshot, document, owner, binding, counterparty, object(),
        )


async def connect_source(monkeypatch, organization_id, source_key, digest="a" * 64):
    async def verified(_session, _org, _key, _core):
        return receipt(organization_id, source_key, digest)

    monkeypatch.setattr(routes, "verified_shipment_source", verified)

    async def source_recipient(session, _org, _receipt):
        counterparty = await session.get(Counterparty, 1)
        if counterparty is None:
            return {
                "reference": "core.counterparties", "id": 1, "name": "supplier1", "unp": "190000001",
                "revision": 1, "directory_current": False, "source_document_id": 81,
                "source_document_version": 2,
            }
        directory_current = counterparty.is_active and counterparty.merged_into_id is None
        return {
            "reference": "core.counterparties", "id": counterparty.id,
            "name": (counterparty.legal_name or counterparty.name) if directory_current else "supplier1",
            "unp": (counterparty.unp or "") if directory_current else "190000001",
            "revision": counterparty.revision if directory_current else 1,
            "directory_current": directory_current, "source_document_id": 81,
            "source_document_version": 2,
        }

    async def verified_contract(_session, _org, dimensions):
        if (dimensions.get("counterparty_id") != "1"
                or dimensions.get("contract_source") != "sales"
                or dimensions.get("contract_id") != "12"
                or dimensions.get("contract") != "Договор 12"
                or dimensions.get("contract_title") != "Договор продажи"
                or dimensions.get("contract_version") != "3"):
            from modules.accounting.service import AccountingError
            raise AccountingError("Contract directory record changed; select it again")
        return SimpleNamespace(id=12, number="Договор 12", version=3)

    monkeypatch.setattr(routes.shipment_document_drafts, "verified_shipment_recipient", source_recipient)
    monkeypatch.setattr(routes.shipment_document_drafts.contract_snapshot,
                        "verified_contract_snapshot", verified_contract)


async def test_tn_ttn_draft_versions_replay_history_and_conflict_without_posting(client, db, book, monkeypatch):
    organization_id = book[0]
    source_key = str(uuid4())
    await connect_source(monkeypatch, organization_id, source_key)
    url = f"/accounting/organizations/{organization_id}/shipments/{source_key}/tn-ttn-draft"

    initial = await client.get(f"{url}?kind=ttn")
    assert initial.status_code == 200, initial.text
    assert initial.json()["saved_revision"] == 0
    assert initial.json()["can_issue"] is False
    assert initial.json()["saved_fields"]["sender_identity"] == {
        "reference": "accounting.organization", "id": organization_id,
        "name": "Synthetic test company", "unp": "999999999",
    }
    assert initial.json()["directory_identity_status"] == "verified"
    first_body = body()
    first = await client.post(url, json=first_body)
    assert first.status_code == 200, first.text
    assert first.json()["saved_revision"] == 1
    assert first.json()["saved_by"] == "tester"
    assert first.json()["saved_at"].endswith("Z")
    assert first.json()["saved_fields"]["sender_legal_entity"] == "Synthetic test company"
    assert first.json()["saved_fields"]["recipient_identity"] == {
        "reference": "core.counterparties", "id": 1,
        "name": "supplier1", "unp": "190000001", "revision": 1,
        "directory_current": True,
        "source_document_id": 81, "source_document_version": 2,
    }
    assert first.json()["saved_fields"]["contract_identity"] == {
        "reference": "sales.deal_document", "source": "sales", "id": 12,
        "number": "Договор 12", "title": "Договор продажи", "version": 3,
    }
    assert first.json()["directory_identity_status"] == "verified"
    assert first.json()["history"][0]["actor"] == "tester"
    assert first.json()["can_issue"] is False

    replay = await client.post(url, json=first_body)
    assert replay.status_code == 200, replay.text
    assert replay.json()["saved_revision"] == 1
    assert await db.scalar(select(func.count()).select_from(ShipmentPreparationDraft)) == 1

    stale = await client.post(url, json=body(expected_revision=0, document_number="Черновик 13"))
    assert stale.status_code == 409
    second = await client.post(url, json=body(expected_revision=1, document_number="Черновик 13"))
    assert second.status_code == 200, second.text
    change = next(item for item in second.json()["history"][1]["changes"] if item["field"] == "document_number")
    assert (change["before"], change["after"]) == ("Черновик 12", "Черновик 13")
    assert second.json()["history"][0]["fields"]["sender_identity"]["name"] == "Synthetic test company"
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


async def test_tn_ttn_party_identity_comes_from_live_directory_and_replay_keeps_snapshot(client, db, book, monkeypatch):
    organization_id = book[0]
    source_key = str(uuid4())
    await connect_source(monkeypatch, organization_id, source_key)
    url = f"/accounting/organizations/{organization_id}/shipments/{source_key}/tn-ttn-draft"
    request = body()

    first = await client.post(url, json=request)
    assert first.status_code == 200, first.text
    counterparty = await db.get(Counterparty, 1)
    counterparty.legal_name = "ООО Переименованный поставщик"
    await db.commit()
    current_revision = await db.scalar(select(Counterparty.revision).where(Counterparty.id == 1))

    replay = await client.post(url, json=request)
    assert replay.status_code == 200, replay.text
    assert replay.json()["saved_fields"]["recipient_identity"]["name"] == "supplier1"

    stale_reference = body(expected_revision=1)
    assert (await client.post(url, json=stale_reference)).status_code == 409
    current_reference = body(expected_revision=1, recipient_counterparty_revision=current_revision)
    second = await client.post(url, json=current_reference)
    assert second.status_code == 200, second.text
    assert second.json()["history"][0]["fields"]["recipient_identity"]["name"] == "supplier1"
    assert second.json()["saved_fields"]["recipient_identity"]["name"] == "ООО Переименованный поставщик"
    identity_change = next(
        item for item in second.json()["history"][1]["changes"]
        if item["field"] == "recipient_identity.name"
    )
    assert (identity_change["before"], identity_change["after"]) == (
        "supplier1", "ООО Переименованный поставщик",
    )


async def test_tn_ttn_rejects_free_text_party_names_and_inactive_recipients(client, db, book, monkeypatch):
    organization_id = book[0]
    source_key = str(uuid4())
    await connect_source(monkeypatch, organization_id, source_key)
    url = f"/accounting/organizations/{organization_id}/shipments/{source_key}/tn-ttn-draft"

    free_text = body()
    free_text["fields"]["recipient_legal_entity"] = "Not a directory record"
    assert (await client.post(url, json=free_text)).status_code == 422

    recipient = await db.get(Counterparty, 1)
    recipient.is_active = False
    await db.commit()
    inactive = await client.post(url, json=body())
    assert inactive.status_code == 409
    assert "active directory record" in inactive.text


async def test_tn_ttn_recipient_and_contract_are_bound_to_source_buyer(client, db, book, monkeypatch):
    organization_id = book[0]
    source_key = str(uuid4())
    await connect_source(monkeypatch, organization_id, source_key)
    url = f"/accounting/organizations/{organization_id}/shipments/{source_key}/tn-ttn-draft"

    wrong_recipient = body(recipient_counterparty_id=2)
    rejected_party = await client.post(url, json=wrong_recipient)
    assert rejected_party.status_code == 409
    assert "exact buyer bound to the source invoice" in rejected_party.text

    supplier_contract = body(contract_source="procurement")
    assert (await client.post(url, json=supplier_contract)).status_code == 422
    wrong_contract = body(contract_number="Договор другого покупателя")
    rejected_contract = await client.post(url, json=wrong_contract)
    assert rejected_contract.status_code == 409
    assert "Contract directory record changed" in rejected_contract.text
    assert await db.scalar(select(func.count()).select_from(ShipmentPreparationDraft)) == 0
