"""Regression for preserving an issued invoice after a new customer quote."""
from decimal import Decimal

from core.domain.models import Counterparty
from modules.sales.models import PriceQuote
from tests.test_invoice_issuance import command, create, seed


async def test_issued_invoice_stays_unchanged_after_new_customer_quote(api, session):
    ids, base = await seed(api, session)
    customer = (await session.get(Counterparty, ids["buyer"])).name
    session.add(PriceQuote(sku_code=ids["code"], counterparty=customer, price=Decimal("100")))
    await session.commit()
    deal_id = ids["deal"]
    request, _ = await command(api, ids, base)
    invoice = await create(api, ids, request)
    assert invoice.status_code == 201, invoice.text
    invoice_id = invoice.json()["document"]["id"]
    original_amount = Decimal(str(invoice.json()["document"]["amount"]))
    assert original_amount == Decimal("240.00")
    first = await api.get(f"/sales/documents/{invoice_id}/render")
    assert first.status_code == 200, first.text
    session.add(PriceQuote(sku_code=ids["code"], counterparty=customer, price=Decimal("150")))
    await session.commit()
    second = await api.get(f"/sales/documents/{invoice_id}/render")
    assert second.status_code == 200, second.text
    docs = (await api.get(f"/sales/deals/{deal_id}/documents")).json()
    doc = next(d for d in docs if d["id"] == invoice_id)
    assert Decimal(str(doc["amount"])) == original_amount
    assert "100.00" in first.text and "100.00" in second.text
    assert first.content == second.content
