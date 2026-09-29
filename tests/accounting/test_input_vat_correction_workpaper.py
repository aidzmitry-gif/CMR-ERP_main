"""Review-only source binding for VAT-only receipt correction drafts."""
import hashlib
import json
from copy import deepcopy
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from modules.accounting.models import (
    Account,
    Entry,
    InboundVatCorrectionWorkpaper,
    InputVatRegisterEntry,
    Line,
    Period,
)
from modules.procurement.receipt_documents import ReceiptDocument, ReceiptPosting, ReceiptRevision
from tests.accounting.test_inbound_vat_evidence_files import PDF, XML, payload, seed_vat_correction
from tests.accounting.test_procurement_receipt_drafts import document


def workpaper_command(receipt_id: int, *, key=None, **overrides):
    return {
        "receipt_id": receipt_id,
        "receipt_version": 1,
        "tax_period": "2026-09",
        "request_key": str(key or uuid4()),
        "basis_digest": "0" * 64,
        "reviewer_evidence": "Synthetic accountant review of linked source revisions and evidence",
        "supersedes_workpaper_id": None,
        **overrides,
    }


async def seed_workpaper_source(db, book, *, correction_changes=None):
    correction_id = await seed_vat_correction(db, book, correction_changes=correction_changes)
    correction = await db.get(ReceiptDocument, correction_id)
    entry = await db.scalar(select(Entry).where(
        Entry.source == f"procurement:receipt:{correction.correction_of_receipt_id}",
    ))
    account = await db.scalar(select(Account).where(
        Account.organization_id == book[0], Account.code == "18",
    ))
    if account is None:
        account = Account(
            organization_id=book[0], code="18", title="Input VAT", category="asset",
            valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
            quantity_tracking=False, cash=False, normative_ref="synthetic",
        )
        db.add(account)
        await db.flush()
    goods = await db.scalar(select(Account).where(
        Account.organization_id == book[0], Account.code == "41",
    ))
    settlement = await db.scalar(select(Account).where(
        Account.organization_id == book[0], Account.code == "60",
    ))
    db.add_all([
        Line(entry_id=entry.id, account_id=goods.id, account_code="41", account_title=goods.title,
             category="asset", cash=False, side="debit", amount="100.00", dimensions={}, currency="BYN"),
        Line(entry_id=entry.id, account_id=account.id, account_code="18", account_title=account.title,
             category="asset", cash=False, side="debit", amount="20.00", dimensions={"supplier": "supplier1"},
             currency="BYN"),
        Line(entry_id=entry.id, account_id=settlement.id, account_code="60", account_title=settlement.title,
             category="liability", cash=False, side="credit", amount="120.00", dimensions={}, currency="BYN"),
    ])
    await db.commit()
    return correction_id, entry.id


async def seed_zero_vat_workpaper_source(db, book):
    original_document = document()
    original_document["items"][0].update(vat_rate="0", vat_amount="0.00")
    corrected_document = deepcopy(original_document)
    corrected_document["items"][0].update(vat_rate="10", vat_amount="10.00")
    original = ReceiptDocument(
        organization_id=book[0], source_key="synthetic-inbound-vat-zero-original-" + uuid4().hex,
        current_version=1, status="draft", created_by="tester",
    )
    db.add(original)
    await db.flush()
    original_revision = ReceiptRevision(
        receipt_id=original.id, version=1, request_key=None, document=original_document, actor="tester",
    )
    db.add(original_revision)
    entry = Entry(
        organization_id=book[0], source=f"procurement:receipt:{original.id}",
        source_version=1, operation="inventory_purchase", document_date=date(2026, 9, 1),
        operation_date=date(2026, 9, 2), posting_date=date(2026, 9, 2), policy_id=book[1],
        rule_version="receipt-v1", explanation="Synthetic posted zero-VAT receipt source",
        opening=False, correction_of=None, digest="d" * 64, actor="tester",
    )
    db.add(entry)
    await db.flush()
    db.add(ReceiptPosting(
        receipt_id=original.id, version=1, entry_id=entry.id, options={}, digest="e" * 64, actor="tester",
    ))
    correction = ReceiptDocument(
        organization_id=book[0], source_key="synthetic-inbound-vat-zero-correction-" + uuid4().hex,
        current_version=1, status="draft", created_by="tester",
        correction_of_receipt_id=original.id, correction_of_version=1,
        correction_of_entry_id=entry.id,
    )
    db.add(correction)
    await db.flush()
    db.add(ReceiptRevision(
        receipt_id=correction.id, version=1, request_key=None,
        document=corrected_document, actor="tester",
    ))
    goods = await db.scalar(select(Account).where(Account.organization_id == book[0], Account.code == "41"))
    settlement = await db.scalar(select(Account).where(Account.organization_id == book[0], Account.code == "60"))
    db.add_all([
        Line(entry_id=entry.id, account_id=goods.id, account_code="41", account_title=goods.title,
             category="asset", cash=False, side="debit", amount="100.01", dimensions={}, currency="BYN"),
        Line(entry_id=entry.id, account_id=settlement.id, account_code="60", account_title=settlement.title,
             category="liability", cash=False, side="credit", amount="100.01", dimensions={}, currency="BYN"),
    ])
    await db.commit()
    return correction.id, entry.id


async def upload_file(client, org_id, receipt_id, *, kind="supplier_eschf_xml", data=XML,
                      supersedes_id=None):
    command = payload(receipt_id, data=data, kind=kind, request_key=str(uuid4()),
                      supersedes_id=supersedes_id)
    response = await client.post(
        f"/accounting/organizations/{org_id}/receipt-correction-evidence-files", json=command,
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_vat_correction_workpaper_preview_replay_history_and_read_only(
        client, db, book, tmp_path, monkeypatch):
    receipt_id, entry_id = await seed_workpaper_source(db, book)
    storage = tmp_path / "private-accounting-evidence"
    storage.mkdir()
    monkeypatch.setenv("AIOS_ACCOUNTING_EVIDENCE_DATA_DIR", str(storage.resolve()))
    first_file = await upload_file(client, book[0], receipt_id)
    pdf_file = await upload_file(
        client, book[0], receipt_id, kind="supporting_document_pdf", data=PDF,
    )

    preview_response = await client.post(
        f"/accounting/organizations/{book[0]}/inbound-vat-correction-workpapers/preview",
        json={"receipt_id": receipt_id, "receipt_version": 1, "tax_period": "2026-09"},
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["basis"]["receipt"]["source_entry_id"] == entry_id
    assert preview["basis"]["receipt"]["source_entry_digest"] == "a" * 64
    assert preview["source_account_18_line_count"] == 1
    assert preview["input_vat_register_links"] == {
        "status": "none", "organization_id": book[0],
        "source_entry_id": entry_id, "source_entry_digest": "a" * 64,
        "source_line_count": 1, "registered_line_count": 0, "items": [],
        "statutory_certified": False, "deduction_assessed": False, "posting_available": False,
    }
    line, = preview["basis"]["source_account_18_lines"]
    assert line["account_code"] == "18" and line["amount"] == "20.00"
    assert not any(key in line for key in ("side", "debit", "credit", "delta", "vat_delta"))
    assert {item["file_id"] for item in preview["basis"]["evidence_files"]} == {
        first_file["file_id"], pdf_file["file_id"],
    }
    assert all(item["sha256"] and item["digest"] and item["size_bytes"] > 0
               for item in preview["basis"]["evidence_files"])
    for key, expected in {
        "review_only": True,
        "signature_verified": False,
        "document_facts_verified": False,
        "deduction_eligibility_assessed": False,
        "accountant_accepted": False,
        "posting_available": False,
    }.items():
        assert preview[key] is expected and preview["basis"][key] is expected
    assert preview["evidence_bytes_verified_at_review"] is True
    assert "vat_delta" not in json.dumps(preview)

    ledger_count = await db.scalar(select(func.count()).select_from(Line))
    command = workpaper_command(receipt_id, basis_digest=preview["basis_digest"])
    url = f"/accounting/organizations/{book[0]}/inbound-vat-correction-workpapers"
    created = await client.post(url, json=command)
    assert created.status_code == 201, created.text
    first = created.json()
    assert first["revision"] == 1 and first["supersedes_workpaper_id"] is None
    assert (await client.post(url, json=command)).json() == first
    changed_replay = await client.post(url, json={**command, "reviewer_evidence": "Different review evidence"})
    assert changed_replay.status_code == 409
    assert await db.scalar(select(func.count()).select_from(Line)) == ledger_count
    assert await db.scalar(select(func.count()).select_from(InboundVatCorrectionWorkpaper)) == 1

    replacement = await upload_file(
        client, book[0], receipt_id, supersedes_id=first_file["file_id"],
    )
    revised_preview_response = await client.post(
        f"/accounting/organizations/{book[0]}/inbound-vat-correction-workpapers/preview",
        json={"receipt_id": receipt_id, "receipt_version": 1, "tax_period": "2026-09"},
    )
    revised_preview = revised_preview_response.json()
    second_command = workpaper_command(
        receipt_id, basis_digest=revised_preview["basis_digest"],
        supersedes_workpaper_id=first["workpaper_id"],
    )
    second_response = await client.post(url, json=second_command)
    assert second_response.status_code == 201, second_response.text
    second = second_response.json()
    assert second["revision"] == 2 and second["supersedes_workpaper_id"] == first["workpaper_id"]
    current_evidence = next(
        item for item in second["snapshot"]["evidence_files"] if item["kind"] == "supplier_eschf_xml"
    )
    assert current_evidence["file_id"] == replacement["file_id"]

    history = await client.get(url, params={
        "receipt_id": receipt_id, "receipt_version": 1, "tax_period": "2026-09",
    })
    assert history.status_code == 200 and [row["revision"] for row in history.json()] == [1, 2]
    by_request = await client.get(url + f"/by-request/{second['request_key']}")
    assert by_request.status_code == 200 and by_request.json() == second

    # Historical exact retries still verify their original bytes after a file is superseded.
    replay_first = await client.post(url, json=command)
    assert replay_first.status_code == 201 and replay_first.json() == first
    stored = storage / str(book[0]) / (replacement["request_key"].replace("-", "") + ".xml")
    assert hashlib.sha256(stored.read_bytes()).hexdigest() == replacement["sha256"]

    source_line = await db.scalar(select(Line).where(
        Line.entry_id == entry_id, Line.account_code == "18",
    ))
    register_url = f"/accounting/organizations/{book[0]}/input-vat-register"
    register_command = {
        "request_key": str(uuid4()), "entry_id": entry_id, "line_id": source_line.id,
        "expected_entry_digest": "a" * 64, "tax_period": "2026-09",
        "invoice_reference": "INV-18", "eschf_identifier": "ЭСЧФ-18",
        "deduction_status": "pending", "eschf_status": "provided",
        "right_basis": "Синтетическая запись регистра для проверки навигационной связи",
        "evidence": "Тестовые сведения не подтверждают применимое право на вычет",
    }
    register_preview = await client.post(register_url + "/preview", json=register_command)
    assert register_preview.status_code == 200, register_preview.text
    register_confirm = await client.post(
        register_url + "/confirm", headers={"X-Expected-Principal": "tester"},
        json={**register_command, "digest": register_preview.json()["digest"]},
    )
    assert register_confirm.status_code == 201, register_confirm.text
    register_entry = register_confirm.json()
    assert register_entry["posted"] is False

    linked = await client.get(url + f"/by-request/{second['request_key']}")
    assert linked.status_code == 200, linked.text
    linked_result = linked.json()
    assert linked_result["input_vat_register_links"] == {
        "status": "complete", "organization_id": book[0],
        "source_entry_id": entry_id, "source_entry_digest": "a" * 64,
        "source_line_count": 1, "registered_line_count": 1,
        "items": [{
            "register_entry_id": register_entry["id"], "source_line_id": source_line.id,
            "register_digest": register_entry["digest"], "tax_period": "2026-09",
            "invoice_reference": "INV-18", "eschf_identifier": "ЭСЧФ-18", "eschf_status": "provided",
        }],
        "statutory_certified": False, "deduction_assessed": False, "posting_available": False,
    }
    assert linked_result["basis_digest"] == second["basis_digest"]
    assert linked_result["snapshot_digest"] == second["snapshot_digest"]
    assert not any(key in json.dumps(linked_result["input_vat_register_links"])
                   for key in ("amount", "side", "delta", "vat_delta", "deduction_status"))
    current_history = await client.get(url, params={
        "receipt_id": receipt_id, "receipt_version": 1, "tax_period": "2026-09",
    })
    assert current_history.status_code == 200, current_history.text
    assert all(row["input_vat_register_links"] == linked_result["input_vat_register_links"]
               for row in current_history.json())
    assert await db.scalar(select(func.count()).select_from(Line)) == ledger_count

    await db.execute(update(InputVatRegisterEntry).where(
        InputVatRegisterEntry.id == register_entry["id"],
    ).values(entry_digest="f" * 64))
    await db.commit()
    db.expire_all()
    stale_link = await client.get(url + f"/by-request/{second['request_key']}")
    assert stale_link.status_code == 409 and "register source binding" in stale_link.text
    await db.execute(update(InputVatRegisterEntry).where(
        InputVatRegisterEntry.id == register_entry["id"],
    ).values(entry_digest="a" * 64))
    await db.commit()
    db.expire_all()
    restored_link = await client.get(url + f"/by-request/{second['request_key']}")
    assert restored_link.status_code == 200 and restored_link.json()["input_vat_register_links"] == \
        linked_result["input_vat_register_links"]

    original_revision = await db.get(ReceiptRevision, second["snapshot"]["receipt"]["original_revision_id"])
    changed_document = deepcopy(original_revision.document)
    changed_document["supplier"] = "Tampered immutable source revision"
    await db.execute(update(ReceiptRevision).where(
        ReceiptRevision.id == original_revision.id,
    ).values(document=changed_document))
    await db.commit()
    db.expire_all()
    broken_by_request = await client.get(url + f"/by-request/{second['request_key']}")
    assert broken_by_request.status_code == 409 and "revision documents" in broken_by_request.text
    broken_history = await client.get(url, params={
        "receipt_id": receipt_id, "receipt_version": 1, "tax_period": "2026-09",
    })
    assert broken_history.status_code == 409 and "revision documents" in broken_history.text
    broken_replay = await client.post(url, json=command)
    assert broken_replay.status_code == 409 and "revision documents" in broken_replay.text


@pytest.mark.asyncio
async def test_vat_correction_workpaper_closed_period_changed_basis_and_bad_scope(
        client, db, book, tmp_path, monkeypatch):
    receipt_id, _ = await seed_workpaper_source(db, book)
    storage = tmp_path / "private-accounting-evidence"
    storage.mkdir()
    monkeypatch.setenv("AIOS_ACCOUNTING_EVIDENCE_DATA_DIR", str(storage.resolve()))
    await upload_file(client, book[0], receipt_id)
    base = f"/accounting/organizations/{book[0]}/inbound-vat-correction-workpapers"
    preview = await client.post(base + "/preview", json={
        "receipt_id": receipt_id, "receipt_version": 1, "tax_period": "2026-09",
    })
    assert preview.status_code == 200, preview.text
    bad_basis = await client.post(base, json=workpaper_command(
        receipt_id, basis_digest="f" * 64,
    ))
    assert bad_basis.status_code == 409

    created = await client.post(base, json=workpaper_command(
        receipt_id, basis_digest=preview.json()["basis_digest"],
    ))
    assert created.status_code == 201, created.text
    closed = Period(organization_id=book[0], month="2026-09", closed=True, generation=0, evidence={})
    db.add(closed)
    await db.commit()
    # Exact replay is stable; a new revision cannot be added to a closed tax period.
    replay = await client.post(base, json=workpaper_command(
        receipt_id, key=created.json()["request_key"],
        basis_digest=preview.json()["basis_digest"],
    ))
    assert replay.status_code == 201 and replay.json() == created.json()
    blocked = await client.post(base, json=workpaper_command(
        receipt_id, basis_digest=preview.json()["basis_digest"],
        supersedes_workpaper_id=created.json()["workpaper_id"],
    ))
    assert blocked.status_code == 409 and "before creating a workpaper" in blocked.text

    foreign = await client.get(
        f"/accounting/organizations/{book[0] + 99}/inbound-vat-correction-workpapers/by-request/"
        f"{created.json()['request_key']}"
    )
    assert foreign.status_code in {403, 404}


@pytest.mark.asyncio
async def test_vat_correction_workpaper_requires_vat_only_current_revision_and_verified_bytes(
        client, db, book, tmp_path, monkeypatch):
    receipt_id, _ = await seed_workpaper_source(
        db, book, correction_changes={"warehouse": "other warehouse"},
    )
    storage = tmp_path / "private-accounting-evidence"
    storage.mkdir()
    monkeypatch.setenv("AIOS_ACCOUNTING_EVIDENCE_DATA_DIR", str(storage.resolve()))
    url = f"/accounting/organizations/{book[0]}/inbound-vat-correction-workpapers/preview"
    physical = await client.post(url, json={
        "receipt_id": receipt_id, "receipt_version": 1, "tax_period": "2026-09",
    })
    assert physical.status_code == 409 and "VAT-only" in physical.text

    valid_id, _ = await seed_workpaper_source(db, book)
    file = await upload_file(client, book[0], valid_id)
    path = storage / str(book[0]) / (file["request_key"].replace("-", "") + ".xml")
    path.write_bytes(b"tampered")
    invalid_bytes = await client.post(url, json={
        "receipt_id": valid_id, "receipt_version": 1, "tax_period": "2026-09",
    })
    assert invalid_bytes.status_code == 409


@pytest.mark.asyncio
async def test_vat_correction_workpaper_requires_account_18_source_line_and_current_evidence(
        client, db, book, tmp_path, monkeypatch):
    missing_evidence_id, _ = await seed_workpaper_source(db, book)
    base = f"/accounting/organizations/{book[0]}/inbound-vat-correction-workpapers/preview"
    no_evidence = await client.post(base, json={
        "receipt_id": missing_evidence_id, "receipt_version": 1, "tax_period": "2026-09",
    })
    assert no_evidence.status_code == 409 and "current correction evidence" in no_evidence.text

    storage = tmp_path / "private-accounting-evidence"
    storage.mkdir()
    monkeypatch.setenv("AIOS_ACCOUNTING_EVIDENCE_DATA_DIR", str(storage.resolve()))
    zero_vat_id, _ = await seed_zero_vat_workpaper_source(db, book)
    await upload_file(client, book[0], zero_vat_id)
    zero_vat = await client.post(base, json={
        "receipt_id": zero_vat_id, "receipt_version": 1, "tax_period": "2026-09",
    })
    assert zero_vat.status_code == 409 and "account-18 source line" in zero_vat.text
