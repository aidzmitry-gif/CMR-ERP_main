"""Special ledger operations cannot bypass their reviewed source workflows."""
from datetime import date

import pytest
from sqlalchemy import func, select

from modules.accounting import models, service

SPECIAL_OPERATIONS = [
    "inventory_purchase", "production_output_cost_correction", "production_overhead_correction",
    "production_output_transfer", "production_labor_import", "payroll_accrual_import",
    "payroll_statutory_import", "fixed_asset_depreciation", "repair_service", "fx_revaluation",
    "settlement_offset", "production_overhead", "inventory_late_cost", "inventory_sale",
    "inventory_issue", "period_close", "period_reopen",
]
INTERNAL_FLAGS = [
    "inventory_purchase", "production_output_correction", "production_correction",
    "production_output_transfer", "production_labor_import", "payroll_accrual_import",
    "payroll_statutory_import", "fixed_asset_depreciation", "repair_accounting", "fx_revaluation",
    "settlement_offset", "production_overhead", "late_cost", "financial_transfer",
]


async def _counts(db):
    return tuple([await db.scalar(select(func.count()).select_from(table)) for table in (
        models.Entry, models.Line, models.Period,
    )])


@pytest.mark.parametrize("operation", SPECIAL_OPERATIONS)
async def test_general_entry_endpoint_cannot_impersonate_reviewed_workflow(client, db, book, posting, operation):
    command = posting(source=f"synthetic:manual-bypass:{operation}", operation=operation)
    before = await _counts(db)
    response = await client.post(f"/accounting/organizations/{book[0]}/entries",
                                 json=command.model_dump(mode="json"))
    assert response.status_code == 422 and "require" in response.json()["detail"].lower()
    assert await _counts(db) == before


@pytest.mark.parametrize("flag", INTERNAL_FLAGS)
async def test_internal_workflow_flag_rejects_an_unrelated_manual_command(db, book, posting, flag):
    command = posting(source=f"synthetic:internal-mismatch:{flag}")
    before = await _counts(db)
    with pytest.raises(service.AccountingError) as error:
        await service.validate_posting(db, book[0], command, **{flag: True})
    assert str(error.value).startswith("Invalid internal")
    assert await _counts(db) == before


@pytest.mark.parametrize("original_operation, original_day, expected", [
    ("production_overhead", "2026-09-01", "dedicated allocation correction workflow"),
    ("production_overhead_correction", "2026-09-01", "dedicated allocation correction workflow"),
    ("manual", "2026-09-02", "Correction cannot precede its original"),
    ("period_close", "2026-09-01", "dedicated reopening command"),
    ("period_reopen", "2026-09-01", "dedicated reopening command"),
])
async def test_general_correction_cannot_rewrite_special_or_future_history(
    db, book, posting, original_operation, original_day, expected,
):
    # A synthetic existing entry is inserted once, never updated or deleted.
    original = models.Entry(
        organization_id=book[0], source="synthetic:original", source_version=1,
        operation=original_operation, document_date=date.fromisoformat(original_day),
        operation_date=date.fromisoformat(original_day), posting_date=date.fromisoformat(original_day),
        policy_id=book[1], rule_version="synthetic-control-v1", explanation="Synthetic reviewed history",
        opening=False, digest="a" * 64, actor="tester",
    )
    db.add(original)
    await db.commit()
    command = posting(source="synthetic:correction", correction_of=original.id, source_version=2)
    before = await _counts(db)
    with pytest.raises(service.AccountingError) as error:
        await service.validate_posting(db, book[0], command)
    assert expected in str(error.value)
    assert await _counts(db) == before


async def test_financial_reopening_requires_its_original_closing_entry(db, book, posting):
    before = await _counts(db)
    with pytest.raises(service.AccountingError) as error:
        await service.validate_posting(
            db, book[0], posting(operation="period_reopen"), financial_transfer=True,
        )
    assert str(error.value) == "Financial reopening requires its original entry"
    assert await _counts(db) == before
