"""Synthetic trade-month ledger integration; not physical-stock or statutory acceptance."""
# ruff: noqa: F811
from datetime import date

from sqlalchemy import text

from core.domain.models import User
from modules.accounting.models import Account
from tests.accounting.test_bank_documents import document as bank_document
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_procurement_receipt_drafts import source_options
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401


async def test_purchase_sale_settlements_and_reports_use_one_ledger(issuance_pg, pg_book):
    api, factory = issuance_pg
    api.headers["X-User"] = "tester"
    root = f"/accounting/organizations/{pg_book[0]}"
    async with factory() as session:
        await session.execute(text("SELECT setval(pg_get_serial_sequence('accounting.account', 'id'), (SELECT max(id) FROM accounting.account))"))
        path, options = await source_options(api, session, pg_book)
        session.add(User(username="tester", full_name="Synthetic accountant", role="finance", status="active"))
        for code, category in [("90.2", "income"), ("68.2", "liability")]:
            session.add(Account(organization_id=pg_book[0], code=code, title=code, category=category,
                valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
                quantity_tracking=False, cash=False, normative_ref="Synthetic only"))
        await session.commit()
    api.headers["X-User-Roles"] = "finance"
    receipt_id = path.rsplit("/", 1)[1]
    preview = await api.post(root + f"/receipts/{receipt_id}/preview", json=options)
    assert preview.status_code == 200, preview.text
    posted = await api.post(root + f"/receipts/{receipt_id}/confirm", json={**options, "digest": preview.json()["digest"]})
    assert posted.status_code == 201, posted.text

    async def report():
        response = await api.get(root + "/reports", params={"start": "2026-09-01", "end": "2026-09-30"})
        assert response.status_code == 200, response.text
        return response.json()

    purchased = await report()
    assert purchased["pnl"]["expenses"] == "0.00"
    assert purchased["balance"]["assets"] == "100.01"
    sale = {"policy_id": pg_book[1], "posting_date": "2026-09-04", "account": "41.2",
        "warehouse": "warehouse1", "sku": "sku1", "lot": "lot1", "quantity": "1",
        "source": "synthetic-sale-month", "source_version": 1, "document_date": "2026-09-04",
        "operation_date": "2026-09-04", "expense_account": "90.4", "explanation": "Synthetic trade month sale",
        "net_amount": "100.00", "vat_rate": "20", "vat_basis": "Synthetic explicit basis",
        "buyer_account": "62", "revenue_account": "90.1", "vat_revenue_account": "90.2",
        "vat_payable_account": "68.2", "buyer_dimensions": {"counterparty": "buyer", "contract": "B1", "settlement_document": "synthetic-sale-month"}}
    preview = await api.post(root + "/sales/posting-preview", json=sale)
    assert preview.status_code == 200, preview.text
    command = {**sale, "basis_digest": preview.json()["cost"]["basis_digest"], "digest": preview.json()["digest"]}
    sold = await api.post(root + "/sales/confirm", json=command)
    assert sold.status_code == 201, sold.text
    before_cash = await report()
    assert before_cash["pnl"] == {"income": "100.00", "expenses": "50.00", "profit": "50.00"}
    for direction, amount, account, source, dimensions in [
        ("receipt", "120.00", "62", "customer-bank", sale["buyer_dimensions"]),
        ("payment", "100.01", "60", "supplier-bank", {"counterparty": "supplier1", "contract": "contract1", "settlement_document": "INV1"}),
    ]:
        bank = bank_document(direction=direction, source=source, statement_reference=source,
            policy_id=pg_book[1], posting_date="2026-09-05", operation_date="2026-09-05",
            document_date="2026-09-05", amount=amount, settlement_account=account, settlement_dimensions=dimensions)
        first = await api.post(root + "/bank/confirm", json=bank)
        assert first.status_code == 201, first.text
        assert (await api.post(root + "/bank/confirm", json=bank)).json()["id"] == first.json()["id"]
    final = await report()
    assert final["pnl"] == before_cash["pnl"]
    assert final["cashflow"]["closing"] == "19.99"
    assert final["balance"] == {"assets": "70.00", "liabilities": "20.00", "equity": "0.00", "current_result": "50.00", "difference": "0.00"}
    assert final["pending_documents"] == 0
    # Reconcile by source-document analytics, not just net account totals.
    for account, reference in [("60", "INV1"), ("62", "synthetic-sale-month")]:
        settled = [row for row in final["trial_balance"] if row["account"] == account]
        assert len(settled) == 1
        assert settled[0]["dimensions"]["settlement_document"] == reference
        assert settled[0]["closing"] == "0.00"
    stock = [row for row in final["trial_balance"] if row["account"] == "41.2"]
    assert len(stock) == 1
    assert stock[0]["dimensions"]["lot"] == "lot1"
    assert stock[0]["quantity_closing"] == "1.000001"
    assert stock[0]["closing"] == "50.01"
    assert final["statutory_certified"] is False
    assert (await api.post(root + "/sales/confirm", json=command)).json()["id"] == sold.json()["id"]
    assert await report() == final
