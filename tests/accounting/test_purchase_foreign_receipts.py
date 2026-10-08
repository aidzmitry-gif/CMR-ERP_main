"""Native FX receipts: historical identities, exact valuation and source lifecycle."""
from copy import deepcopy
from datetime import date
from decimal import Decimal, localcontext

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select

from core.services.auth import CurrentUser, get_current_user
from modules.accounting import models, purchases, service
from modules.procurement.receipt_documents import (
    ReceiptConfirm,
    ReceiptContent,
    ReceiptPosting,
    classify_receipt_correction,
)
from tests.accounting.test_procurement_receipt_drafts import document
from tests.accounting.test_purchase_documents import purchase


def exchange():
    return {"currency": "USD", "rate": "2.5", "rate_scale": 1, "rate_date": "2026-09-02",
            "rate_source": "SYNTHETIC quote only", "valuation_basis": "SYNTHETIC policy only"}


def foreign_purchase():
    data = purchase((1, 1))
    data["foreign_exchange"] = exchange()
    for item, net, vat in zip(data["items"], ("40.00", "20.00"), ("8.00", "2.00"), strict=True):
        item["foreign_amounts"] = {"net_amount": net, "vat_amount": vat}
    return data


def foreign_source():
    facts = document()
    facts["foreign_exchange"] = exchange()
    facts["items"][0].update(net_amount="100.00", vat_amount="20.00",
                             quantity="2.00",
                             foreign_amounts={"net_amount": "40.00", "vat_amount": "8.00"})
    return facts


def test_historical_byn_json_and_v1_v2_digests_are_unchanged():
    original = purchase((1, 1))
    data = purchases.PurchaseDocument.model_validate(original)
    assert data.model_dump(mode="json")["items"] == [
        {"order_id": None, "unit": None, **item} for item in original["items"]]
    assert "foreign_exchange" not in data.model_dump(mode="json")
    receipt = ReceiptContent.model_validate(document()).model_dump(mode="json")
    assert "foreign_exchange" not in receipt
    assert "foreign_amounts" not in receipt["items"][0]
    assert receipt["supplier_id"] == 1 and receipt["items"][0]["order_id"] is None
    assert service.digest(data.posting()) == "d91eba91b0cd24f6224337a3d62ad16468f9c61961a332318e182032eef906cf"
    assert service.digest(data.posting(verified_counterparty_id=7)) == "d52b81b9b74a008785212e82cc74bd76d9b3df45e19fd070def731bae9de6ba7"


@pytest.mark.parametrize("scale,rate", [(1, "2.5"), (100, "250")])
def test_exact_fx_only_supplier_has_foreign_metadata(scale, rate):
    data = foreign_purchase()
    data["foreign_exchange"].update(rate_scale=scale, rate=rate)
    parsed = purchases.PurchaseDocument.model_validate(data)
    posting = parsed.posting(verified_counterparty_id=7)
    assert posting.rule_version == "purchase-fx-v2"
    assert [line.amount for line in posting.lines] == list(map(Decimal, ["100", "20", "50", "5", "175"]))
    assert all(line.currency == "BYN" and line.original_amount is None for line in posting.lines[:-1])
    supplier = posting.lines[-1]
    assert (supplier.currency, supplier.original_amount, supplier.rate_scale) == ("USD", Decimal("70"), scale)
    assert supplier.dimensions["fx_valuation_basis"] == exchange()["valuation_basis"]
    basis = {"document": parsed.model_dump(mode="json"), "verified_counterparty_id": 7}
    rebuilt, replay = purchases.purchase_from_receipt_basis(basis)
    assert rebuilt.foreign_exchange == parsed.foreign_exchange
    assert service.digest(replay) == service.digest(posting)
    basis["document"]["foreign_exchange"]["valuation_basis"] = "OTHER synthetic policy"
    assert service.digest(purchases.purchase_from_receipt_basis(basis)[1]) != service.digest(posting)


def test_fx_arithmetic_does_not_depend_on_decimal_precision():
    data = foreign_purchase()
    with localcontext() as context:
        context.prec = 2
        parsed = purchases.PurchaseDocument.model_validate(data)
        assert parsed.posting().lines[-1].amount == Decimal("175.00")


def test_half_cent_and_total_divergence_are_explicit():
    data = foreign_purchase()
    item = {**data["items"][0], "net_amount": "0.03", "vat_rate": "0", "vat_amount": "0",
            "foreign_amounts": {"net_amount": "0.01", "vat_amount": "0"}}
    data.update(items=[item], vat_account=None)
    assert purchases.PurchaseDocument.model_validate(data).posting().lines[-1].amount == Decimal("0.03")
    data["items"].append(deepcopy(item))
    with pytest.raises(ValueError, match="documented exchange rate"):
        purchases.PurchaseDocument.model_validate(data)


@pytest.mark.parametrize("field", list(exchange()))
def test_missing_fx_metadata_cannot_be_defaulted(field):
    data = foreign_purchase()
    del data["foreign_exchange"][field]
    with pytest.raises(ValueError):
        purchases.PurchaseDocument.model_validate(data)


@pytest.mark.parametrize("field,value", [("currency", "BYN"), ("currency", "usd"),
    ("rate", True), ("rate", 2.5), ("rate", "0"), ("rate", "NaN"), ("rate", "2.5000001"),
    ("rate_scale", True), ("rate_scale", "1"), ("rate_scale", 0), ("rate_scale", 2147483648),
    ("rate_source", " "), ("valuation_basis", " "), ("rate_date", None)])
def test_invalid_fx_metadata_refuses_before_posting(field, value):
    data = foreign_purchase()
    data["foreign_exchange"][field] = value
    with pytest.raises(ValueError):
        purchases.PurchaseDocument.model_validate(data)


@pytest.mark.parametrize("mutation", ["missing_original", "orphan_original", "wrong_byn", "wrong_original_vat"])
def test_source_pairs_and_converted_components_are_required(mutation):
    data = foreign_purchase()
    if mutation == "missing_original":
        del data["items"][0]["foreign_amounts"]
    elif mutation == "orphan_original":
        del data["foreign_exchange"]
    elif mutation == "wrong_byn":
        data["items"][0]["net_amount"] = "100.01"
    else:
        data["items"][0]["foreign_amounts"]["vat_amount"] = "7.99"
    with pytest.raises(ValueError):
        purchases.PurchaseDocument.model_validate(data)


@pytest.mark.parametrize("field,value", [("rate", "2.6"), ("rate_scale", 2), ("currency", "RUB"),
    ("rate_date", "2026-09-01"), ("rate_source", "Other source"), ("valuation_basis", "Other basis")])
def test_all_exchange_corrections_are_primary_changes(field, value):
    facts = foreign_source()
    changed = deepcopy(facts)
    changed["foreign_exchange"][field] = value
    flags, classification = classify_receipt_correction(
        ReceiptContent.model_validate(facts), ReceiptContent.model_validate(changed))
    assert flags["primary_document_change"]
    assert not flags["no_difference"] and not flags["explanation_only"]
    assert classification == ["primary_document_change"]


@pytest.mark.parametrize("field,flag", [("net_amount", "inventory_value_change"), ("vat_amount", "vat_change")])
def test_original_amount_change_is_not_hidden_by_identical_byn(field, flag):
    facts = foreign_source()
    changed = deepcopy(facts)
    changed["items"][0]["foreign_amounts"][field] = "40.01" if field == "net_amount" else "8.01"
    flags, _ = classify_receipt_correction(ReceiptContent.model_validate(facts), ReceiptContent.model_validate(changed))
    assert flags["primary_document_change"] and not flags["no_difference"]
    assert flags[flag]


@pytest_asyncio.fixture
async def foreign_book(db, book):
    db.add(models.Account(organization_id=book[0], code="41.1", title="Synthetic owned goods", category="asset",
                          valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
                          quantity_tracking=True, cash=False, normative_ref="Synthetic only"))
    db.add(models.Account(organization_id=book[0], code="18", title="Synthetic input VAT", category="asset",
                          valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
                          quantity_tracking=False, cash=False, normative_ref="Synthetic only"))
    db.add(models.Account(organization_id=book[0], code="60.1", title="Synthetic BYN-only supplier", category="liability",
                          valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
                          quantity_tracking=False, cash=False, normative_ref="Synthetic only"))
    await db.commit()
    return book


@pytest.mark.usefixtures("receipt_catalog_sku")
async def test_native_fx_receipt_create_post_replay_frozen_source_and_warehouse_projection(client, db, foreign_book):
    org, policy = foreign_book
    path = f"/procurement/organizations/{org}/receipt-documents"
    created = await client.post(path, json={"key": "native-fx", "document": foreign_source()})
    assert created.status_code == 201, created.text
    receipt_id = created.json()["id"]
    options = {"expected_version": 1, "posting_date": "2026-09-03", "policy_id": policy,
               "settlement_account": "60", "vat_account": "18", "inventory_accounts": ["41.1"]}
    preview = await client.post(f"{path}/{receipt_id}/preview", json=options)
    assert preview.status_code == 200, preview.text
    assert preview.json()["lines"][-1]["currency"] == "USD"
    command = {**options, "digest": preview.json()["digest"]}
    assert (await client.post(f"{path}/{receipt_id}/confirm", json={**command, "digest": "0" * 64})).status_code == 409
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == 0


    first = await client.post(f"{path}/{receipt_id}/confirm", json=command)
    assert first.status_code == 201, first.text
    second = await client.post(f"{path}/{receipt_id}/confirm", json=command)
    assert second.status_code == 201, second.text
    assert first.json()["entry_id"] == second.json()["entry_id"]
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == 1
    source = client.test_app.state.core.services.procurement_source
    basis = await source.posted_receipt_basis(db, org, receipt_id, 1)
    assert service.digest(purchases.purchase_from_receipt_basis(basis)[1]) == command["digest"]
    physical = await source.warehouse_receipt_source(db, org, receipt_id, 1)
    assert physical["document"]["currency"] == "BYN"
    assert physical["document"]["foreign_exchange"] == foreign_source()["foreign_exchange"]
    assert physical["lines"][0]["quantity"] == foreign_source()["items"][0]["quantity"]
    posting = await db.get(ReceiptPosting, receipt_id)
    assert posting.digest == command["digest"]
    assert (await client.post(f"{path}/{receipt_id}/confirm", json={**command, "expected_version": 2})).status_code == 409
    assert (await client.post(f"/procurement/organizations/{org+999}/receipt-documents/{receipt_id}/confirm", json=command)).status_code == 403
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("tester", ["sales"])
    assert (await client.post(f"{path}/{receipt_id}/confirm", json=command)).status_code == 403


@pytest.mark.usefixtures("receipt_catalog_sku")
async def test_native_fx_catalog_and_settlement_account_guards(client, db, foreign_book):
    org, policy = foreign_book
    facts = foreign_source()
    facts["foreign_exchange"]["currency"] = "ZZZ"
    path = f"/procurement/organizations/{org}/receipt-documents"
    created = await client.post(path, json={"key": "unknown-fx", "document": facts})
    assert created.status_code == 201, created.text
    options = {"expected_version": 1, "posting_date": "2026-09-03", "policy_id": policy,
               "settlement_account": "60", "vat_account": "18", "inventory_accounts": ["41.1"]}
    refused = await client.post(f"{path}/{created.json()['id']}/preview", json=options)
    assert refused.status_code == 422 and "currency" in refused.text.lower()
    known = await client.post(path, json={"key": "known-fx", "document": foreign_source()})
    assert known.status_code == 201, known.text
    refused = await client.post(f"{path}/{known.json()['id']}/preview", json={**options, "settlement_account": "60.1"})
    assert refused.status_code == 422 and "currency" in refused.text.lower()
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == 0


@pytest.mark.usefixtures("receipt_catalog_sku")
async def test_fx_receipt_late_marker_failure_rolls_back_ledger_and_source_control(client, db, foreign_book):
    org, policy = foreign_book
    path = f"/procurement/organizations/{org}/receipt-documents"
    created = await client.post(path, json={"key": "fx-rollback", "document": foreign_source()})
    assert created.status_code == 201, created.text
    receipt_id = created.json()["id"]
    options = {"expected_version": 1, "posting_date": "2026-09-03", "policy_id": policy,
               "settlement_account": "60", "vat_account": "18", "inventory_accounts": ["41.1"]}
    preview = await client.post(f"{path}/{receipt_id}/preview", json=options)
    assert preview.status_code == 200, preview.text
    command = ReceiptConfirm.model_validate({**options, "digest": preview.json()["digest"]})

    def fail_final_marker(session, flush_context, instances):
        if any(isinstance(row, ReceiptPosting) for row in session.new):
            raise RuntimeError("Synthetic late marker failure")

    event.listen(db.sync_session, "before_flush", fail_final_marker)
    try:
        with pytest.raises(RuntimeError, match="late marker"):
            async with db.begin_nested():
                await client.test_app.state.core.services.procurement_source.confirm_receipt(
                    db, org, receipt_id, command, CurrentUser("tester", ["director"]),
                    client.test_app.state.core.services.accounting, None)
    finally:
        event.remove(db.sync_session, "before_flush", fail_final_marker)
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == 0
    assert await db.scalar(select(func.count()).select_from(models.Line)) == 0
    assert await db.scalar(select(func.count()).select_from(ReceiptPosting)) == 0
    control = await db.scalar(select(models.SourceControl).where(
        models.SourceControl.source == f"procurement:receipt:{receipt_id}"))
    assert control.entry_id is None


@pytest.mark.usefixtures("receipt_catalog_sku")
@pytest.mark.parametrize("field,blocker", [
    ("net_amount", "inventory_cost_layer_correction_required"),
    ("vat_amount", "vat_register_and_eschf_evidence_required"),
])
async def test_original_fx_correction_readiness_requires_matching_evidence(client, db, foreign_book, field, blocker):
    org, policy = foreign_book
    path = f"/procurement/organizations/{org}/receipt-documents"
    source = await client.post(path, json={"key": "fx-readiness", "document": foreign_source()})
    assert source.status_code == 201, source.text
    source_id = source.json()["id"]
    options = {"expected_version": 1, "posting_date": "2026-09-03", "policy_id": policy,
               "settlement_account": "60", "vat_account": "18", "inventory_accounts": ["41.1"]}
    preview = await client.post(f"{path}/{source_id}/preview", json=options)
    assert preview.status_code == 200, preview.text
    posted = await client.post(f"{path}/{source_id}/confirm", json={**options, "digest": preview.json()["digest"]})
    assert posted.status_code == 201, posted.text
    draft = await client.post(f"{path}/{source_id}/correction-drafts", json={
        "key": "original-fx-correction", "expected_version": 1, "expected_entry_id": posted.json()["entry_id"],
    })
    assert draft.status_code == 201, draft.text
    draft_id = draft.json()["id"]
    changed = foreign_source()
    changed["items"][0]["foreign_amounts"][field] = "40.01" if field == "net_amount" else "8.01"
    edited = await client.put(f"{path}/{draft_id}", json={
        "key": "original-fx-change", "expected_version": 1, "document": changed,
    })
    assert edited.status_code == 200, edited.text
    readiness = await client.get(f"{path}/{draft_id}/correction-readiness")
    assert readiness.status_code == 200, readiness.text
    assert blocker in readiness.json()["blockers"]
    assert "primary_document_reissue_evidence_required" in readiness.json()["blockers"]
    assert readiness.json()["posting_available"] is False
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == 1
