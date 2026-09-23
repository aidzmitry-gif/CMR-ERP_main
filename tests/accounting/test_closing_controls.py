import base64
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from modules.accounting import models, service
from modules.accounting.models import (
    Entry,
    ForeignTradeRegisterEntry,
    Inbox,
    InputVatRegisterEntry,
    Line,
    OutputVatRegisterEntry,
    Period,
    SourceControl,
)
from modules.accounting.schemas import CloseInput
from modules.hr.models import Employee


async def _account(client, prefix, code, category):
    response = await client.post(prefix + "/accounts", json={
        "code": code, "title": "Synthetic " + code, "category": category,
        "required_dimensions": [], "valid_from": "2026-01-01",
        "currency_tracking": False, "quantity_tracking": False, "cash": False,
        "normative_ref": "Synthetic control only",
    })
    assert response.status_code == 201, response.text


async def test_closing_controls_report_queues_and_unregistered_vat(client, db, book, posting):
    prefix = f"/accounting/organizations/{book[0]}"
    await _account(client, prefix, "18", "asset")
    await _account(client, prefix, "90.2", "expense")
    for source, debit, credit in [("input-vat-source", "18", "60"), ("output-vat-source", "90.2", "62")]:
        payload = posting(source, debit, credit, "10.00", posting_date="2026-10-01",
                          document_date="2026-10-01", operation_date="2026-10-01").model_dump(mode="json")
        response = await client.post(prefix + "/entries", json=payload)
        assert response.status_code == 201, response.text
    db.add_all([
        Inbox(organization_id=book[0], event_key="pending-event", month="2026-10", payload={"explanation": "pending"}),
        SourceControl(organization_id=book[0], source="primary:pending", version=1, month="2026-10"),
    ])
    await db.commit()

    response = await client.get(prefix + "/periods/2026-10/closing-controls")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    result = response.json()
    assert result["status"] == "review_only"
    assert result["close_blocked_by_policy"] is False
    assert result["policy"] == {"id": book[1], "effective_from": "2026-01-01", "status": "verified",
                                 "normative_verified": True, "technical_preview_available": True,
                                 "confirmation_available": True}
    assert result["close_blocked_by_queues"] is True
    assert result["documents"] == {"pending_inbox": 1, "pending_source_controls": 1}
    assert result["vat"]["input_unregistered"] == 1
    assert result["vat"]["output_unregistered"] == 1
    assert {item["code"] for item in result["blockers"]} == {"unposted_inbox", "unposted_source_controls"}
    assert {item["code"] for item in result["review_items"]} >= {"input_vat_register", "output_vat_register"}
    assert result["statutory_certified"] is False
    assert result["production"] == {
        "postings": 0,
        "material_issues": 0,
        "material_issue_receipts": 0,
        "labor_imports": 0,
        "labor_receipts": 0,
        "overhead_allocations": 0,
        "overhead_receipts": 0,
        "output_transfers": 0,
        "output_transfer_receipts": 0,
        "stale_output_transfers": [],
        "receipt_gap": 0,
        "final_cost_certified": False,
    }
    assert result["inventory"]["late_cost_receipts"] == 0


async def test_closing_controls_is_scoped_and_read_only(client, db, book):
    prefix = f"/accounting/organizations/{book[0]}"
    response = await client.get(prefix + "/periods/2026-10/closing-controls")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["organization_id"] == book[0]
    assert result["period"]["closed"] is False
    assert result["blockers"] == []
    assert result["review_items"] == []
    assert result["policy"]["status"] == "verified"
    assert result["vat"]["statutory_certified"] is False
    assert await db.scalar(select(func.count()).select_from(Period)) == 0


async def test_closing_controls_surfaces_unverified_policy_without_certifying_it(client, db, book):
    db.add(models.Policy(organization_id=book[0], effective_from=date(2026, 10, 1), reference="Synthetic later policy",
                         inventory_method="specific", allocation_basis="direct_cost",
                         depreciation_method="straight_line", normative_reference="Synthetic only",
                         normative_verified=False, approved_by="tester"))
    await db.commit()

    response = await client.get(f"/accounting/organizations/{book[0]}/periods/2026-10/closing-controls")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["policy"]["status"] == "unverified"
    assert result["policy"]["technical_preview_available"] is True
    assert result["policy"]["confirmation_available"] is False
    assert result["close_blocked_by_policy"] is True
    assert {item["code"] for item in result["review_items"]} == {"policy_normative_basis"}
    assert result["statutory_certified"] is False


async def test_closing_controls_surfaces_late_inventory_cost_as_provisional(client, db, book, posting):
    await client.post(f"/accounting/organizations/{book[0]}/accounts", json={
        "code": "41.2", "title": "Quantitative goods", "category": "asset",
        "valid_from": "2026-01-01", "required_dimensions": [], "currency_tracking": True,
        "quantity_tracking": True, "cash": False, "normative_ref": "Synthetic",
    })
    payload = posting("late-cost-review", "41.2", "60", "10.00", posting_date="2026-10-01").model_dump(mode="json")
    payload["operation"] = "inventory_late_cost"
    payload["rule_version"] = "late-cost-byn-v1"
    payload["lines"][0]["quantity"] = None
    payload["lines"][0]["dimensions"] = {"warehouse": "W", "sku": "SKU", "lot": "LOT"}
    response = await client.post(f"/accounting/organizations/{book[0]}/entries", json=payload)
    assert response.status_code == 422, response.text

    # The ordinary public endpoint correctly rejects a cost-only package
    # without its dedicated source receipt; use a read-only synthetic entry
    # to prove the closing control query itself when no posting bypass exists.
    db.add(models.Entry(
        organization_id=book[0], source="late-cost-review-row", source_version=1,
        operation="inventory_late_cost", document_date=date(2026, 10, 1),
        operation_date=date(2026, 10, 1), posting_date=date(2026, 10, 1),
        policy_id=book[1], rule_version="late-cost-byn-v1", explanation="Synthetic review row",
        opening=False, correction_of=None, digest="a" * 64, actor="tester",
    ))
    await db.commit()
    result = (await client.get(f"/accounting/organizations/{book[0]}/periods/2026-10/closing-controls")).json()
    assert result["inventory"] == {"late_cost_postings": 1, "late_cost_receipts": 0,
                                    "final_cost_certified": False}
    assert {item["code"] for item in result["review_items"]} >= {"inventory_late_cost_provisional"}


async def test_closing_controls_surfaces_production_receipt_gap(client, db, book):
    db.add(models.Entry(
        organization_id=book[0], source="production:material:gap", source_version=1,
        operation="inventory_issue", document_date=date(2026, 10, 1),
        operation_date=date(2026, 10, 1), posting_date=date(2026, 10, 1),
        policy_id=book[1], rule_version="production-material-v2", explanation="Synthetic production gap",
        opening=False, correction_of=None, digest="d" * 64, actor="tester",
    ))
    await db.commit()

    result = (await client.get(f"/accounting/organizations/{book[0]}/periods/2026-10/closing-controls")).json()
    assert result["production"]["material_issues"] == 1
    assert result["production"]["material_issue_receipts"] == 0
    assert result["production"]["receipt_gap"] == 1
    assert {item["code"] for item in result["review_items"]} >= {
        "production_cost_provisional", "production_cost_receipt_gap",
    }


async def test_close_rejects_production_receipt_gap(db, book):
    db.add(models.Entry(
        organization_id=book[0], source="production:material:close-gap", source_version=1,
        operation="inventory_issue", document_date=date(2026, 10, 1),
        operation_date=date(2026, 10, 1), posting_date=date(2026, 10, 1),
        policy_id=book[1], rule_version="production-material-v2", explanation="Synthetic close gap",
        opening=False, correction_of=None, digest="e" * 64, actor="tester",
    ))
    await db.commit()

    with pytest.raises(service.AccountingError, match="receipts prevent closing"):
        await service.validate_close_period(db, book[0], "2026-10", CloseInput(
            expected_generation=0,
            evidence={step: "Synthetic checked" for step in service.CLOSE_STEPS},
        ))


async def test_closing_controls_surfaces_payroll_accrual_receipt_gap(client, db, book):
    db.add(models.Entry(
        organization_id=book[0], source="payroll:accrual:gap", source_version=1,
        operation="payroll_accrual_import", document_date=date(2026, 10, 1),
        operation_date=date(2026, 10, 1), posting_date=date(2026, 10, 1),
        policy_id=book[1], rule_version="verified-payroll-accrual-import-v1", explanation="Synthetic payroll gap",
        opening=False, correction_of=None, digest="f" * 64, actor="tester",
    ))
    await db.commit()

    result = (await client.get(f"/accounting/organizations/{book[0]}/periods/2026-10/closing-controls")).json()
    assert result["payroll"] == {
        "known_active_bindings": 0, "zero_activity_file_ids": [],
        "source_missing": False, "source_conflict": False,
        "gross_accruals": 1, "receipts": 0, "receipt_gap": 1,
        "statutory_imports": 0, "statutory_receipts": 0, "statutory_receipt_gap": 0,
        "statutory_payroll_certified": False,
        "deductions_and_contributions_available": False,
    }
    assert {item["code"] for item in result["review_items"]} >= {
        "payroll_accrual_provisional", "payroll_accrual_receipt_gap",
    }


async def test_known_employment_needs_month_payroll_source_before_close(
        client, db, book, tmp_path, monkeypatch):
    employee = Employee(full_name="Synthetic close employee", department="repair")
    db.add(employee)
    await db.commit()
    prefix = f"/accounting/organizations/{book[0]}"
    binding = await client.post(prefix + "/payroll-employments", json={
        "request_key": str(uuid4()), "employee_id": employee.id,
        "contract_ref": "test-close-contract", "effective_from": "2026-10-01",
        "state": "active", "source_document": "test-close-contract",
        "evidence": "Synthetic signed contract for close control",
    })
    assert binding.status_code == 200, binding.text
    url = prefix + "/periods/2026-10/closing-controls"
    controls = (await client.get(url)).json()
    assert controls["payroll"]["known_active_bindings"] == 1
    assert controls["payroll"]["source_missing"] is True
    assert "payroll_source_missing" in {item["code"] for item in controls["blockers"]}
    close = CloseInput(expected_generation=0, evidence={
        step: "Synthetic checked" for step in service.CLOSE_STEPS
    })
    with pytest.raises(service.AccountingError, match="Known payroll source is missing"):
        await service.validate_close_period(db, book[0], "2026-10", close)

    root = tmp_path / "payroll"
    root.mkdir()
    monkeypatch.setenv("AIOS_PAYROLL_DATA_DIR", str(root.resolve()))
    raw = b"%PDF-1.7\nsynthetic chief zero-accrual statement\n"
    command = {
        "request_key": str(uuid4()), "kind": "payroll_zero_activity",
        "month": "2026-10", "reference": "test-zero-payroll-2026-10",
        "filename": "zero-payroll.pdf",
        "data_url": "data:application/pdf;base64," + base64.b64encode(raw).decode(),
        "evidence": "Synthetic chief confirms zero accruals for this month",
    }
    saved = await client.post(prefix + "/payroll-evidence-files", json=command)
    assert saved.status_code == 200, saved.text
    assert saved.json()["document_facts_verified"] is False
    assert (await client.post(prefix + "/payroll-evidence-files", json=command)).json() == saved.json()
    controls = (await client.get(url)).json()
    assert controls["payroll"]["zero_activity_file_ids"] == [saved.json()["file_id"]]
    assert controls["payroll"]["source_missing"] is False
    assert "payroll_source_missing" not in {item["code"] for item in controls["blockers"]}
    await service.validate_close_period(db, book[0], "2026-10", close)

    storage_file = root / str(book[0]) / (command["request_key"].replace("-", "") + ".pdf")
    storage_file.write_bytes(b"%PDF-1.7\ntampered\n")
    from fastapi import HTTPException

    with pytest.raises(HTTPException, match="missing or differs"):
        await service.validate_close_period(db, book[0], "2026-10", close)
    storage_file.write_bytes(raw)

    db.add(models.Entry(
        organization_id=book[0], source="payroll:statutory:without-gross",
        source_version=1, operation="payroll_statutory_import",
        document_date=date(2026, 10, 1), operation_date=date(2026, 10, 1),
        posting_date=date(2026, 10, 1), policy_id=book[1],
        rule_version="verified-payroll-statutory-import-v1",
        explanation="Synthetic deductions cannot rely on zero-accrual source",
        opening=False, correction_of=None, digest="e" * 64, actor="tester",
    ))
    await db.commit()
    controls = (await client.get(url)).json()
    assert controls["payroll"]["source_missing"] is True
    assert controls["payroll"]["source_conflict"] is True

    db.add(models.Entry(
        organization_id=book[0], source="payroll:accrual:later-import",
        source_version=1, operation="payroll_accrual_import",
        document_date=date(2026, 10, 1), operation_date=date(2026, 10, 1),
        posting_date=date(2026, 10, 1), policy_id=book[1],
        rule_version="verified-payroll-accrual-import-v1",
        explanation="Synthetic late source supersedes zero statement",
        opening=False, correction_of=None, digest="f" * 64, actor="tester",
    ))
    await db.commit()
    controls = (await client.get(url)).json()
    assert controls["payroll"]["source_conflict"] is True
    assert "payroll_zero_activity_superseded" in {
        item["code"] for item in controls["review_items"]
    }
    with pytest.raises(service.AccountingError, match="receipts prevent closing"):
        await service.validate_close_period(db, book[0], "2026-10", close)


async def test_close_rejects_payroll_accrual_receipt_gap(db, book):
    db.add(models.Entry(
        organization_id=book[0], source="payroll:accrual:close-gap", source_version=1,
        operation="payroll_accrual_import", document_date=date(2026, 10, 1),
        operation_date=date(2026, 10, 1), posting_date=date(2026, 10, 1),
        policy_id=book[1], rule_version="verified-payroll-accrual-import-v1", explanation="Synthetic payroll close gap",
        opening=False, correction_of=None, digest="g" * 64, actor="tester",
    ))
    await db.commit()

    with pytest.raises(service.AccountingError, match="receipts prevent closing"):
        await service.validate_close_period(db, book[0], "2026-10", CloseInput(
            expected_generation=0,
            evidence={step: "Synthetic checked" for step in service.CLOSE_STEPS},
        ))


async def test_closing_controls_surfaces_payroll_statutory_receipt_gap(client, db, book):
    db.add(models.Entry(
        organization_id=book[0], source="payroll:statutory:gap", source_version=1,
        operation="payroll_statutory_import", document_date=date(2026, 10, 1),
        operation_date=date(2026, 10, 1), posting_date=date(2026, 10, 1),
        policy_id=book[1], rule_version="verified-payroll-statutory-import-v1", explanation="Synthetic statutory gap",
        opening=False, correction_of=None, digest="h" * 64, actor="tester",
    ))
    await db.commit()

    result = (await client.get(f"/accounting/organizations/{book[0]}/periods/2026-10/closing-controls")).json()
    assert result["payroll"]["statutory_imports"] == 1
    assert result["payroll"]["statutory_receipts"] == 0
    assert result["payroll"]["statutory_receipt_gap"] == 1
    assert result["payroll"]["deductions_and_contributions_available"] is False
    assert {item["code"] for item in result["review_items"]} >= {
        "payroll_statutory_provisional", "payroll_statutory_receipt_gap",
    }


async def test_close_rejects_payroll_statutory_receipt_gap(db, book):
    db.add(models.Entry(
        organization_id=book[0], source="payroll:statutory:close-gap", source_version=1,
        operation="payroll_statutory_import", document_date=date(2026, 10, 1),
        operation_date=date(2026, 10, 1), posting_date=date(2026, 10, 1),
        policy_id=book[1], rule_version="verified-payroll-statutory-import-v1", explanation="Synthetic statutory close gap",
        opening=False, correction_of=None, digest="i" * 64, actor="tester",
    ))
    await db.commit()

    with pytest.raises(service.AccountingError, match="receipts prevent closing"):
        await service.validate_close_period(db, book[0], "2026-10", CloseInput(
            expected_generation=0,
            evidence={step: "Synthetic checked" for step in service.CLOSE_STEPS},
        ))


async def test_closing_controls_surfaces_registered_vat_with_unresolved_evidence(client, db, book, posting):
    prefix = f"/accounting/organizations/{book[0]}"
    await _account(client, prefix, "18", "asset")
    await _account(client, prefix, "60.9", "liability")
    await _account(client, prefix, "90.2", "expense")
    await _account(client, prefix, "62.9", "asset")
    for source, debit, credit in [("vat-status-input", "18", "60.9"), ("vat-status-output", "90.2", "62.9")]:
        response = await client.post(prefix + "/entries", json=posting(
            source, debit, credit, "10.00", posting_date="2026-10-01").model_dump(mode="json"))
        assert response.status_code == 201, response.text
    input_entry = await db.scalar(select(Entry).where(Entry.organization_id == book[0], Entry.source == "vat-status-input"))
    output_entry = await db.scalar(select(Entry).where(Entry.organization_id == book[0], Entry.source == "vat-status-output"))
    input_line = await db.scalar(select(Line).where(Line.entry_id == input_entry.id).order_by(Line.id))
    output_line = await db.scalar(select(Line).where(Line.entry_id == output_entry.id).order_by(Line.id))
    db.add_all([
        InputVatRegisterEntry(organization_id=book[0], request_key=str(uuid4()), entry_id=input_entry.id,
                              line_id=input_line.id, source=input_entry.source, source_version=1,
                              entry_digest=input_entry.digest, posting_date=date(2026, 10, 1), tax_period="2026-10",
                              amount=Decimal("10.00"), currency="BYN", side="debit", invoice_reference="IN-1",
                              deduction_status="pending", eschf_status="pending", right_basis="Synthetic",
                              evidence="Synthetic", command={}, digest="a" * 64, actor="tester"),
        OutputVatRegisterEntry(organization_id=book[0], request_key=str(uuid4()), entry_id=output_entry.id,
                               line_id=output_line.id, source=output_entry.source, source_version=1,
                               entry_digest=output_entry.digest, posting_date=date(2026, 10, 1), tax_period="2026-10",
                               amount=Decimal("10.00"), currency="BYN", side="credit", invoice_reference="OUT-1",
                               tax_treatment="pending", eschf_status="pending", treatment_basis="Synthetic",
                               export_evidence=None, evidence="Synthetic", command={}, digest="b" * 64, actor="tester"),
    ])
    await db.commit()
    result = (await client.get(prefix + "/periods/2026-10/closing-controls")).json()
    assert result["vat"]["input_registered"] == 1 and result["vat"]["input_unresolved"] == 1
    assert result["vat"]["output_registered"] == 1 and result["vat"]["output_unresolved"] == 1
    assert {item["code"] for item in result["review_items"]} >= {"input_vat_evidence", "output_vat_evidence"}


async def test_closing_controls_surfaces_unresolved_foreign_trade_evidence(client, db, book, posting):
    prefix = f"/accounting/organizations/{book[0]}"
    await _account(client, prefix, "10.9", "asset")
    await _account(client, prefix, "60.9", "liability")
    response = await client.post(prefix + "/entries", json=posting(
        "trade-status", "10.9", "60.9", "10.00", posting_date="2026-10-01").model_dump(mode="json"))
    assert response.status_code == 201, response.text
    entry = await db.scalar(select(Entry).where(Entry.organization_id == book[0], Entry.source == "trade-status"))
    line = await db.scalar(select(Line).where(Line.entry_id == entry.id).order_by(Line.id))
    db.add(ForeignTradeRegisterEntry(
        organization_id=book[0], request_key=str(uuid4()), entry_id=entry.id, line_id=line.id,
        source=entry.source, source_version=1, entry_digest=entry.digest, posting_date=date(2026, 10, 1),
        tax_period="2026-10", trade_mode="eaeu_import", partner_country="KZ",
        contract_reference="C-1", invoice_reference="I-1", customs_reference=None,
        eaeu_reference=None, incoterms=None, amount=Decimal("10.00"), currency="BYN",
        original_amount=None, rate=None, rate_scale=None, rate_date=None, rate_source=None,
        customs_duty=Decimal("0"), import_vat=Decimal("0"), export_evidence=None,
        evidence="Synthetic unresolved trade evidence", command={}, digest="c" * 64, actor="tester",
    ))
    await db.commit()
    result = (await client.get(prefix + "/periods/2026-10/closing-controls")).json()
    assert result["foreign_trade"] == {"entries": 1, "unresolved": 1, "statutory_certified": False}
    assert {item["code"] for item in result["review_items"]} >= {"foreign_trade_evidence"}
