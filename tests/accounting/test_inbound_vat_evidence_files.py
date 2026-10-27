"""Private, revision-scoped evidence files for VAT-only receipt corrections."""
import base64
import copy
import hashlib
import os
from datetime import date
from uuid import uuid4

from modules.accounting.models import Entry, Organization, Period
from modules.procurement.receipt_documents import ReceiptDocument, ReceiptPosting, ReceiptRevision
from tests.accounting.test_procurement_receipt_drafts import document
from tests.conftest import make_private_test_dir

XML = b"<?xml version='1.0' encoding='UTF-8'?><Eschf><Invoice>synthetic</Invoice></Eschf>"
PDF = b"%PDF-1.7\nsynthetic supporting evidence\n"


def payload(receipt_id: int, *, data=XML, kind="supplier_eschf_xml", request_key=None, **changes):
    mime = "application/pdf" if kind == "supporting_document_pdf" else "application/xml"
    suffix = "pdf" if kind == "supporting_document_pdf" else "xml"
    result = {
        "request_key": request_key or str(uuid4()),
        "receipt_id": receipt_id,
        "receipt_version": 1,
        "kind": kind,
        "tax_period": "2026-09",
        "reference": "synthetic supplier evidence",
        "filename": f"supplier-source.{suffix}",
        "data_url": f"data:{mime};base64," + base64.b64encode(data).decode(),
        "evidence": "Synthetic file supplied for accountant review",
    }
    result.update(changes)
    return result


async def seed_vat_correction(db, book, *, correction_changes=None):
    original_document = document()
    corrected_document = copy.deepcopy(original_document)
    corrected_document["items"][0].update(vat_rate="10", vat_amount="10.00")
    if correction_changes:
        corrected_document.update(correction_changes)

    original = ReceiptDocument(
        organization_id=book[0], source_key="synthetic-inbound-vat-original-" + uuid4().hex,
        current_version=1, status="draft", created_by="tester",
    )
    db.add(original)
    await db.flush()
    original_revision = ReceiptRevision(
        receipt_id=original.id, version=1, request_key=None,
        document=original_document, actor="tester",
    )
    db.add(original_revision)
    entry = Entry(
        organization_id=book[0], source=f"procurement:receipt:{original.id}",
        source_version=1, operation="inventory_purchase", document_date=date(2026, 9, 1),
        operation_date=date(2026, 9, 2), posting_date=date(2026, 9, 2), policy_id=book[1],
        rule_version="receipt-v1", explanation="Synthetic posted receipt source",
        opening=False, correction_of=None, digest="a" * 64, actor="tester",
    )
    db.add(entry)
    await db.flush()
    db.add(ReceiptPosting(
        receipt_id=original.id, version=1, entry_id=entry.id, options={},
        digest="b" * 64, actor="tester",
    ))
    correction = ReceiptDocument(
        organization_id=book[0], source_key="synthetic-inbound-vat-correction-" + uuid4().hex,
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
    await db.commit()
    return correction.id


async def test_inbound_vat_file_replay_current_download_and_byte_integrity(
        client, db, book, tmp_path, monkeypatch):
    receipt_id = await seed_vat_correction(db, book)
    root = tmp_path / "accounting-evidence"
    make_private_test_dir(root)
    monkeypatch.setenv("AIOS_ACCOUNTING_EVIDENCE_DATA_DIR", str(root.resolve()))
    url = f"/accounting/organizations/{book[0]}/receipt-correction-evidence-files"

    command = payload(receipt_id)
    created = await client.post(url, json=command)
    assert created.status_code == 200, created.text
    first = created.json()
    assert first["sha256"] == hashlib.sha256(XML).hexdigest()
    assert first["size_bytes"] == len(XML)
    assert first["bytes_verified_at_upload"] is True
    assert first["signature_verified"] is False
    assert first["document_facts_verified"] is False
    assert first["posting_available"] is False
    assert "storage_filename" not in first and "data_url" not in str(first)
    assert created.headers["cache-control"] == "private, no-store"
    assert (await client.post(url, json=command)).json() == first
    changed = await client.post(url, json={**command, "reference": "different source"})
    assert changed.status_code == 409

    params = {"receipt_id": receipt_id, "receipt_version": 1, "kind": "supplier_eschf_xml"}
    listed = await client.get(url, params=params)
    assert listed.status_code == 200 and listed.headers["cache-control"] == "private, no-store"
    assert [item["file_id"] for item in listed.json()] == [first["file_id"]]
    current = await client.get(url + "/current", params=params)
    assert [item["file_id"] for item in current.json()] == [first["file_id"]]
    download_url = f"{url}/{first['file_id']}/download"
    downloaded = await client.get(download_url, params=params)
    assert downloaded.status_code == 200 and downloaded.content == XML
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert downloaded.headers["cache-control"] == "private, no-store"

    pdf_command = payload(receipt_id, data=PDF, kind="supporting_document_pdf")
    pdf = await client.post(url, json=pdf_command)
    assert pdf.status_code == 200, pdf.text
    parallel = await client.post(url, json=payload(receipt_id, request_key=str(uuid4())))
    assert parallel.status_code == 409 and "parallel chain" in parallel.text
    second = await client.post(url, json=payload(
        receipt_id, request_key=str(uuid4()), supersedes_id=first["file_id"],
    ))
    assert second.status_code == 200, second.text
    replacement = payload(receipt_id, request_key=str(uuid4()), supersedes_id=second.json()["file_id"])
    third = await client.post(url, json=replacement)
    assert third.status_code == 200, third.text
    chain_params = {**params, "kind": "supplier_eschf_xml"}
    chain = await client.get(url, params=chain_params)
    assert [item["is_current"] for item in chain.json()] == [False, False, True]
    current_chain = await client.get(url + "/current", params=chain_params)
    assert [item["file_id"] for item in current_chain.json()] == [third.json()["file_id"]]
    replayed_first = await client.post(url, json=command)
    assert replayed_first.status_code == 200
    assert replayed_first.json()["is_current"] is False
    stale = payload(receipt_id, request_key=str(uuid4()), supersedes_id=first["file_id"])
    assert (await client.post(url, json=stale)).status_code == 409

    stored = root / str(book[0]) / (command["request_key"].replace("-", "") + ".xml")
    stored.write_bytes(b"<?xml?><tampered/>")
    assert (await client.get(download_url, params=params)).status_code == 409
    assert (await client.post(url, json=command)).status_code == 409


async def test_inbound_vat_file_requires_private_root_scope_and_vat_only_open_source(
        client, db, book, tmp_path, monkeypatch):
    receipt_id = await seed_vat_correction(db, book)
    url = f"/accounting/organizations/{book[0]}/receipt-correction-evidence-files"
    command = payload(receipt_id)

    monkeypatch.delenv("AIOS_ACCOUNTING_EVIDENCE_DATA_DIR", raising=False)
    assert (await client.post(url, json=command)).status_code == 503

    root = tmp_path / "private"
    make_private_test_dir(root)
    monkeypatch.setenv("AIOS_ACCOUNTING_EVIDENCE_DATA_DIR", str(root.resolve()))
    if os.name != "nt":
        root.chmod(0o755)
        try:
            broad = await client.post(url, json=command)
            assert broad.status_code == 503 and "permissions are too broad" in broad.text
        finally:
            root.chmod(0o700)
    invalid_xml = await client.post(url, json=payload(receipt_id, data=b"not XML"))
    assert invalid_xml.status_code == 422
    utf16_dtd = """<?xml version="1.0" encoding="UTF-16"?>
<!DOCTYPE Eschf [<!ENTITY value "synthetic">]>
<Eschf>&value;</Eschf>""".encode("utf-16")
    rejected_dtd = await client.post(url, json=payload(receipt_id, data=utf16_dtd))
    assert rejected_dtd.status_code == 422
    invalid_mime = await client.post(url, json=payload(receipt_id, data=PDF))
    assert invalid_mime.status_code == 422

    closed_period = Period(
        organization_id=book[0], month="2026-09", closed=True, generation=0, evidence={},
    )
    db.add(closed_period)
    await db.commit()
    closed = await client.post(url, json=payload(receipt_id, request_key=str(uuid4())))
    assert closed.status_code == 409 and "before adding evidence" in closed.text
    await db.delete(closed_period)
    await db.commit()

    accepted = await client.post(url, json=payload(receipt_id))
    assert accepted.status_code == 200, accepted.text

    stale_revision = await client.post(url, json=payload(
        receipt_id, request_key=str(uuid4()), receipt_version=2,
    ))
    assert stale_revision.status_code == 409

    physical_receipt_id = await seed_vat_correction(
        db, book, correction_changes={"warehouse": "another warehouse"},
    )
    physical = await client.post(url, json=payload(physical_receipt_id, request_key=str(uuid4())))
    assert physical.status_code == 409

    other = Organization(name="Other inbound VAT company", unp="123456789")
    db.add(other)
    await db.flush()
    from modules.accounting.models import AccessGrant

    db.add(AccessGrant(organization_id=other.id, subject="tester", role="accountant"))
    other_id = other.id
    await db.commit()
    params = {"receipt_id": receipt_id, "receipt_version": 1, "kind": "supplier_eschf_xml"}
    crossed = await client.get(
        f"/accounting/organizations/{other_id}/receipt-correction-evidence-files/{accepted.json()['file_id']}/download",
        params=params,
    )
    assert crossed.status_code == 404
