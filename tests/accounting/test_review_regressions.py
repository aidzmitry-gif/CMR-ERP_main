from datetime import date

import pytest

from modules.accounting import reports, service
from modules.accounting.models import Policy
from modules.accounting.schemas import CloseInput


async def test_arbitrary_operation_label_cannot_hide_income(db, book, posting):
    with pytest.raises(service.AccountingError, match="reserved"):
        await service.post(db, book[0], posting("ordinary-sale", "62", "90.1", operation="period_close"), "tester")
    await service.post(db, book[0], posting("ordinary-sale", "62", "90.1"), "tester")
    with pytest.raises(service.AccountingError, match="reserved"):
        await service.post(db, book[0], posting("transfer", "90.1", "80", operation="period_close"), "tester")
    with pytest.raises(service.AccountingError, match="not implemented"):
        await service.post(db, book[0], posting("transfer-manual", "90.1", "80"), "tester")
    result = await reports.report(db, book[0], date(2026, 9, 1), date(2026, 9, 30))
    assert result["pnl"]["profit"] == "100.00"
    assert len(result["movements"]) == 2


async def test_unregistered_currency_is_rejected_even_with_a_complete_rate(db, book, posting):
    item = posting().model_dump(mode="json")
    item["lines"][0].update(currency="XYZ", original_amount="100.00", rate="1",
                            rate_scale=1, rate_date="2026-09-01", rate_source="Untrusted source")
    from modules.accounting.schemas import PostingInput

    with pytest.raises(service.AccountingError, match="Unknown"):
        await service.post(db, book[0], PostingInput.model_validate(item), "tester")


async def test_opening_import_can_be_previewed_and_retried_after_close(client, book, posting, opening_package):
    prefix = f"/accounting/organizations/{book[0]}"
    data = opening_package([posting("opening", "51", "80", opening=True)], batch="retry-control")
    first = await client.post(prefix + "/imports/confirm", json=data)
    assert first.status_code == 200
    closed = await client.post(prefix + "/periods/2026-09/close", json={
        "expected_generation": 1, "evidence": {step: "control" for step in service.CLOSE_STEPS},
    })
    assert closed.status_code == 200
    assert (await client.post(prefix + "/imports/preview", json=data)).status_code == 200
    assert (await client.post(prefix + "/preview", json=data["entries"][0])).status_code == 200
    again = await client.post(prefix + "/imports/confirm", json=data)
    assert again.json()["entry_ids"] == first.json()["entry_ids"]
    data["entries"][0]["explanation"] = "different payload"
    assert (await client.post(prefix + "/imports/preview", json=data)).status_code == 422


async def test_commit_failure_is_an_error_response_not_premature_success(client, db, monkeypatch):
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    from modules.accounting.models import Organization

    async def fail_commit():
        raise IntegrityError("COMMIT", {}, RuntimeError("synthetic deferred failure"))

    monkeypatch.setattr(db, "commit", fail_commit)
    response = await client.post("/accounting/organizations", json={
        "name": "Rollback control", "unp": "111111111",
    })
    assert response.status_code == 409
    assert await db.scalar(select(Organization.id).where(Organization.unp == "111111111")) is None


async def test_midmonth_unverified_policy_prevents_close(db, book, posting):
    policy = Policy(organization_id=book[0], effective_from=date(2026, 9, 15),
                    reference="changed", inventory_method="fifo", allocation_basis="direct_cost",
                    depreciation_method="straight_line", normative_reference="unverified",
                    normative_verified=False, approved_by="tester")
    db.add(policy)
    await db.flush()
    await service.post(db, book[0], posting(posting_date="2026-09-20", policy_id=policy.id), "tester")
    with pytest.raises(service.AccountingError, match="Normative"):
        await service.close_period(db, book[0], "2026-09", CloseInput(
            expected_generation=1, evidence={k: "checked" for k in service.CLOSE_STEPS}), "tester")
