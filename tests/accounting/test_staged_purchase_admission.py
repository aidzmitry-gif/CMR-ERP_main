"""Synthetic source observations reach native receipts; no 1C journal is imported."""
# pytest fixtures are intentionally re-exported into this module's namespace.
# ruff: noqa: F811
import hashlib
import json
from copy import deepcopy
from datetime import datetime

import pytest
from sqlalchemy import func, select

from core.domain.document_source import DocumentSourceRevision
from core.services.native_document_stage import BOUND, REQUIRED_HOLDS, stage_documents
from modules.accounting.models import AccessGrant, Entry, Line, Organization, Period, SourceControl
from modules.procurement.receipt_documents import ReceiptDocument, ReceiptRevision
from tests.accounting.test_automatic_receipts import configure, preview
from tests.accounting.test_onec_purchase_import import (  # noqa: F401
    mapping,
    source_doc,
    source_mapping,
    source_receipt,
)

pytestmark = pytest.mark.usefixtures("receipt_catalog_sku")
ENTITY = "Document_ПриобретениеТоваровУслуг"
GUID = "00000000-0000-0000-0000-000000000001"
ORG_GUID = "00000000-0000-0000-0000-000000000002"


async def stage(db, row, *, namespace="synthetic-ka", holds=None, previous=None):
    connection = await db.connection()
    await connection.run_sync(lambda c: DocumentSourceRevision.__table__.create(c, checkfirst=True))
    await db.commit()
    raw = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    sha = hashlib.sha256(raw.encode()).hexdigest()
    envelope = dict(entity=ENTITY, source_guid=GUID, data_version=row["DataVersion"],
                    source_text=raw, source_sha256=sha, source_scope=BOUND,
                    status="HELD_SOURCE_ONLY", holds=sorted(holds or REQUIRED_HOLDS))
    await db.run_sync(lambda s: stage_documents(
        s, namespace, [envelope], actor="synthetic-observer", entity_scopes={ENTITY: BOUND},
        organization_sha256=hashlib.sha256(ORG_GUID.encode()).hexdigest(),
        period_start=datetime(2026, 9, 1), period_end=datetime(2026, 10, 1),
        expected_previous={(ENTITY, GUID): previous} if previous else None,
    ))
    await db.commit()
    return sha


@pytest.fixture
async def command(client, db, book, source_mapping, source_receipt):
    contract = await client.post(f"/procurement/organizations/{book[0]}/supplier-contracts", json={
        "supplier_id": 1, "number": "SC-1", "title": "Synthetic supply agreement",
        "signed_on": "2026-01-01", "expires_on": "2026-12-31",
        "evidence": "Synthetic signed original",
    })
    assert contract.status_code == 201, contract.text
    profile = deepcopy(source_mapping)
    profile.update(organization_id=book[0])
    profile["suppliers"]["supplier-1"] = {"id": 1, "name": "supplier1", "unp": "190000001"}
    profile["contracts"]["contract-1"] = {"id": contract.json()["id"], "number": "SC-1"}
    profile["warehouses"]["warehouse-1"] = {"id": 1, "code": "warehouse1", "title": "Synthetic warehouse"}
    profile["skus"]["sku-1"] = {"id": 1, "code": "sku1", "title": "Synthetic receipt item", "unit": "шт"}
    source_receipt.update(Ref_Key=GUID, Организация_Key=ORG_GUID)
    sha = await stage(db, source_receipt)
    return dict(namespace="synthetic-ka", entity=ENTITY, source_guid=GUID,
                expected_data_version=source_receipt["DataVersion"], expected_source_sha256=sha,
                source_organization_guid=ORG_GUID, mapping=profile)


def path(book):
    return f"/procurement/organizations/{book[0]}/receipt-documents/from-source"


async def test_staged_source_creates_one_native_receipt_and_native_journal(client, db, book, command):
    before = await db.scalar(select(DocumentSourceRevision.source_text))
    response = await client.post(path(book), json=command)
    assert response.status_code == 201, response.text
    receipt_id = response.json()["id"]
    assert response.json()["status"] == "draft"
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0
    replay = await client.post(path(book), json=command)
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == receipt_id
    db.expire_all()
    fetched = await client.get(f"/procurement/organizations/{book[0]}/receipt-documents")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()[0]["id"] == receipt_id
    assert command["expected_source_sha256"] in fetched.json()[0]["revisions"][0]["document"]["explanation"]
    await configure(client, db, book)
    posting_path = f"/accounting/organizations/{book[0]}/receipts/{receipt_id}"
    calculated = await preview(client, posting_path, on="2026-09-12")
    assert calculated.status_code == 200, calculated.text
    assert [(v["account"], v["side"], v["amount"]) for v in calculated.json()["lines"]] == [
        ("41.01", "debit", "100.00"), ("18.03", "debit", "20.00"), ("60.01", "credit", "120.00")]
    confirmation = {**calculated.json()["resolved_options"], "digest": calculated.json()["digest"]}
    posted = await client.post(posting_path + "/auto-confirm", json=confirmation)
    assert posted.status_code == 201, posted.text
    again = await client.post(posting_path + "/auto-confirm", json=confirmation)
    assert again.status_code == 201, again.text
    assert again.json()["entry_id"] == posted.json()["entry_id"]
    assert await db.scalar(select(func.count()).select_from(ReceiptDocument)) == 1
    assert await db.scalar(select(func.count()).select_from(Entry)) == 1
    assert await db.scalar(select(func.count()).select_from(Line)) == 3
    assert await db.scalar(select(DocumentSourceRevision.source_text)) == before
    assert set(await db.scalar(select(DocumentSourceRevision.holds))) == REQUIRED_HOLDS


@pytest.mark.parametrize("change,status", [
    ("version", 409), ("sha", 409), ("namespace", 404), ("org", 422),
    ("target-org", 422), ("legacy-profile", 422), ("entity", 422),
    ("supplier", 422), ("sku", 422), ("unit", 409), ("warehouse", 409),
])
async def test_invalid_binding_does_not_create_native_document(client, db, book, command, change, status):
    if change == "version":
        command["expected_data_version"] = "other-version"
    elif change == "sha":
        command["expected_source_sha256"] = "f" * 64
    elif change == "namespace":
        command["namespace"] = "unseen-namespace"
    elif change == "org":
        command["source_organization_guid"] = GUID
    elif change == "target-org":
        command["mapping"]["organization_id"] += 1
    elif change == "legacy-profile":
        command["mapping"]["schema_version"] = "onec-purchase-map-v1"
    elif change == "entity":
        command["entity"] = "Document_ПриобретениеУслугПрочихАктивов"
    elif change == "supplier":
        command["mapping"]["suppliers"].clear()
    elif change == "sku":
        command["mapping"]["skus"].clear()
    elif change == "unit":
        command["mapping"]["skus"]["sku-1"]["unit"] = "кг"
    else:
        command["mapping"]["warehouses"]["warehouse-1"]["code"] = "other"
    response = await client.post(path(book), json=command)
    assert response.status_code == status, response.text
    assert await db.scalar(select(func.count()).select_from(ReceiptDocument)) == 0
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0


@pytest.mark.parametrize("change", ["extra-hold", "unposted", "deleted", "services", "operation-date"])
async def test_source_eligibility_holds_are_not_discarded(client, db, book, command, source_receipt, change):
    source_receipt.update(Ref_Key=GUID, Организация_Key=ORG_GUID, DataVersion="synthetic-version-2")
    holds = set(REQUIRED_HOLDS)
    if change == "extra-hold":
        holds.add("UNRESOLVED_SOURCE_FIELD")
    elif change == "unposted":
        source_receipt["Posted"] = False
    elif change == "deleted":
        source_receipt["DeletionMark"] = True
    elif change == "services":
        source_receipt["Услуги"] = [{"Сумма": "10"}]
    else:
        source_receipt["OperationDate"] = "2026-08-31T00:00:00"
    command["expected_source_sha256"] = await stage(
        db, source_receipt, holds=holds, previous=command["expected_source_sha256"])
    command["expected_data_version"] = source_receipt["DataVersion"]
    rejected = await client.post(path(book), json=command)
    assert rejected.status_code == 422, rejected.text
    assert await db.scalar(select(func.count()).select_from(ReceiptDocument)) == 0


async def test_changed_source_or_mapping_requires_correction_not_duplicate(client, db, book, command, source_receipt):
    first = await client.post(path(book), json=command)
    assert first.status_code == 201, first.text
    changed_mapping = deepcopy(command)
    changed_mapping["mapping"]["source_rules"]["vat_rates"]["Unused"] = "0"
    assert (await client.post(path(book), json=changed_mapping)).status_code == 409
    source_receipt.update(Ref_Key=GUID, Организация_Key=ORG_GUID, DataVersion="synthetic-version-2")
    new_sha = await stage(db, source_receipt, previous=command["expected_source_sha256"])
    assert (await client.post(path(book), json=command)).status_code == 409
    updated = {**command, "expected_source_sha256": new_sha, "expected_data_version": "synthetic-version-2"}
    assert (await client.post(path(book), json=updated)).status_code == 409
    assert await db.scalar(select(func.count()).select_from(ReceiptDocument)) == 1
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0


async def test_only_chief_may_bind_and_source_cannot_be_reused_in_other_book(client, db, book, command):
    grant = await db.scalar(select(AccessGrant).where(AccessGrant.organization_id == book[0]))
    grant.role = "accountant"
    await db.commit()
    assert (await client.post(path(book), json=command)).status_code == 403
    grant.role = "chief"
    await db.commit()
    assert (await client.post(path(book), json=command)).status_code == 201
    org = Organization(name="Synthetic other company", unp="999999998")
    db.add(org)
    await db.flush()
    other_id = org.id
    db.add(AccessGrant(organization_id=other_id, subject="tester", role="chief"))
    await db.commit()
    command["mapping"]["organization_id"] = other_id
    assert (await client.post(path((other_id, 0)), json=command)).status_code == 409
    assert await db.scalar(select(func.count()).select_from(ReceiptDocument)) == 1


async def test_reserved_keys_and_edits_cannot_bypass_source_provenance(client, book, command):
    created = await client.post(path(book), json=command)
    assert created.status_code == 201, created.text
    doc = created.json()["revisions"][0]["document"]
    root = f"/procurement/organizations/{book[0]}/receipt-documents"
    key = created.json()["key"]
    assert (await client.post(root, json={"key": key, "document": doc})).status_code == 422
    receipt_id = created.json()["id"]
    correction = {"key": key, "expected_version": 1, "expected_entry_id": 1}
    assert (await client.post(f"{root}/{receipt_id}/correction-drafts", json=correction)).status_code == 422
    legacy = "onec:purchase:" + key.split(":")[-2]
    assert (await client.post(root, json={"key": legacy, "document": doc})).status_code == 409
    assert (await client.post(f"{root}/{receipt_id}/correction-drafts",
                             json={**correction, "key": legacy})).status_code == 409
    edit = {"key": "synthetic-edit", "expected_version": 1, "document": doc}
    assert (await client.put(f"{root}/{receipt_id}", json=edit)).status_code == 409


async def test_existing_legacy_receipt_is_held_without_adoption(client, db, book, command):
    from modules.accounting.onec_purchase_import import build_receipt_drafts

    raw = await db.scalar(select(DocumentSourceRevision.source_text))
    draft = build_receipt_drafts([json.loads(raw)], {
        "entity": ENTITY, "date_from": "2026-09-01", "date_to": "2026-10-01"}, command["mapping"])[0]
    legacy = await client.post(f"/procurement/organizations/{book[0]}/receipt-documents",
                              json={"key": draft["key"], "document": draft["document"]})
    assert legacy.status_code == 201, legacy.text
    assert (await client.post(path(book), json=command)).status_code == 409
    assert await db.scalar(select(func.count()).select_from(ReceiptDocument)) == 1


async def test_native_failure_after_flush_rolls_back_admission(client, db, book, command):
    db.add(Period(organization_id=book[0], month="2026-09", closed=True))
    await db.commit()
    response = await client.post(path(book), json=command)
    assert response.status_code == 409, response.text
    assert "closed period" in response.json()["detail"]
    for model in (ReceiptDocument, ReceiptRevision, SourceControl, Entry):
        assert await db.scalar(select(func.count()).select_from(model)) == 0
    assert await db.scalar(select(func.count()).select_from(DocumentSourceRevision)) == 1


async def test_namespace_keys_and_lots_keep_distinct_source_identity(client, db, book, command, source_receipt):
    first = await client.post(path(book), json=command)
    assert first.status_code == 201, first.text
    source_receipt.update(Ref_Key=GUID, Организация_Key=ORG_GUID)
    sha = await stage(db, source_receipt, namespace="synthetic-other-ka")
    other = {**command, "namespace": "synthetic-other-ka", "expected_source_sha256": sha}
    second = await client.post(path(book), json=other)
    assert second.status_code == 201, second.text
    assert first.json()["key"] != second.json()["key"]
    assert first.json()["revisions"][0]["document"]["items"][0]["lot"] != second.json()["revisions"][0]["document"]["items"][0]["lot"]
