"""Audit-only reproduction; no changes to the application repository."""
from decimal import Decimal

from core.domain.models import Sku
from modules.sales.models import PriceQuote


async def test_issued_invoice_changes_after_new_customer_quote(api, session):
    customer = "AUDIT synthetic customer"
    sku = Sku(code="AUDIT-SKU", title="AUDIT battery", unit="шт")
    session.add(sku)
    await session.flush()
    session.add(PriceQuote(sku_code=sku.code, counterparty=customer, price=Decimal("100")))
    await session.commit()
    deal_response = await api.post("/sales/deals", json={
        "number": "AUDIT-INV-1", "title": "Synthetic audit", "counterparty": customer,
        "amount": 200,
    })
    assert deal_response.status_code == 201, deal_response.text
    deal_id = deal_response.json()["id"]
    item = await api.post(f"/sales/deals/{deal_id}/items", json={"sku_id": sku.id, "qty": 2})
    assert item.status_code == 201, item.text
    invoice = await api.post(f"/sales/deals/{deal_id}/documents", json={"kind": "invoice"})
    assert invoice.status_code == 201, invoice.text
    invoice_id = invoice.json()["id"]
    original_amount = Decimal(str(invoice.json()["amount"]))
    first = await api.get(f"/sales/documents/{invoice_id}/render")
    assert first.status_code == 200, first.text
    session.add(PriceQuote(sku_code=sku.code, counterparty=customer, price=Decimal("150")))
    await session.commit()
    second = await api.get(f"/sales/documents/{invoice_id}/render")
    assert second.status_code == 200, second.text
    docs = (await api.get(f"/sales/deals/{deal_id}/documents")).json()
    doc = next(d for d in docs if d["id"] == invoice_id)
    assert Decimal(str(doc["amount"])) == original_amount
    assert "100.00" in first.text and "100.00" in second.text
    assert first.content == second.content
