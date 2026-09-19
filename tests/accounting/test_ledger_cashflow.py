from datetime import date

from sqlalchemy import update

from modules.accounting import reports, service
from modules.accounting.models import Line


async def test_ledger_cashflow_keeps_opening_out_of_gross_and_reviews_unresolved(db, book, posting):
    await service.post(db, book[0], posting("opening", "51", "80", "50.00", opening=True), "tester")
    await service.post(db, book[0], posting("receipt", "51", "62", "100.00"), "tester")
    await service.post(db, book[0], posting("payment", "60", "51", "40.00", lines=[
        {"account": "60", "side": "debit", "amount": "40.00"},
        {"account": "51", "side": "credit", "amount": "40.00", "cash_activity": "financing"},
    ]), "tester")
    await service.post(db, book[0], posting("internal", "51", "60", "30.00", lines=[
        {"account": "51", "side": "debit", "amount": "30.00", "cash_activity": "internal"},
        {"account": "60", "side": "credit", "amount": "30.00"},
    ]), "tester")
    unclassified_in = await service.post(db, book[0], posting("unknown-in", "51", "62", "100.00"), "tester")
    unclassified_out = await service.post(db, book[0], posting("unknown-out", "60", "51", "100.00"), "tester")
    await db.execute(update(Line).where(Line.entry_id.in_([unclassified_in.id, unclassified_out.id]), Line.cash.is_(True)).values(cash_activity=None))
    result = await reports.report(db, book[0], date(2026, 9, 1), date(2026, 9, 30))
    summary = result["cashflow_ledger"]
    assert summary == {
        "opening": "50.00", "external_inflow": "100.00", "external_outflow": "40.00", "external_net": "60.00",
        "internal_net": "30.00", "internal_count": 1, "unclassified_inflow": "100.00", "unclassified_outflow": "100.00",
        "unclassified_net": "0.00", "unclassified_count": 2, "opening_adjustment_net": "0.00", "opening_adjustment_count": 0,
        "closing": "140.00", "activities": {"operating": {"inflow": "100.00", "outflow": "0.00", "net": "100.00"},
            "investing": {"inflow": "0.00", "outflow": "0.00", "net": "0.00"}, "financing": {"inflow": "0.00", "outflow": "40.00", "net": "-40.00"}},
    }
    assert {row["source"] for row in result["cash_movements"]} == {"receipt", "payment", "internal", "unknown-in", "unknown-out"}
    assert all(row["source"] != "opening" for row in result["cash_movements"])
    assert summary["opening"] != summary["external_inflow"]
    wider = await reports.report(db, book[0], date(2026, 8, 1), date(2026, 9, 30))
    assert wider["cashflow_ledger"]["opening"] == "0.00"
    assert wider["cashflow_ledger"]["opening_adjustment_net"] == "50.00"
    assert wider["cashflow_ledger"]["opening_adjustment_count"] == 1
    assert wider["cashflow_ledger"]["closing"] == "140.00"
    assert all(row["source"] != "opening" for row in wider["cash_movements"])
