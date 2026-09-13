from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from core.services.auth import CurrentUser, get_current_user
from modules.accounting import reports, service
from modules.accounting.models import Account, Entry, Line, Organization
from modules.accounting.schemas import CloseInput, LineInput


async def test_closed_month_purchase_sale_payment(db, book, posting):
    org, _ = book
    await service.post(db, org, posting("opening", "51", "80", "1000.00", opening=True), "tester")
    await service.post(db, org, posting("purchase"), "tester")
    await service.post(db, org, posting("sale", "62", "90.1", "180.00"), "tester")
    await service.post(db, org, posting("cost", "90.4", "41"), "tester")
    await service.post(db, org, posting("receipt", "51", "62", "180.00"), "tester")
    await service.post(db, org, posting("payment", "60", "51"), "tester")
    result = await reports.report(db, org, date(2026, 9, 1), date(2026, 9, 30))
    assert result["pnl"]["profit"] == "80.00"
    assert result["balance"] == dict(assets="1080.00", liabilities="0.00", equity="1000.00",
                                    current_result="80.00", difference="0.00")
    assert result["cashflow"]["opening"] == "1000.00"
    assert result["cashflow"]["closing"] == "1080.00"
    assert result["status"] == "preliminary"
    assert all(m["currency"] == "BYN" for m in result["movements"])
    assert len({m["line_id"] for m in result["movements"]}) == len(result["movements"])
    await service.close_period(db, org, "2026-09", CloseInput(
        expected_generation=6, evidence={step: "synthetic checked" for step in service.CLOSE_STEPS}
    ), "tester")
    await db.commit()
    assert (await reports.report(db, org, date(2026, 9, 1), date(2026, 9, 30)))["status"] == "closed_periods"
    with pytest.raises(service.AccountingError, match="Reopen"):
        await service.post(db, org, posting("late"), "tester")


async def test_replay_and_conflict(db, book, posting):
    item = posting()
    first = await service.post(db, book[0], item, "tester")
    replay = await service.post(db, book[0], item, "tester")
    assert first.id == replay.id
    assert await db.scalar(select(func.count()).select_from(Entry)) == 1
    with pytest.raises(service.AccountingError, match="different content"):
        await service.post(db, book[0], posting(amount="101.00"), "tester")


@pytest.mark.parametrize("amount", [1.5, True, None, "NaN", "Infinity", "oops", "1.001", "-1"])
def test_bad_money_fails_closed(amount):
    with pytest.raises(ValidationError):
        LineInput(account="51", side="debit", amount=amount)


def test_fx_exact_rate_and_scale():
    data = dict(account="52", side="debit", amount="3.50", currency="RUB",
                original_amount="100.00", rate="3.5", rate_scale=100,
                rate_date="2026-09-01", rate_source="synthetic rate")
    assert LineInput(**data).amount == Decimal("3.50")
    with pytest.raises(ValidationError, match="does not match"):
        LineInput(**{**data, "amount": "3.85"})
    with pytest.raises(ValidationError, match="needs"):
        LineInput(**{**data, "rate_source": None})


async def test_unbalanced_and_missing_analytics(db, book, posting):
    bad = posting().model_dump(mode="json")
    bad["lines"][1]["amount"] = "99.99"
    with pytest.raises(service.AccountingError, match="balance"):
        await service.post(db, book[0], posting(**bad), "tester")
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0


async def test_api_org_isolation_and_read_only(client, db, book, posting):
    other = Organization(name="Other", unp="888888888")
    db.add(other)
    await db.commit()
    prefix = f"/accounting/organizations/{other.id}"
    assert (await client.get(prefix + "/accounts?on=2026-09-01")).status_code == 403
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("stranger", ["director"])
    assert (await client.get(f"/accounting/organizations/{book[0]}/reports?start=2026-09-01&end=2026-09-30")).status_code == 403


async def test_api_decimal_strings_and_detail(client, book, posting):
    prefix = f"/accounting/organizations/{book[0]}"
    response = await client.post(prefix + "/entries", json=posting().model_dump(mode="json"))
    assert response.status_code == 201, response.text
    detail = await client.get(prefix + f"/entries/{response.json()['id']}")
    assert detail.json()["lines"][0]["amount"] == "100.00"


async def test_history_immutable(db, book, posting):
    entry = await service.post(db, book[0], posting(), "tester")
    await db.commit()
    entry.explanation = "edited"
    with pytest.raises(ValueError, match="immutable"):
        await db.flush()
    await db.rollback()


async def test_pending_late_source_invalidates_close(db, book, posting):
    await service.post(db, book[0], posting(), "tester")
    await service.close_period(db, book[0], "2026-09", CloseInput(
        expected_generation=1, evidence={k: "checked" for k in service.CLOSE_STEPS}), "tester")
    await db.commit()
    await service.receive(db, book[0], "late-event", "2026-09", posting("late").model_dump(mode="json"))
    await db.commit()
    result = await reports.report(db, book[0], date(2026, 9, 1), date(2026, 9, 30))
    assert result["status"] == "preliminary"
    assert result["pending_documents"] == 1


async def test_opening_import_atomic(client, db, book, posting, opening_package):
    first = posting("opening", "51", "80", opening=True)
    second = posting("bad-opening", "999", "80", opening=True)
    response = await client.post(f"/accounting/organizations/{book[0]}/imports/confirm",
                                 json=opening_package([first, second], batch="test"))
    assert response.status_code == 422
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0


async def test_snapshot_and_as_of_ignore_future(db, book, posting):
    await service.post(db, book[0], posting(), "tester")
    await service.post(db, book[0], posting("future", posting_date="2026-10-01"), "tester")
    db.add(Account(organization_id=book[0], code="41", title="New title", category="asset",
                   valid_from=date(2026, 11, 1), required_dimensions=[], currency_tracking=False,
                   quantity_tracking=False, cash=False, normative_ref="test"))
    await db.flush()
    result = await reports.report(db, book[0], date(2026, 9, 1), date(2026, 9, 30))
    stock = next(x for x in result["trial_balance"] if x["account"] == "41")
    assert stock["title"] == "Товары"
    assert stock["closing"] == "100.00"


async def test_off_balance_does_not_affect_equity(db, book, posting):
    item = posting(lines=[dict(account="003", side="debit", amount="100.00")])
    await service.post(db, book[0], item, "tester")
    result = await reports.report(db, book[0], date(2026, 9, 1), date(2026, 9, 30))
    assert result["balance"]["assets"] == "0.00"
    assert result["balance"]["difference"] == "0.00"
    assert await db.scalar(select(func.count()).select_from(Line)) == 1

async def test_opening_drilldown_reconciles_boundary_and_later_import(db, book, posting):
    await service.post(db, book[0], posting("initial", "41", "80", "100.00", opening=True), "tester")
    await service.post(db, book[0], posting("purchase", "41", "60", "30.00", posting_date="2026-09-02"), "tester")
    for start in [date(2026, 8, 31), date(2026, 9, 1), date(2026, 9, 3)]:
        result = await reports.report(db, book[0], start, date(2026, 9, 30))
        opening_ids = {m["line_id"] for m in result["opening_movements"]}
        assert not opening_ids.intersection(m["line_id"] for m in result["movements"])
        for row in result["trial_balance"]:
            opening = sum((Decimal(m["amount"]) * (1 if m["side"] == "debit" else -1) for m in result["opening_movements"] if m["account"] == row["account"]), Decimal("0"))
            assert opening == Decimal(row["opening"])
            for side in ["debit", "credit"]:
                turnover = sum((Decimal(m["amount"]) for m in result["movements"] if m["account"] == row["account"] and m["side"] == side), Decimal("0"))
                assert turnover == Decimal(row[side])
