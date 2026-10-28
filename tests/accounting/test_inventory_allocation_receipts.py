import hashlib
import json
from types import SimpleNamespace

import pytest

from modules.accounting.inventory_allocation_receipts import validate_inventory_disposition_binding
from modules.accounting.inventory_issues import posting_for, rule_version
from modules.accounting.sales import SaleDocument
from modules.accounting.sales import posting_for as sale_posting_for
from modules.accounting.schemas import (
    InventoryIssueDocument,
    InventorySkuIdentity,
    InventoryWarehouseIdentity,
    PostingInput,
)
from modules.accounting.service import AccountingError, digest


def packet(*, amount="10.00", quantity="2", layers=None):
    return {"allocation_version": 1, "valuation_method": "fifo", "quantity": quantity, "amount_byn": amount,
            "layers": layers or [
                {"source_entry_id": 1, "source_line_id": 2, "inventory_account": "41",
                 "inventory_dimensions": {"warehouse": "W", "sku": "S", "lot": "L"}, "quantity": "1", "amount_byn": "0.00"},
                {"source_entry_id": 3, "source_line_id": 4, "inventory_account": "41",
                 "inventory_dimensions": {"warehouse": "W", "sku": "S", "lot": "L"}, "quantity": "1", "amount_byn": amount},
            ]}


def saved_cost(allocation):
    return {"organization_id": 1, "policy_id": 1, "posting_date": "2026-01-01", "account": "41",
            "source_allocation_version": 1, "method": allocation["valuation_method"],
            "issue_quantity": allocation["quantity"], "issue_cost_byn": allocation["amount_byn"],
            "inventory_layers": [{"source_entry_id": layer["source_entry_id"], "source_line_id": layer["source_line_id"],
                                  "lot": layer["inventory_dimensions"]["lot"], "dimensions": layer["inventory_dimensions"],
                                  "quantity": layer["quantity"], "amount_byn": layer["amount_byn"]}
                                 for layer in allocation["layers"]], "basis_digest": "a" * 64}


def binding():
    document = InventoryIssueDocument(source="issue:1", source_version=1, document_date="2026-01-01",
        operation_date="2026-01-01", posting_date="2026-01-01", policy_id=1, account="41", warehouse="W", sku="S",
        lot="L", quantity="2", expense_account="90.4", explanation="issue")
    allocation = packet()
    posting = posting_for(document, saved_cost(allocation))
    posting = PostingInput.model_validate({**posting.model_dump(mode="json"), "lines": [
        line.model_dump(mode="json") for line in posting.lines if line.amount > 0
    ]})
    entry = SimpleNamespace(id=9, organization_id=1, actor="a", digest=digest(posting), operation="inventory_issue",
        source=document.source, source_version=document.source_version, document_date=document.document_date,
        operation_date=document.operation_date, posting_date=document.posting_date, policy_id=document.policy_id,
        rule_version=posting.rule_version, explanation=document.explanation, opening=False, correction_of=None)
    receipt = SimpleNamespace(entry_id=9, organization_id=1, actor="a", digest=digest(posting),
        command=document.model_dump(mode="json"), posting=posting.model_dump(mode="json"), cost=saved_cost(allocation))
    return entry, receipt, document, allocation


def check(entry, receipt, document, allocation):
    validate_inventory_disposition_binding(entry, receipt, document, allocation, organization_id=1)


@pytest.mark.parametrize("version", [True, 1.0, "1", 2])
def test_allocation_model_rejects_noncanonical_version(version):
    from modules.accounting.zero_value_disposals import InventoryDispositionAllocation

    with pytest.raises(ValueError, match="integer 1"):
        InventoryDispositionAllocation.model_validate({**packet(), "allocation_version": version})


def test_cash_metadata_rejected_even_with_matching_posting_digest():
    entry, receipt, document, allocation = binding()
    receipt.posting["lines"][-1]["cash_activity"] = "operating"
    entry.digest = receipt.digest = digest(PostingInput.model_validate(receipt.posting))
    with pytest.raises(AccountingError, match="currency or cash"):
        check(entry, receipt, document, allocation)


def test_fifo_mixed_zero_and_positive_allocation_binds_only_positive_credit():
    entry, receipt, document, allocation = binding()
    check(entry, receipt, document, allocation)
    posting = posting_for(document, receipt.cost)
    assert [(line.amount, line.quantity) for line in posting.lines] == [(10, None), (10, 1)]
    assert posting.rule_version.endswith(":a1")


@pytest.mark.parametrize("marker", [None, True, 1.0, "1", 2])
def test_explicit_builder_rejects_noncanonical_marker(marker):
    _, receipt, document, _ = binding()
    receipt.cost["source_allocation_version"] = marker
    with pytest.raises(AccountingError, match="marker"):
        posting_for(document, receipt.cost)


def test_legacy_issue_rule_and_shape_are_unchanged():
    _, receipt, document, _ = binding()
    legacy = {key: value for key, value in receipt.cost.items() if key != "source_allocation_version"}
    posting = posting_for(document, legacy)
    assert posting.rule_version == rule_version(document, legacy["basis_digest"])
    old_document = document.model_dump(mode="json")
    old_document.pop("warehouse_identity", None)
    old_document.pop("sku_identity", None)
    raw = json.dumps({"document": old_document, "basis": legacy["basis_digest"]},
                     sort_keys=True, ensure_ascii=False)
    assert posting.rule_version == "inventory-issue-v2:" + hashlib.sha256(raw.encode()).hexdigest()
    bound = document.model_copy(update={
        "warehouse_identity": InventoryWarehouseIdentity(id=4, name="W", title="Main warehouse"),
        "sku_identity": InventorySkuIdentity(id=8, code="S", title="Item S", unit="шт"),
    })
    assert rule_version(bound, legacy["basis_digest"]) != posting.rule_version
    assert len(posting.lines) == 3


@pytest.mark.parametrize("marker", [None, True, 1])
def test_explicit_zero_sale_cannot_bypass_allocation_validation(marker):
    _, _, issue, _ = binding()
    document = SaleDocument(**issue.model_dump(), net_amount="10.00", vat_rate="0", vat_basis="Synthetic",
        buyer_account="62", revenue_account="90.1", vat_revenue_account="90.2", vat_payable_account="68",
        buyer_dimensions={"counterparty": "C", "contract": "D", "settlement_document": "S"})
    cost = saved_cost(packet(amount="0.00"))
    cost["source_allocation_version"] = marker
    with pytest.raises(AccountingError, match="Explicit allocation"):
        sale_posting_for(document, cost)


@pytest.mark.parametrize("change, match", [
    (lambda entry, receipt, document, allocation: setattr(entry, "organization_id", 2), "organization"),
    (lambda entry, receipt, document, allocation: setattr(entry, "source", "forged:1"), "identity"),
    (lambda entry, receipt, document, allocation: allocation.update(quantity="1"), "invalid"),
    (lambda entry, receipt, document, allocation: allocation.update(amount_byn="9.99"), "invalid"),
    (lambda entry, receipt, document, allocation: allocation.update(layers=allocation["layers"][1:]), "invalid"),
    (lambda entry, receipt, document, allocation: receipt.posting["lines"].append({"account": "41", "side": "credit", "amount": "1.00", "quantity": "1", "dimensions": {"warehouse": "W", "sku": "S", "lot": "L"}}), "digest"),
    (lambda entry, receipt, document, allocation: receipt.cost.update(source_allocation_version=2), "Legacy"),
])
def test_rejects_wrong_or_incomplete_binding(change, match):
    entry, receipt, document, allocation = binding()
    change(entry, receipt, document, allocation)
    with pytest.raises(AccountingError, match=match):
        check(entry, receipt, document, allocation)


def test_rejects_entryless_zero_value_flow():
    _, receipt, document, allocation = binding()
    with pytest.raises(AccountingError, match="posted ledger entry"):
        check(None, receipt, document, allocation)


def test_sale_document_binds_its_inventory_account_credits():
    document = SaleDocument(source="issue:1", source_version=1, document_date="2026-01-01", operation_date="2026-01-01",
        posting_date="2026-01-01", policy_id=1, account="41", warehouse="W", sku="S", lot="L", quantity="2",
        expense_account="90.4", explanation="sale", net_amount="20", vat_rate="20", vat_basis="standard",
        buyer_account="62", revenue_account="90.1", vat_revenue_account="90.2", vat_payable_account="68",
        buyer_dimensions={"counterparty": "C", "contract": "K", "settlement_document": "D"})
    allocation = packet()
    cost = saved_cost(allocation)
    posting = sale_posting_for(document, cost)
    posting = PostingInput.model_validate({**posting.model_dump(mode="json"), "lines": [
        line.model_dump(mode="json") for line in posting.lines if line.amount > 0
    ]})
    entry = SimpleNamespace(id=9, organization_id=1, actor="a", digest=digest(posting), operation="inventory_sale",
        source=document.source, source_version=document.source_version, document_date=document.document_date,
        operation_date=document.operation_date, posting_date=document.posting_date, policy_id=document.policy_id,
        rule_version=posting.rule_version, explanation=document.explanation, opening=False, correction_of=None)
    receipt = SimpleNamespace(entry_id=9, organization_id=1, actor="a", digest=digest(posting),
        command=document.model_dump(mode="json"), posting=posting.model_dump(mode="json"), cost=cost)
    check(entry, receipt, document, allocation)
    assert posting.rule_version.endswith(":a1")


@pytest.mark.parametrize("edit", ["omit", "add"])
def test_rejects_omitted_or_added_positive_credit_after_digest_is_rebound(edit):
    entry, receipt, document, allocation = binding()
    credits = receipt.posting["lines"]
    if edit == "omit":
        receipt.posting["lines"] = [line for line in credits if line["account"] != "41"]
    else:
        receipt.posting["lines"].append({"account": "41", "side": "credit", "amount": "1.00", "quantity": "1",
                                         "dimensions": {"warehouse": "W", "sku": "S", "lot": "L"}})
    entry.digest = receipt.digest = digest(PostingInput.model_validate(receipt.posting))
    with pytest.raises(AccountingError, match="positive credits"):
        check(entry, receipt, document, allocation)


@pytest.mark.parametrize("edit, match", [
    (lambda entry, receipt, document, allocation: receipt.cost.update(organization_id=2), "cost identity"),
    (lambda entry, receipt, document, allocation: allocation["layers"][0]["inventory_dimensions"].update(warehouse="OTHER"), "invalid"),
    (lambda entry, receipt, document, allocation: allocation.update(allocation_version=True), "strict integer"),
    (lambda entry, receipt, document, allocation: setattr(entry, "opening", True), "opening"),
])
def test_rejects_strict_version_and_saved_identity_mismatches(edit, match):
    entry, receipt, document, allocation = binding()
    edit(entry, receipt, document, allocation)
    with pytest.raises(AccountingError, match=match):
        check(entry, receipt, document, allocation)


def test_issue_allocation_accepts_its_own_legacy_identity_snapshot():
    from modules.accounting.inventory_issues import document_snapshot

    entry, receipt, document, allocation = binding()
    receipt.command = document_snapshot(document)
    assert "warehouse_identity" not in receipt.command
    assert "sku_identity" not in receipt.command
    check(entry, receipt, document, allocation)


@pytest.mark.parametrize("field", ["warehouse_identity", "sku_identity", "account", "unexpected"])
def test_issue_allocation_rejects_modified_identity_snapshot(field):
    from modules.accounting.inventory_issues import document_snapshot

    entry, receipt, document, allocation = binding()
    receipt.command = document_snapshot(document)
    receipt.command[field] = {"forged": True} if field.endswith("identity") else "forged"
    with pytest.raises(AccountingError, match="command differs"):
        check(entry, receipt, document, allocation)


@pytest.mark.parametrize("field, identity", [
    ("warehouse_identity", InventoryWarehouseIdentity(id=4, name="W", title="Main warehouse")),
    ("sku_identity", InventorySkuIdentity(id=8, code="S", title="Item S", unit="шт")),
])
def test_issue_allocation_rejects_omitted_bound_identity(field, identity):
    from modules.accounting.inventory_issues import document_snapshot

    entry, receipt, document, allocation = binding()
    document = document.model_copy(update={field: identity})
    receipt.command = document_snapshot(document)
    receipt.command.pop(field)
    with pytest.raises(AccountingError, match="command differs"):
        check(entry, receipt, document, allocation)


def test_sale_allocation_does_not_accept_issue_only_legacy_snapshot():
    from modules.accounting.inventory_issues import document_snapshot

    entry, receipt, issue, allocation = binding()
    document = SaleDocument(**issue.model_dump(), net_amount="10.00", vat_rate="0", vat_basis="Synthetic",
        buyer_account="62", revenue_account="90.1", vat_revenue_account="90.2", vat_payable_account="68",
        buyer_dimensions={"counterparty": "C", "contract": "D", "settlement_document": "S"})
    receipt.command = document_snapshot(document)
    with pytest.raises(AccountingError, match="command differs"):
        check(entry, receipt, document, allocation)
