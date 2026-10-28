"""PostgreSQL constraints for review-only inbound VAT correction workpapers."""
# ruff: noqa: F811 -- pytest fixtures are imported for registration.
import asyncio
import base64
import hashlib
import json
from copy import deepcopy
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from modules.accounting.models import (
    Account,
    Entry,
    InboundVatCorrectionWorkpaper,
    Line,
    Organization,
    Period,
)
from modules.procurement.receipt_documents import ReceiptDocument, ReceiptRevision
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_procurement_receipt_drafts import document, source_options
from tests.conftest import make_private_test_dir
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401

pytestmark = pytest.mark.integration


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()


async def seed_additional_correction(api, pg_book, *, tag: str, source_vat: str,
                                     corrected_vat: str, attach_evidence: bool):
    from datetime import date

    source_document = document()
    source_document["items"][0].update(
        vat_rate=source_vat, vat_amount=f"{int(source_vat):.2f}",
    )
    receipt_path = f"/procurement/organizations/{pg_book[0]}/receipt-documents"
    created = await api.post(receipt_path, json={
        "key": f"{tag}-{uuid4()}", "document": source_document,
    })
    assert created.status_code == 201, created.text
    options = {
        "expected_version": 1,
        "posting_date": date(2026, 9, 3).isoformat(),
        "policy_id": pg_book[1],
        "settlement_account": "60",
        "vat_account": "18" if int(source_vat) else None,
        "inventory_accounts": ["41.2"],
    }
    posting_preview = await api.post(f"{receipt_path}/{created.json()['id']}/preview", json=options)
    assert posting_preview.status_code == 200, posting_preview.text
    posted = await api.post(f"{receipt_path}/{created.json()['id']}/confirm", json={
        **options, "digest": posting_preview.json()["digest"],
    })
    assert posted.status_code == 201, posted.text
    correction_response = await api.post(f"{receipt_path}/{created.json()['id']}/correction-drafts", json={
        "key": f"{tag}-correction-{uuid4()}",
        "expected_version": 1,
        "expected_entry_id": posted.json()["entry_id"],
    })
    assert correction_response.status_code == 201, correction_response.text
    correction = correction_response.json()
    revised_document = deepcopy(correction["revisions"][0]["document"])
    revised_document["items"][0].update(
        vat_rate=corrected_vat, vat_amount=f"{int(corrected_vat):.2f}",
    )
    changed = await api.put(
        f"/procurement/organizations/{pg_book[0]}/receipt-documents/{correction['id']}",
        json={"key": f"{tag}-correction-edit-{uuid4()}", "expected_version": 1,
              "document": revised_document},
    )
    assert changed.status_code == 200 and changed.json()["version"] == 2, changed.text
    evidence_result = None
    if attach_evidence:
        raw_xml = b"<?xml version='1.0'?><Eschf><Invoice>synthetic-extra</Invoice></Eschf>"
        evidence = {
            "request_key": str(uuid4()), "receipt_id": correction["id"], "receipt_version": 2,
            "kind": "supplier_eschf_xml", "tax_period": "2026-09",
            "reference": "Synthetic supplier e-ЭСЧФ", "filename": "extra-source.xml",
            "data_url": "data:application/xml;base64," + base64.b64encode(raw_xml).decode(),
            "evidence": "Synthetic PostgreSQL evidence for additional source guard testing",
        }
        uploaded = await api.post(
            f"/accounting/organizations/{pg_book[0]}/receipt-correction-evidence-files", json=evidence,
        )
        assert uploaded.status_code == 200, uploaded.text
        evidence_result = uploaded.json()
    basis = {"receipt_id": correction["id"], "receipt_version": 2, "tax_period": "2026-09"}
    workpaper_url = f"/accounting/organizations/{pg_book[0]}/inbound-vat-correction-workpapers"
    preview = await api.post(workpaper_url + "/preview", json=basis)
    return workpaper_url, basis, correction["id"], evidence_result, preview


async def direct_workpaper_values(session, org_id, correction_id: int, template: dict,
                                  evidence: dict | None):
    correction = await session.get(ReceiptDocument, correction_id)
    original = await session.get(ReceiptDocument, correction.correction_of_receipt_id)
    original_revision = await session.scalar(select(ReceiptRevision).where(
        ReceiptRevision.receipt_id == original.id, ReceiptRevision.version == correction.correction_of_version,
    ))
    correction_revision = await session.scalar(select(ReceiptRevision).where(
        ReceiptRevision.receipt_id == correction.id, ReceiptRevision.version == correction.current_version,
    ))
    entry = await session.get(Entry, correction.correction_of_entry_id)
    lines = (await session.scalars(select(Line).where(
        Line.entry_id == entry.id, (Line.account_code == "18") | Line.account_code.like("18.%"),
    ).order_by(Line.id))).all()
    snapshot = deepcopy(template)
    snapshot["organization_id"] = org_id
    snapshot["receipt"] = {
        "correction_receipt_id": correction.id,
        "correction_version": correction.current_version,
        "correction_revision_id": correction_revision.id,
        "correction_document_digest": _digest(correction_revision.document),
        "original_receipt_id": original.id,
        "original_version": correction.correction_of_version,
        "original_revision_id": original_revision.id,
        "original_document_digest": _digest(original_revision.document),
        "source_entry_id": entry.id,
        "source_entry": entry.source,
        "source_version": entry.source_version,
        "source_entry_digest": entry.digest,
        "source_posting_date": entry.posting_date.isoformat(),
        "source_operation_date": entry.operation_date.isoformat(),
    }
    snapshot["tax_period"] = "2026-09"
    snapshot["classification"] = ["vat_change"]
    snapshot["source_account_18_lines"] = [{
        "line_id": line.id, "account_id": line.account_id, "account_code": line.account_code,
        "account_title": line.account_title, "category": line.category, "cash": line.cash,
        "amount": f"{line.amount:.2f}", "currency": line.currency, "dimensions": line.dimensions or {},
    } for line in lines]
    snapshot["evidence_files"] = [] if evidence is None else [{
        key: evidence[key] for key in (
            "file_id", "receipt_id", "receipt_version", "kind", "tax_period", "reference",
            "filename", "content_type", "size_bytes", "sha256", "digest",
        )
    }]
    digest = _digest(snapshot)
    return {
        "organization_id": org_id,
        "receipt_id": correction.id,
        "receipt_version": correction.current_version,
        "correction_revision_id": correction_revision.id,
        "original_receipt_id": original.id,
        "original_version": correction.correction_of_version,
        "original_revision_id": original_revision.id,
        "source_entry_id": entry.id,
        "source_entry_digest": entry.digest,
        "tax_period": "2026-09",
        "revision": 1,
        "supersedes_id": None,
        "request_key": str(uuid4()),
        "request_digest": "a" * 64,
        "basis_digest": digest,
        "snapshot_digest": digest,
        "snapshot": json.dumps(snapshot),
        "reviewer_evidence": "Synthetic direct database guard verification",
        "actor": "pg-workpaper-test",
    }


async def seed_workpaper_api(api, factory, pg_book):
    async with factory() as session:
        await session.execute(text(
            "SELECT setval(pg_get_serial_sequence('accounting.account','id'), "
            "(SELECT max(id) FROM accounting.account))"
        ))
        await session.execute(text(
            "SELECT setval(pg_get_serial_sequence('accounting.organization','id'), "
            "(SELECT max(id) FROM accounting.organization))"
        ))
        session.add(Account(
            organization_id=pg_book[0], code="18", title="Synthetic input VAT", category="asset",
            valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
            quantity_tracking=False, cash=False, normative_ref="Synthetic VAT workpaper fixture",
        ))
        await session.commit()
        receipt_path, options = await source_options(api, session, pg_book)

    source_document = document()
    source_document["items"][0].update(vat_rate="20", vat_amount="20.00")
    edited = await api.put(receipt_path, json={
        "key": "pg-inbound-vat-source-with-tax",
        "expected_version": 1,
        "document": source_document,
    })
    assert edited.status_code == 200, edited.text
    options.update(expected_version=2, vat_account="18")
    posting_preview = await api.post(receipt_path + "/preview", json=options)
    assert posting_preview.status_code == 200, posting_preview.text
    posted = await api.post(receipt_path + "/confirm", json={
        **options, "digest": posting_preview.json()["digest"],
    })
    assert posted.status_code == 201, posted.text

    correction_response = await api.post(receipt_path + "/correction-drafts", json={
        "key": "pg-inbound-vat-correction", "expected_version": 2,
        "expected_entry_id": posted.json()["entry_id"],
    })
    assert correction_response.status_code == 201, correction_response.text
    correction = correction_response.json()
    revised_document = deepcopy(correction["revisions"][0]["document"])
    revised_document["items"][0].update(vat_rate="10", vat_amount="10.00")
    correction_id = correction["id"]
    changed = await api.put(
        f"/procurement/organizations/{pg_book[0]}/receipt-documents/{correction_id}",
        json={"key": "pg-inbound-vat-correction-vat-only", "expected_version": 1,
              "document": revised_document},
    )
    assert changed.status_code == 200 and changed.json()["version"] == 2, changed.text

    raw_xml = b"<?xml version='1.0'?><Eschf><Invoice>synthetic-pg</Invoice></Eschf>"
    evidence = {
        "request_key": str(uuid4()), "receipt_id": correction_id, "receipt_version": 2,
        "kind": "supplier_eschf_xml", "tax_period": "2026-09",
        "reference": "Synthetic supplier e-ЭСЧФ", "filename": "pg-source.xml",
        "data_url": "data:application/xml;base64," + base64.b64encode(raw_xml).decode(),
        "evidence": "Synthetic PostgreSQL evidence for database guard testing",
    }
    added_file = await api.post(
        f"/accounting/organizations/{pg_book[0]}/receipt-correction-evidence-files", json=evidence,
    )
    assert added_file.status_code == 200, added_file.text

    basis = {"receipt_id": correction_id, "receipt_version": 2, "tax_period": "2026-09"}
    base = f"/accounting/organizations/{pg_book[0]}/inbound-vat-correction-workpapers"
    preview = await api.post(base + "/preview", json=basis)
    assert preview.status_code == 200, preview.text
    create = {
        **basis,
        "request_key": str(uuid4()),
        "basis_digest": preview.json()["basis_digest"],
        "reviewer_evidence": "Synthetic accountant review of PostgreSQL source and file binding",
        "supersedes_workpaper_id": None,
    }
    first = await api.post(base, json=create)
    assert first.status_code == 201, first.text
    return base, basis, first.json()


async def test_pg_inbound_vat_workpaper_scope_immutability_and_concurrent_successor(
        issuance_pg, pg_book, tmp_path, monkeypatch):
    api, factory = issuance_pg
    api.headers["X-User"] = "tester"
    api.headers["X-User-Roles"] = "director"
    storage = tmp_path / "accounting-evidence"
    make_private_test_dir(storage)
    monkeypatch.setenv("AIOS_ACCOUNTING_EVIDENCE_DATA_DIR", str(storage.resolve()))
    base, basis, first = await seed_workpaper_api(api, factory, pg_book)

    assert first["revision"] == 1
    line, = first["snapshot"]["source_account_18_lines"]
    assert line["account_code"] == "18" and "side" not in line
    assert first["snapshot"]["evidence_files"][0]["sha256"]
    for key, expected in {
        "review_only": True,
        "signature_verified": False,
        "document_facts_verified": False,
        "deduction_eligibility_assessed": False,
        "accountant_accepted": False,
        "posting_available": False,
    }.items():
        assert first[key] is expected

    async def successor(index):
        command = {
            **basis,
            "request_key": str(uuid4()),
            "basis_digest": first["basis_digest"],
            "reviewer_evidence": f"Synthetic concurrent review contender number {index}",
            "supersedes_workpaper_id": first["workpaper_id"],
        }
        response = await api.post(base, json=command)
        return response.status_code, response

    outcomes = await asyncio.gather(successor(1), successor(2))
    assert sorted(status for status, _ in outcomes) == [201, 409], [response.text for _, response in outcomes]
    accepted = next(response.json() for status, response in outcomes if status == 201)
    assert accepted["revision"] == 2 and accepted["supersedes_workpaper_id"] == first["workpaper_id"]

    async with factory() as session:
        ledger_counts_before = (
            await session.scalar(select(func.count()).select_from(Entry)),
            await session.scalar(select(func.count()).select_from(Line)),
        )

    # Register a synthetic, explicitly pending classification and prove the
    # workpaper exposes only a verified navigation link on PostgreSQL.
    api.headers["X-User-Roles"] = "director,chief"
    register_url = f"/accounting/organizations/{pg_book[0]}/input-vat-register"
    register_command = {
        "request_key": str(uuid4()),
        "entry_id": first["source_entry_id"],
        "line_id": line["line_id"],
        "expected_entry_digest": first["source_entry_digest"],
        "tax_period": first["tax_period"],
        "invoice_reference": "SYN-PG-INPUT-VAT",
        "eschf_identifier": "SYN-PG-ESCHF",
        "deduction_status": "pending",
        "eschf_status": "provided",
        "right_basis": "Synthetic PostgreSQL navigation fixture only",
        "evidence": "Synthetic evidence does not prove deduction eligibility",
    }
    register_preview = await api.post(register_url + "/preview", json=register_command)
    assert register_preview.status_code == 200, register_preview.text
    register_confirmation = await api.post(
        register_url + "/confirm",
        headers={"X-Expected-Principal": "tester"},
        json={**register_command, "digest": register_preview.json()["digest"]},
    )
    assert register_confirmation.status_code == 201, register_confirmation.text
    registered = register_confirmation.json()
    assert registered["posted"] is False
    assert registered["deduction_assessed"] is False

    linked_responses = []
    for request_key in (first["request_key"], accepted["request_key"]):
        linked_response = await api.get(base + f"/by-request/{request_key}")
        assert linked_response.status_code == 200, linked_response.text
        linked = linked_response.json()
        assert linked["input_vat_register_links"] == {
            "status": "complete",
            "organization_id": pg_book[0],
            "source_entry_id": first["source_entry_id"],
            "source_entry_digest": first["source_entry_digest"],
            "source_line_count": 1,
            "registered_line_count": 1,
            "items": [{
                "register_entry_id": registered["id"],
                "source_line_id": line["line_id"],
                "register_digest": registered["digest"],
                "tax_period": first["tax_period"],
                "invoice_reference": register_command["invoice_reference"],
                "eschf_identifier": register_command["eschf_identifier"],
                "eschf_status": register_command["eschf_status"],
            }],
            "statutory_certified": False,
            "deduction_assessed": False,
            "posting_available": False,
        }
        assert linked["basis_digest"] == first["basis_digest"]
        assert linked["snapshot_digest"] == first["snapshot_digest"]
        assert not any(key in json.dumps(linked["input_vat_register_links"])
                       for key in ("amount", "side", "delta", "vat_delta", "deduction_status"))
        linked_responses.append(linked)

    history = await api.get(base, params={
        "receipt_id": first["receipt_id"],
        "receipt_version": first["receipt_version"],
        "tax_period": first["tax_period"],
    })
    assert history.status_code == 200, history.text
    assert all(row["input_vat_register_links"] == linked_responses[0]["input_vat_register_links"]
               for row in history.json())

    async with factory() as session:
        ledger_counts_after = (
            await session.scalar(select(func.count()).select_from(Entry)),
            await session.scalar(select(func.count()).select_from(Line)),
        )
    assert ledger_counts_after == ledger_counts_before

    async with factory() as session:
        rows = (await session.scalars(select(InboundVatCorrectionWorkpaper).order_by(
            InboundVatCorrectionWorkpaper.revision,
        ))).all()
        assert len(rows) == 2
        first_row = rows[0]
        other = Organization(name="Other VAT workpaper company", unp="876543210")
        session.add(other)
        await session.flush()
        other_id = other.id
        await session.commit()

        for statement in (
            "UPDATE accounting.inbound_vat_correction_workpaper SET actor='tampered' WHERE id=:id",
            "DELETE FROM accounting.inbound_vat_correction_workpaper WHERE id=:id",
            "TRUNCATE accounting.inbound_vat_correction_workpaper",
        ):
            with pytest.raises(DBAPIError, match="immutable"):
                async with session.begin_nested():
                    await session.execute(text(statement), {"id": first_row.id})

        snapshot = dict(first["snapshot"])
        snapshot["organization_id"] = other_id
        foreign_values = {
            "organization_id": other_id,
            "receipt_id": first["receipt_id"],
            "receipt_version": first["receipt_version"],
            "correction_revision_id": first_row.correction_revision_id,
            "original_receipt_id": first["original_receipt_id"],
            "original_version": first["original_version"],
            "original_revision_id": first_row.original_revision_id,
            "source_entry_id": first["source_entry_id"],
            "source_entry_digest": first["source_entry_digest"],
            "tax_period": first["tax_period"],
            "revision": 1,
            "supersedes_id": None,
            "request_key": str(uuid4()),
            "request_digest": "a" * 64,
            "basis_digest": "b" * 64,
            "snapshot_digest": "c" * 64,
            "snapshot": json.dumps(snapshot),
            "reviewer_evidence": "Synthetic cross-company database guard attempt",
            "actor": "pg-workpaper-test",
        }
        insert = text("""
            INSERT INTO accounting.inbound_vat_correction_workpaper
              (organization_id, receipt_id, receipt_version, correction_revision_id,
               original_receipt_id, original_version, original_revision_id, source_entry_id,
               source_entry_digest, tax_period, revision, supersedes_id, request_key,
               request_digest, basis_digest, snapshot_digest, snapshot, reviewer_evidence, actor)
            VALUES (:organization_id, :receipt_id, :receipt_version, :correction_revision_id,
               :original_receipt_id, :original_version, :original_revision_id, :source_entry_id,
               :source_entry_digest, :tax_period, :revision, :supersedes_id, :request_key,
               :request_digest, :basis_digest, :snapshot_digest, CAST(:snapshot AS jsonb),
               :reviewer_evidence, :actor)
        """)
        with pytest.raises(DBAPIError, match="exact current correction draft"):
            async with session.begin_nested():
                await session.execute(insert, foreign_values)

        stale_successor_values = {
            **foreign_values,
            "organization_id": pg_book[0],
            "receipt_id": first["receipt_id"],
            "receipt_version": first["receipt_version"],
            "correction_revision_id": first_row.correction_revision_id,
            "original_receipt_id": first["original_receipt_id"],
            "original_version": first["original_version"],
            "original_revision_id": first_row.original_revision_id,
            "source_entry_id": first["source_entry_id"],
            "source_entry_digest": first["source_entry_digest"],
            "revision": 3,
            "supersedes_id": first_row.id,
            "request_key": str(uuid4()),
            "snapshot": json.dumps(first["snapshot"]),
        }
        with pytest.raises(DBAPIError, match="latest same-scope revision"):
            async with session.begin_nested():
                await session.execute(insert, stale_successor_values)

        latest = rows[-1]
        for digest_field in ("correction_document_digest", "original_document_digest"):
            false_digest_snapshot = deepcopy(first["snapshot"])
            actual_digest = false_digest_snapshot["receipt"][digest_field]
            false_digest_snapshot["receipt"][digest_field] = "0" * 64 if actual_digest != "0" * 64 else "1" * 64
            false_digest = _digest(false_digest_snapshot)
            false_digest_values = {
                **stale_successor_values,
                "organization_id": pg_book[0],
                "revision": latest.revision + 1,
                "supersedes_id": latest.id,
                "request_key": str(uuid4()),
                "basis_digest": false_digest,
                "snapshot_digest": false_digest,
                "snapshot": json.dumps(false_digest_snapshot),
            }
            with pytest.raises(DBAPIError, match="immutable review evidence is invalid"):
                async with session.begin_nested():
                    await session.execute(insert, false_digest_values)

        missing_document_digest = deepcopy(first["snapshot"])
        del missing_document_digest["receipt"]["correction_document_digest"]
        malformed_snapshot_values = {
            **stale_successor_values,
            "organization_id": pg_book[0],
            "revision": latest.revision + 1,
            "supersedes_id": latest.id,
            "request_key": str(uuid4()),
            "snapshot": json.dumps(missing_document_digest),
        }
        with pytest.raises(DBAPIError, match="immutable review evidence is invalid"):
            async with session.begin_nested():
                await session.execute(insert, malformed_snapshot_values)

        _, _, no_evidence_receipt, _, no_evidence_preview = await seed_additional_correction(
            api, pg_book, tag="pg-workpaper-no-evidence", source_vat="20", corrected_vat="10",
            attach_evidence=False,
        )
        assert no_evidence_preview.status_code == 409 and "current correction evidence" in no_evidence_preview.text
        no_evidence_values = await direct_workpaper_values(
            session, pg_book[0], no_evidence_receipt, first["snapshot"], None,
        )
        with pytest.raises(DBAPIError, match="at least one current correction evidence file"):
            async with session.begin_nested():
                await session.execute(insert, no_evidence_values)

        _, _, zero_vat_receipt, zero_vat_evidence, zero_vat_preview = await seed_additional_correction(
            api, pg_book, tag="pg-workpaper-zero-vat", source_vat="0", corrected_vat="10",
            attach_evidence=True,
        )
        assert zero_vat_preview.status_code == 409 and "account-18 source line" in zero_vat_preview.text
        zero_vat_values = await direct_workpaper_values(
            session, pg_book[0], zero_vat_receipt, first["snapshot"], zero_vat_evidence,
        )
        with pytest.raises(DBAPIError, match="at least one exact account-18 source line"):
            async with session.begin_nested():
                await session.execute(insert, zero_vat_values)

        period = await session.scalar(select(Period).where(
            Period.organization_id == pg_book[0], Period.month == first["tax_period"],
        ))
        close_evidence = {
            key: "Synthetic close evidence"
            for key in ("documents", "bank", "settlements", "stock", "costing",
                        "depreciation", "fx", "tax", "financial_result", "trial_balance")
        }
        if period is None:
            period = Period(organization_id=pg_book[0], month=first["tax_period"],
                            closed=True, generation=0, closed_generation=0, evidence=close_evidence)
            session.add(period)
        else:
            period.evidence = close_evidence
            period.closed_generation = period.generation
            period.closed = True
        await session.flush()
        closed_values = {
            **stale_successor_values,
            "revision": latest.revision + 1,
            "supersedes_id": latest.id,
            "request_key": str(uuid4()),
            "snapshot": json.dumps(latest.snapshot),
        }
        with pytest.raises(DBAPIError, match="closed tax period"):
            async with session.begin_nested():
                await session.execute(insert, closed_values)
