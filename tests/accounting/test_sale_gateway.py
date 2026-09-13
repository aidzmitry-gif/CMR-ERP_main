from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from core.services.auth import CurrentUser
from modules.accounting import models, reports, sales, service
from modules.accounting.gateway import AccountingService
from modules.accounting.schemas import CloseInput
from tests.accounting.test_sales import setup_sale


async def test_source_sale_registration_confirmation_and_exact_replay(db, book, posting):
    document = await setup_sale(db, book, posting, quantity="3", source="sales:primary:1")
    gateway, user = AccountingService(), CurrentUser("tester", ["director"])
    with pytest.raises(HTTPException) as missing:
        await gateway.sale_posting(db, book[0], user, document, confirm_digest=None)
    assert missing.value.status_code == 409
    await gateway.source_changed(db, book[0], user, document["source"], 1, "2026-09-01")
    await db.commit()
    control = await db.scalar(select(models.SourceControl))
    assert control.entry_id is None
    report = await reports.report(db, book[0], date(2026, 9, 1), date(2026, 9, 30))
    assert report["pending_documents"] == 1
    period = await db.scalar(select(models.Period))
    with pytest.raises(service.AccountingError, match="Unposted primary documents"):
        await service.close_period(db, book[0], "2026-09", CloseInput(expected_generation=period.generation, evidence={step: "Synthetic control evidence" for step in service.CLOSE_STEPS}), "tester")
    prepared = await gateway.sale_posting(db, book[0], user, document, confirm_digest=None)
    result = await gateway.sale_posting(db, book[0], user, document, confirm_digest=prepared["digest"], basis_digest=prepared["cost"]["basis_digest"])
    await db.commit()
    assert control.entry_id == result["entry_id"]
    receipt = await db.get(models.InventorySaleReceipt, result["entry_id"])
    assert receipt.command == sales.SaleDocument.model_validate(document).model_dump(mode="json")
    assert receipt.digest == result["digest"] and receipt.actor == "tester"
    assert receipt.cost["basis_digest"] == prepared["cost"]["basis_digest"]
    report = await reports.report(db, book[0], date(2026, 9, 1), date(2026, 9, 30))
    assert report["pending_documents"] == 0
    repeated = await gateway.sale_posting(db, book[0], user, document, confirm_digest=prepared["digest"], basis_digest=prepared["cost"]["basis_digest"])
    assert repeated["entry_id"] == result["entry_id"]
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == 2
    assert await db.scalar(select(func.count()).select_from(models.InventorySaleReceipt)) == 1
    assert await db.scalar(select(func.count()).select_from(models.Audit).where(models.Audit.action == "source_posted")) == 1


@pytest.mark.parametrize("case", ["version", "period", "reader", "foreign", "missing_basis"])
async def test_source_sale_rejects_unregistered_version_period_and_access(db, book, posting, case):
    document = await setup_sale(db, book, posting, source="sales:primary:1")
    gateway, user = AccountingService(), CurrentUser("tester", ["director"])
    await gateway.source_changed(db, book[0], user, document["source"], 1, "2026-09-01")
    await db.commit()
    if case == "reader":
        grant = await db.scalar(select(models.AccessGrant))
        grant.role = "reader"
        await db.commit()
    if case == "version":
        document["source_version"] = 2
    if case == "period":
        document["posting_date"] = "2026-10-01"
    with pytest.raises(HTTPException) as rejected:
        await gateway.sale_posting(db, 999 if case == "foreign" else book[0], user, document, confirm_digest="0" * 64 if case == "missing_basis" else None)
    assert rejected.value.status_code == {"version": 409, "period": 422, "reader": 403, "foreign": 403, "missing_basis": 422}[case]
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == 1
    assert (await db.scalar(select(models.SourceControl))).entry_id is None
