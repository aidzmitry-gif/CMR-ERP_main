from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from core.domain.models import Counterparty, Sku
from modules.accounting import models, sales, service
from modules.accounting.schemas import PostingInput
from tests.accounting.test_inventory_cost import move, request


async def setup_sale(db, book, posting, **changes):
    await move(db, book, posting, "receipt", "3", "10.00")
    db.add(Sku(code="SKU", title="Synthetic accounting item", unit="шт", is_active=True))
    for code, category in [("90.2", changes.pop("vat_category", "income")), ("68.2", "liability")]:
        db.add(models.Account(organization_id=book[0], code=code, title=code, category=category,
                              valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
                              quantity_tracking=False, cash=False, normative_ref="synthetic"))
    await db.commit()
    sku = await db.scalar(select(Sku).where(Sku.code == "SKU"))
    return {**request(book), "source": "sale-1", "source_version": 1,
            "document_date": "2026-09-01", "operation_date": "2026-09-01",
            "expense_account": "90.4", "explanation": "Synthetic sale preview",
            "net_amount": "20.00", "vat_rate": "20", "vat_basis": "Synthetic accountant-approved basis",
            "buyer_account": "62", "revenue_account": "90.1", "vat_revenue_account": "90.2", "vat_payable_account": "68.2",
            "buyer_dimensions": {"counterparty_id": "1", "counterparty": "supplier1",
                                 "counterparty_unp": "190000001", "counterparty_revision": "1",
                                 "contract": "contract", "settlement_document": "sale-1"},
            "sku_identity": {"id": sku.id, "code": sku.code, "title": sku.title, "unit": sku.unit},
            **changes}


async def test_sale_preview_balanced_net_income_cost_and_no_writes(client, db, book, posting):
    data = await setup_sale(db, book, posting)
    response = await client.post(f"/accounting/organizations/{book[0]}/sales/posting-preview", json=data)
    assert response.status_code == 200, response.text
    result = response.json()
    assert (result["net_amount_byn"], result["vat_amount_byn"], result["gross_amount_byn"]) == ("20.00", "4.00", "24.00")
    lines = result["posting"]["lines"]
    assert [(x["account"], x["side"], x["amount"]) for x in lines] == [
        ("62", "debit", "24.00"), ("90.1", "credit", "24.00"), ("90.2", "debit", "4.00"),
        ("68.2", "credit", "4.00"), ("90.4", "debit", "3.33"), ("41.2", "credit", "3.33")]
    assert lines[-1]["quantity"] == "1" and lines[-1]["dimensions"]["lot"] == "lot1"
    assert sum(Decimal(x["amount"]) * (1 if x["side"] == "debit" else -1) for x in lines) == 0
    assert not result["posted"] and not result["vat_treatment_verified"]
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == 1
    with pytest.raises(service.AccountingError, match="dedicated"):
        await service.post(db, book[0], PostingInput(**result["posting"]), "tester")
    assert (await client.post("/accounting/organizations/999/sales/posting-preview", json=data)).status_code == 403


async def test_sale_omits_optional_empty_buyer_unp_from_ledger(client, db, book, posting):
    data = await setup_sale(db, book, posting)
    buyer = Counterparty(name="Buyer without UNP")
    db.add(buyer)
    await db.flush()
    data["buyer_dimensions"].update({
        "counterparty_id": str(buyer.id), "counterparty": buyer.legal_name or buyer.name,
        "counterparty_unp": buyer.unp or "", "counterparty_revision": str(buyer.revision),
    })
    await db.commit()
    base = f"/accounting/organizations/{book[0]}/sales"
    response = await client.post(base + "/posting-preview", json=data)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["posting"]["lines"][0]["dimensions"]["counterparty_id"] == str(buyer.id)
    assert "counterparty_unp" not in preview["posting"]["lines"][0]["dimensions"]
    assert data["buyer_dimensions"]["counterparty_unp"] == ""
    assert (await client.post("/accounting/organizations/999/sales/posting-preview", json=data)).status_code == 403
    payload = {**data, "basis_digest": preview["cost"]["basis_digest"], "digest": preview["digest"]}
    first = await client.post(base + "/confirm", json=payload)
    repeated = await client.post(base + "/confirm", json=payload)
    assert first.status_code == repeated.status_code == 201
    assert repeated.json()["id"] == first.json()["id"]
    saved = await db.get(models.InventorySaleReceipt, first.json()["id"])
    assert saved.command["buyer_dimensions"]["counterparty_unp"] == ""
    assert "counterparty_unp" not in saved.posting["lines"][0]["dimensions"]
    assert await db.scalar(select(func.count()).select_from(models.InventorySaleReceipt)) == 1


async def test_sale_buyer_must_be_current_directory_record_and_replay_preserves_history(client, db, book, posting):
    data = await setup_sale(db, book, posting)
    base = f"/accounting/organizations/{book[0]}/sales"
    assert (await client.get(base + "/buyers")).json()["items"] == []
    options = await client.get(base + "/buyers?q=supplier1")
    assert options.status_code == 200
    assert options.json()["items"] == [{"id": 1, "name": "supplier1", "unp": "190000001", "revision": 1}]
    assert (await client.get("/accounting/organizations/999/sales/buyers?q=supplier1")).status_code == 403
    free_text = {**data, "buyer_dimensions": {"counterparty": "supplier1",
        "contract": "contract", "settlement_document": "sale-1"}}
    assert (await client.post(base + "/posting-preview", json=free_text)).status_code == 422
    forged = {**data, "buyer_dimensions": {**data["buyer_dimensions"], "counterparty": "Forged"}}
    assert (await client.post(base + "/posting-preview", json=forged)).status_code == 422
    preview = (await client.post(base + "/posting-preview", json=data)).json()
    payload = {**data, "basis_digest": preview["cost"]["basis_digest"], "digest": preview["digest"]}
    first = await client.post(base + "/confirm", json=payload)
    assert first.status_code == 201, first.text
    buyer = await db.get(Counterparty, 1)
    buyer.legal_name = "Renamed buyer"
    await db.commit()
    assert (await client.post(base + "/posting-preview", json=data)).status_code == 422
    repeated = await client.post(base + "/confirm", json=payload)
    assert repeated.status_code == 201 and repeated.json()["id"] == first.json()["id"]
    assert await db.scalar(select(func.count()).select_from(models.InventorySaleReceipt)) == 1


async def test_sale_confirmation_rechecks_buyer_after_preview(client, db, book, posting):
    data = await setup_sale(db, book, posting)
    base = f"/accounting/organizations/{book[0]}/sales"
    preview = (await client.post(base + "/posting-preview", json=data)).json()
    buyer = await db.get(Counterparty, 1)
    buyer.legal_name = "Current legal name"
    await db.commit()
    await db.refresh(buyer)
    buyer_revision = buyer.revision
    stale = await client.post(base + "/confirm", json={**data,
        "basis_digest": preview["cost"]["basis_digest"], "digest": preview["digest"]})
    assert stale.status_code == 422, stale.text
    assert await db.scalar(select(func.count()).select_from(models.InventorySaleReceipt)) == 0
    current = {**data, "buyer_dimensions": {**data["buyer_dimensions"],
        "counterparty": "Current legal name", "counterparty_revision": str(buyer_revision)}}
    assert (await client.post(base + "/posting-preview", json=current)).status_code == 200


async def test_accountant_sale_requires_current_sku_snapshot(client, db, book, posting):
    data = await setup_sale(db, book, posting)
    base = f"/accounting/organizations/{book[0]}"
    options = await client.get(base + "/inventory/skus?q=SKU")
    assert options.status_code == 200
    assert options.json()["items"] == [data["sku_identity"]]
    assert (await client.get("/accounting/organizations/999/inventory/skus?q=SKU")).status_code == 403
    missing = {key: value for key, value in data.items() if key != "sku_identity"}
    assert (await client.post(base + "/sales/posting-preview", json=missing)).status_code == 422
    forged = {**data, "sku_identity": {**data["sku_identity"], "title": "Forged"}}
    assert (await client.post(base + "/sales/posting-preview", json=forged)).status_code == 422
    preview = (await client.post(base + "/sales/posting-preview", json=data)).json()
    sku = await db.get(Sku, data["sku_identity"]["id"])
    sku.title = "Renamed item"
    await db.commit()
    stale = await client.post(base + "/sales/confirm", json={**data,
        "basis_digest": preview["cost"]["basis_digest"], "digest": preview["digest"]})
    assert stale.status_code == 422
    assert await db.scalar(select(func.count()).select_from(models.InventorySaleReceipt)) == 0


async def test_new_manual_sale_cannot_claim_crm_invoice_or_shipment_source(client, db, book, posting):
    data = await setup_sale(db, book, posting)
    base = f"/accounting/organizations/{book[0]}/sales/posting-preview"
    for reference in ("sales:document:27", "sales:document:027", " sales:document: 27 ",
                      "SALES:DOCUMENT:27", f"wms:physical-shipment:{book[0]}:some-key"):
        linked = {**data, "buyer_dimensions": {**data["buyer_dimensions"],
            "settlement_document": reference}}
        response = await client.post(base, json=linked)
        assert response.status_code == 422 and "physical shipment" in response.text
    for source in ("sales:document:27", "sales:document:027", " SALES:DOCUMENT:27 ",
                   f"wms:physical-shipment:{book[0]}:some-key"):
        response = await client.post(base, json={**data, "source": source})
        assert response.status_code == 422 and "physical shipment" in response.text
    assert await db.scalar(select(func.count()).select_from(models.InventorySaleReceipt)) == 0


async def test_historical_crm_linked_manual_sale_exact_replay_remains_available(client, db, book, posting):
    data = await setup_sale(db, book, posting)
    old = {**data, "buyer_dimensions": {**data["buyer_dimensions"],
        "settlement_document": "sales:document:27"}}
    document = sales.SaleDocument.model_validate(old)
    prepared = await sales.prepare(db, book[0], document)
    first = await sales.confirm(db, book[0], document, prepared["cost"]["basis_digest"],
                                prepared["digest"], "tester")
    await db.commit()
    repeated = await client.post(f"/accounting/organizations/{book[0]}/sales/confirm", json={**old,
        "basis_digest": prepared["cost"]["basis_digest"], "digest": prepared["digest"]})
    assert repeated.status_code == 201 and repeated.json()["id"] == first.id


async def test_historical_sale_without_sku_id_replays_after_catalog_change(client, db, book, posting):
    data = await setup_sale(db, book, posting)
    old = {key: value for key, value in data.items() if key != "sku_identity"}
    document = sales.SaleDocument.model_validate(old)
    prepared = await sales.prepare(db, book[0], document)
    entry = await sales.confirm(db, book[0], document, prepared["cost"]["basis_digest"],
                                prepared["digest"], "tester")
    sku = await db.get(Sku, data["sku_identity"]["id"])
    sku.title = "Renamed item"
    await db.commit()
    repeated = await client.post(f"/accounting/organizations/{book[0]}/sales/confirm", json={**old,
        "basis_digest": prepared["cost"]["basis_digest"], "digest": prepared["digest"]})
    assert repeated.status_code == 201 and repeated.json()["id"] == entry.id
    assert await db.scalar(select(func.count()).select_from(models.InventorySaleReceipt)) == 1


@pytest.mark.parametrize(("method", "expected_cost", "expected_lines"), [
    ("fifo", "50.00", [("old", "30.00"), ("new", "20.00")]),
    ("weighted_average", "56.00", [("old", "42.00"), ("new", "14.00")]),
])
async def test_sale_preview_preserves_policy_selected_inventory_layers(client, db, book, posting,
                                                                         method, expected_cost, expected_lines):
    policy = models.Policy(organization_id=book[0], effective_from=date(2026, 2, 1), reference=f"Synthetic {method} sale",
                           inventory_method=method, allocation_basis="direct_cost", depreciation_method="straight_line",
                           normative_reference="Synthetic", normative_verified=False, approved_by="tester")
    db.add(policy)
    await db.commit()
    book = (book[0], policy.id)
    await move(db, book, posting, "old-receipt", "3", "30.00", day="2026-09-01", lot="old")
    await move(db, book, posting, "new-receipt", "2", "40.00", day="2026-09-02", lot="new")
    db.add(Sku(code="SKU", title="Synthetic accounting item", unit="шт", is_active=True))
    await db.commit()
    sku = await db.scalar(select(Sku).where(Sku.code == "SKU"))
    data = {**request(book, lot="", quantity="4", posting_date="2026-09-03"),
            "source": f"{method}-sale", "source_version": 1,
            "document_date": "2026-09-03", "operation_date": "2026-09-03",
            "expense_account": "90.4", "explanation": "Synthetic layered sale",
            "net_amount": "80.00", "vat_rate": "0", "vat_basis": "Synthetic explicit zero VAT basis",
            "buyer_account": "62", "revenue_account": "90.1", "vat_revenue_account": "90.2",
            "vat_payable_account": "68.2",
            "buyer_dimensions": {"counterparty_id": "1", "counterparty": "supplier1",
                                 "counterparty_unp": "190000001", "counterparty_revision": "1",
                                 "contract": "contract", "settlement_document": method},
            "sku_identity": {"id": sku.id, "code": sku.code, "title": sku.title, "unit": sku.unit}}
    response = await client.post(f"/accounting/organizations/{book[0]}/sales/posting-preview", json=data)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["cost"]["method"] == method and result["cost"]["issue_cost_byn"] == expected_cost
    credits = [(line["dimensions"]["lot"], line["amount"]) for line in result["posting"]["lines"]
               if line["account"] == "41.2" and line["side"] == "credit"]
    assert credits == expected_lines


@pytest.mark.parametrize("changes", [{"vat_category": "expense"}, {"buyer_dimensions": {}},
                                     {"net_amount": "0"}, {"vat_basis": " "},
                                     {"vat_dimensions": {"vat_rate": "10"}}, {"account": "10"},
                                     {"vat_rate": "NaN"}, {"vat_rate": 20.1}])
async def test_sale_rejects_ambiguous_or_invalid_inputs(client, db, book, posting, changes):
    data = await setup_sale(db, book, posting, **changes)
    response = await client.post(f"/accounting/organizations/{book[0]}/sales/posting-preview", json=data)
    assert response.status_code == 422, response.text
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == 1


async def test_zero_rate_is_explicit_not_eligibility_inference(client, db, book, posting):
    data = await setup_sale(db, book, posting, vat_rate="0")
    response = await client.post(f"/accounting/organizations/{book[0]}/sales/posting-preview", json=data)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["vat_amount_byn"] == "0.00" and len(result["posting"]["lines"]) == 4
    assert not result["vat_treatment_verified"]
    first = result["digest"]
    data["vat_basis"] = "Different explicit basis"
    other = await client.post(f"/accounting/organizations/{book[0]}/sales/posting-preview", json=data)
    assert other.json()["digest"] != first


async def test_sale_confirmation_single_entry_replay_and_changed_payload(client, db, book, posting):
    data = await setup_sale(db, book, posting, quantity="3")
    base = f"/accounting/organizations/{book[0]}/sales"
    preview = (await client.post(base + "/posting-preview", json=data)).json()
    payload = {**data, "basis_digest": preview["cost"]["basis_digest"], "digest": preview["digest"]}
    first = await client.post(base + "/confirm", json=payload)
    assert first.status_code == 201, first.text
    repeated = await client.post(base + "/confirm", json=payload)
    assert repeated.status_code == 201 and repeated.json()["id"] == first.json()["id"]
    lines = (await db.scalars(select(models.Line).where(models.Line.entry_id == first.json()["id"])) ).all()
    assert len(lines) == 6
    assert sum(x.amount * (1 if x.side == "debit" else -1) for x in lines) == 0
    assert next(x for x in lines if x.account_code == "41.2").quantity == Decimal("3")
    assert (await client.post(base + "/confirm", json={**payload, "vat_basis": "Changed basis"})).status_code == 422
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == 2


@pytest.mark.parametrize("rate,net", [("0", "20.00"), ("20", "0.01")])
async def test_confirm_preserves_readable_zero_tax_basis(client, db, book, posting, rate, net):
    data = await setup_sale(db, book, posting, vat_rate=rate, net_amount=net)
    base = f"/accounting/organizations/{book[0]}"
    preview = (await client.post(base + "/sales/posting-preview", json=data)).json()
    result = await client.post(base + "/sales/confirm", json={**data, "basis_digest": preview["cost"]["basis_digest"], "digest": preview["digest"]})
    assert result.status_code == 201, result.text
    entry = await client.get(base + f"/entries/{result.json()['id']}")
    assert entry.status_code == 200, entry.text
    revenue = next(line for line in entry.json()["lines"] if line["account_code"] == "90.1")
    assert revenue["dimensions"]["vat_rate"] == rate
    assert revenue["dimensions"]["vat_basis"] == data["vat_basis"]


@pytest.mark.parametrize("change", ["basis", "amount", "digest", "commit"])
async def test_sale_stale_or_failed_confirm_leaves_no_partial_package(client, db, book, posting, monkeypatch, change):
    from sqlalchemy.exc import IntegrityError

    data = await setup_sale(db, book, posting)
    base = f"/accounting/organizations/{book[0]}/sales"
    preview = (await client.post(base + "/posting-preview", json=data)).json()
    payload = {**data, "basis_digest": preview["cost"]["basis_digest"], "digest": preview["digest"]}
    expected = 1
    if change == "basis":
        await move(db, book, posting, "receipt2", "3", "10.00")
        expected = 2
    elif change == "amount":
        payload["net_amount"] = "21.00"
    elif change == "digest":
        payload["digest"] = "0" * 64
    else:
        async def fail():
            raise IntegrityError("Synthetic failure", None, Exception("test"))
        monkeypatch.setattr(db, "commit", fail)
    response = await client.post(base + "/confirm", json=payload)
    assert response.status_code == (409 if change == "commit" else 422), response.text
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == expected
    assert await db.scalar(select(func.count()).select_from(models.Line)) == expected * 2
    assert await db.scalar(select(func.count()).select_from(models.InventorySaleReceipt)) == 0


@pytest.mark.parametrize("field", ["cost", "command", "actor"])
async def test_sale_receipt_verification_rejects_changed_evidence(db, book, posting, monkeypatch, field):
    from types import SimpleNamespace

    data = sales.SaleDocument.model_validate(await setup_sale(db, book, posting))
    prepared = await sales.prepare(db, book[0], data)
    entry = await sales.confirm(db, book[0], data, prepared["cost"]["basis_digest"], prepared["digest"], "tester")
    await db.commit()
    verified = await sales.verify_receipt(db, book[0], entry.id)
    assert service.digest(verified) == prepared["digest"]
    saved = await db.get(models.InventorySaleReceipt, entry.id)
    changed = SimpleNamespace(**{name: getattr(saved, name) for name in ("organization_id", "command", "cost", "posting", "digest", "actor")})
    if field == "cost":
        changed.cost = {**saved.cost, "issue_cost_byn": "999.99"}
    elif field == "command":
        changed.command = {**saved.command, "net_amount": "999.99"}
    else:
        changed.actor = "other"
    original_get = db.get
    async def substituted(model, identity, *args, **kwargs):
        if model is models.InventorySaleReceipt and identity == entry.id:
            return changed
        return await original_get(model, identity, *args, **kwargs)
    monkeypatch.setattr(db, "get", substituted)
    with pytest.raises(service.AccountingError, match="source, calculation or ledger package changed"):
        await sales.verify_receipt(db, book[0], entry.id)
    with pytest.raises(service.AccountingError, match="source, calculation or ledger package changed"):
        await sales.confirm(db, book[0], data, prepared["cost"]["basis_digest"], prepared["digest"], "tester")
