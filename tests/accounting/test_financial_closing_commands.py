"""Internal command contract; these tests do not certify pending SQL/API integration."""
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from modules.accounting import closing_commands, reports, service
from modules.accounting.financial_closing import preview
from modules.accounting.models import Entry, FinancialCloseReceipt, FinancialReopenReceipt, Period
from modules.accounting.schemas import CloseInput, FinancialCloseInput, FinancialReopenInput
from tests.accounting.test_closing_policy import policy_body
from tests.accounting.test_financial_closing_preview import post, setup_policy


async def close(db, org, month="2026-10"):
    plan = await preview(db, org, month)
    body = FinancialCloseInput(request_key=uuid4(), expected_basis_digest=plan["basis_digest"],
        expected_generation=plan["period_generation"], evidence={step: "Synthetic reviewed control" for step in service.CLOSE_STEPS})
    receipt = await closing_commands.confirm(db, org, month, body, "tester")
    await db.commit()
    return body, receipt


@pytest.mark.parametrize("year_end,income,expense,result,equity", [
    (12, "180.00", "100.00", "80.00", "0.00"),
    (10, "180.00", "100.00", "0.00", "80.00"),
    (10, "80.00", "180.00", "0.00", "-100.00"),
    (10, "100.00", "100.00", "0.00", "0.00"),
])
async def test_close_keeps_operating_pnl_and_posts_actual_balance(client, db, book, posting,
                                                                year_end, income, expense, result, equity):
    prefix, policy = await setup_policy(client, book, year_end, normative_verified=True)
    await post(client, prefix, posting, policy, "purchase", "41", "60", "50.00")
    await post(client, prefix, posting, policy, "income", "62", "701", income)
    await post(client, prefix, posting, policy, "expense", "702", "60", expense)
    before = await reports.report(db, book[0], date(2026, 10, 1), date(2026, 10, 31))
    assert "purchase" not in {row["source"] for row in before["pnl_movements"]}
    assert {row["category"] for row in before["pnl_movements"]} == {"income", "expense"}
    assert sum(Decimal(row["amount"]) * (Decimal("1") if row["side"] == "debit" else Decimal("-1"))
               for row in before["pnl_movements"] if row["category"] == "income") == -Decimal(before["pnl"]["income"])
    assert sum(Decimal(row["amount"]) * (Decimal("1") if row["side"] == "debit" else Decimal("-1"))
               for row in before["pnl_movements"] if row["category"] == "expense") == Decimal(before["pnl"]["expenses"])
    body, receipt = await close(db, book[0])
    after = await reports.report(db, book[0], date(2026, 10, 1), date(2026, 10, 31))
    assert after["pnl"] == before["pnl"]
    assert after["pnl_movements"] == before["pnl_movements"]
    technical_ids = set(await db.scalars(select(Entry.id).where(Entry.operation == "period_close")))
    assert technical_ids
    assert not technical_ids.intersection(row["entry_id"] for row in after["pnl_movements"])
    assert after["balance"]["current_result"] == result
    assert after["balance"]["equity"] == equity
    assert after["balance"]["difference"] == "0.00"
    assert all(row["closing"] == "0.00" for row in after["trial_balance"] if row["account"] in {"701", "702"})
    count = await db.scalar(select(func.count()).select_from(Entry))
    assert (await closing_commands.confirm(db, book[0], "2026-10", body, "tester")).id == receipt.id
    assert await db.scalar(select(func.count()).select_from(Entry)) == count
    changed = body.model_copy(update={"expected_basis_digest": "0" * 64})
    with pytest.raises(service.AccountingError, match="different content"):
        await closing_commands.confirm(db, book[0], "2026-10", changed, "tester")


async def test_stale_basis_and_generic_close_are_rejected_before_technical_entries(client, db, book, posting):
    prefix, policy = await setup_policy(client, book, normative_verified=True)
    plan = await preview(db, book[0], "2026-10")
    body = FinancialCloseInput(request_key=uuid4(), expected_basis_digest=plan["basis_digest"], expected_generation=0,
        evidence={step: "Synthetic reviewed control" for step in service.CLOSE_STEPS})
    await post(client, prefix, posting, policy, "late", "62", "701", "1.00")
    with pytest.raises(service.AccountingError, match="basis changed"):
        await closing_commands.confirm(db, book[0], "2026-10", body, "tester")
    with pytest.raises(service.AccountingError, match="dedicated closing"):
        await service.close_period(db, book[0], "2026-10", CloseInput(expected_generation=1, evidence=body.evidence), "tester")
    assert await db.scalar(select(func.count()).select_from(FinancialCloseReceipt)) == 0
    assert await db.scalar(select(func.count()).select_from(Entry)) == 1


@pytest.mark.parametrize("empty", [False, True])
async def test_reopen_reverses_technical_entries_and_empty_months_without_changing_pnl(client, db, book, posting, empty):
    prefix, policy = await setup_policy(client, book, year_end=10, normative_verified=True)
    if not empty:
        await post(client, prefix, posting, policy, "income", "62", "701", "180.00")
        await post(client, prefix, posting, policy, "expense", "702", "60", "100.00")
    first_body, first = await close(db, book[0])
    before = await reports.report(db, book[0], date(2026, 10, 1), date(2026, 10, 31))
    with pytest.raises(service.AccountingError, match="dedicated reopening"):
        await service.reopen_period(db, book[0], "2026-10", "Synthetic correction", "tester")
    body = FinancialReopenInput(request_key=uuid4(), reason="Synthetic correction of reviewed source")
    receipt = await closing_commands.reopen(db, book[0], "2026-10", body, "tester")
    await db.commit()
    after = await reports.report(db, book[0], date(2026, 10, 1), date(2026, 10, 31))
    assert after["pnl"] == before["pnl"]
    assert after["balance"]["current_result"] == ("0.00" if empty else "80.00")
    assert after["balance"]["equity"] == "0.00"
    assert after["balance"]["difference"] == "0.00"
    period = await db.scalar(select(Period))
    assert not period.closed and period.generation > first.snapshot["closed_generation"]
    count = await db.scalar(select(func.count()).select_from(Entry))
    assert count == (0 if empty else 6)
    assert (await closing_commands.reopen(db, book[0], "2026-10", body, "tester")).id == receipt.id
    assert (await closing_commands.confirm(db, book[0], "2026-10", first_body, "tester")).id == first.id
    assert not period.closed  # Historical retry must not re-close a reopened period.
    _, second = await close(db, book[0])
    assert second.id != first.id
    assert await db.scalar(select(func.count()).select_from(FinancialReopenReceipt)) == 1


async def test_reopen_cascades_across_year_end_and_later_month(client, db, book, posting):
    prefix, policy = await setup_policy(client, book, year_end=10, normative_verified=True)
    await post(client, prefix, posting, policy, "oct-income", "62", "701", "80.00")
    await close(db, book[0])
    data = posting("nov-income", "62", "701", "50.00", policy_id=policy,
        document_date="2026-11-01", operation_date="2026-11-01", posting_date="2026-11-01")
    data.lines[1].dimensions = {"department": "source"}
    await service.post(db, book[0], data, "tester")
    await db.commit()
    await close(db, book[0], "2026-11")
    body = FinancialReopenInput(request_key=uuid4(), reason="Synthetic cascading correction")
    receipt = await closing_commands.reopen(db, book[0], "2026-10", body, "tester")
    await db.commit()
    assert len(receipt.snapshot["items"]) == 2
    assert all(not p.closed for p in (await db.scalars(select(Period))).all())
    report = await reports.report(db, book[0], date(2026, 10, 1), date(2026, 11, 30))
    assert report["pnl"]["profit"] == "130.00"
    assert report["balance"]["current_result"] == "130.00"
    assert report["balance"]["equity"] == "0.00"


@pytest.mark.parametrize("change", [{"opening_balance_treatment": "exclude"}, {"year_end_month": 11},
                                  {"result_dimensions": {"department": "changed"}}])
async def test_policy_transition_cannot_reinterpret_active_historical_closes(client, db, book, posting, change):
    prefix, policy = await setup_policy(client, book, normative_verified=True)
    await post(client, prefix, posting, policy, "opening", "62", "701", "100.00", opening=True)
    await close(db, book[0])
    body = policy_body()
    body.update(effective_from="2026-11-01", normative_verified=True)
    body["financial_closing"].update(monthly_accounts=["701", "702"], result_account="703",
                                     retained_earnings_account="704", **change)
    response = await client.post(prefix + "/policies", json=body)
    assert response.status_code == 201, response.text
    with pytest.raises(service.AccountingError, match="policy changed since an active close"):
        await preview(db, book[0], "2026-11")
    await closing_commands.reopen(db, book[0], "2026-10", FinancialReopenInput(
        request_key=uuid4(), reason="Synthetic explicit transition review"), "tester")
    await db.commit()
    result = await preview(db, book[0], "2026-11")
    if change.get("opening_balance_treatment") == "exclude":
        assert result["monthly_lines"] == [] and result["annual_lines"] == []


async def test_closing_invalidates_fresh_future_generation_in_retained_session(client, db, book, posting):
    prefix, policy = await setup_policy(client, book, normative_verified=True)
    await post(client, prefix, posting, policy, "income", "62", "701", "80.00")
    future = Period(organization_id=book[0], month="2026-11", generation=5, closed=False)
    db.add(future)
    await db.commit()
    # Boundary injection: retain the ORM object while the database has newer state.
    # The separate PostgreSQL suite proves real organization-lock waits.
    await db.execute(update(Period).where(Period.id == future.id).values(generation=7)
                     .execution_options(synchronize_session=False))
    assert future.generation == 5
    await close(db, book[0])
    assert future.generation == 8
    assert await db.scalar(select(Period.generation).where(Period.id == future.id)) == 8
