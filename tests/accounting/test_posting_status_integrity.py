"""Lost-response recovery must distinguish a verified receipt from corrupt joins.

The isolated SQLite projections deliberately include untrusted/dangling links;
they test HTTP read admission, not PostgreSQL write or production acceptance.
"""
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from modules.accounting import models

FAMILIES = [
    ("output", models.ProductionOutputTransferReceipt, "production_output_transfer", "production:output-transfer"),
    ("labor", models.ProductionLaborReceipt, "production_labor_import", "production:labor"),
    ("accrual", models.PayrollAccrualReceipt, "payroll_accrual_import", "payroll:accrual"),
    ("statutory", models.PayrollStatutoryReceipt, "payroll_statutory_import", "payroll:statutory"),
    ("repair", models.RepairAccountingReceipt, "repair_service", "service:repair"),
]


async def _projection(db, book, family, problem):
    name, model, operation, prefix = family
    request_key = str(uuid4())
    source_document = "synthetic-reviewed-batch"
    source_id = 17 if name in {"output", "repair"} else source_document
    source = f"{prefix}:{book[0]}:{source_id}"
    entry_org = book[0]
    if problem == "foreign_organization":
        other = models.Organization(name="Synthetic other book", unp="999999998")
        db.add(other)
        await db.flush()
        entry_org = other.id
    entry = models.Entry(
        organization_id=entry_org, source="synthetic:wrong-source" if problem == "source" else source,
        source_version=2 if problem == "version" else 1,
        operation="manual" if problem == "operation" else operation,
        document_date=date(2026, 9, 30), operation_date=date(2026, 9, 30),
        posting_date=date(2026, 9, 30), policy_id=book[1], rule_version="synthetic-status-v1",
        explanation="Synthetic immutable recovery projection", opening=False,
        digest="b" * 64 if problem == "digest" else "a" * 64, actor="tester",
    )
    db.add(entry)
    await db.flush()
    receipt_fields = dict(
        entry_id=999999 if problem == "missing_entry" else entry.id,
        organization_id=book[0], month="2026-09", command={}, posting={}, digest="a" * 64,
        actor="tester",
    )
    if name == "output":
        receipt_fields.update(order_id=17, basis={}, basis_digest="c" * 64)
        suffix = "periods/2026-09/production-output-transfer-status/17"
    else:
        receipt_fields.update(
            request_key=request_key, source_version=1, source_digest="d" * 64, source={},
        )
        if name == "repair":
            receipt_fields.update(
                service_request_id=17, serial_number="SYNTHETIC-001", owner_type="customer",
                owner_reference="Synthetic customer", coverage="paid", financial_result={},
            )
            suffix = f"repairs/{request_key}"
        else:
            receipt_fields["source_document"] = source_document
            route = {"labor": "production-labor", "accrual": "payroll-accrual", "statutory": "payroll-statutory"}[name]
            suffix = f"{route}-import-status/{request_key}"
    if problem != "missing_receipt":
        db.add(model(**receipt_fields))
    await db.commit()
    return f"/accounting/organizations/{book[0]}/{suffix}", entry.id


@pytest.mark.parametrize("family", FAMILIES, ids=lambda value: value[0])
@pytest.mark.parametrize("problem", [
    "ok", "missing_receipt", "missing_entry", "foreign_organization", "operation", "digest", "source", "version",
])
async def test_recovery_status_requires_the_exact_scoped_ledger_entry(client, db, book, family, problem):
    path, entry_id = await _projection(db, book, family, problem)
    model = family[1]
    before = (await db.scalar(select(func.count()).select_from(models.Entry)),
              await db.scalar(select(func.count()).select_from(model)))
    response = await client.get(path)
    expected = 200 if problem == "ok" else 404 if problem == "missing_receipt" else 409
    assert response.status_code == expected, response.text
    if problem == "ok":
        result = response.json()
        assert result["posted"] is True
        assert result["organization_id"] == book[0] and result["entry_id"] == entry_id
        assert result["digest"] == "a" * 64
        if "entry" in result:
            assert result["entry"]["digest"] == result["digest"]
        assert response.headers["Cache-Control"] == "private, no-store"
    else:
        assert "posted" not in response.json()
        assert "not found" in response.json()["detail"] if expected == 404 else "inconsistent" in response.json()["detail"]
    assert (await db.scalar(select(func.count()).select_from(models.Entry)),
            await db.scalar(select(func.count()).select_from(model))) == before
