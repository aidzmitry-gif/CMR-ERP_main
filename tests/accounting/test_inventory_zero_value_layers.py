from dataclasses import replace
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from modules.accounting.inventory_cost import (
    _valuation_layers,
    issue_result,
    project_source_allocation,
    replay_source_allocation,
)
from modules.accounting.service import AccountingError
from modules.accounting.zero_value_disposals import (
    AllocatedZeroValueDisposalCommand,
    AuthenticatedZeroValueDisposal,
    InventoryDispositionAllocation,
    ZeroValueDisposalCommand,
    receipt_digest,
)


def row(entry_id, line_id, day, *, quantity, amount, side="debit", dimensions=None, operation="production_output_transfer"):
    dimensions = dimensions or {"warehouse": "MAIN", "sku": "A", "lot": "L1"}
    return SimpleNamespace(id=entry_id, posting_date=day, operation=operation, source=f"source:{entry_id}", source_version=1), SimpleNamespace(
        id=line_id, account_code="43", dimensions=dimensions, category="asset", cash=False, currency="BYN",
        quantity=None if quantity is None else Decimal(str(quantity)), amount=Decimal(str(amount)), side=side,
    )


def event(entry_id=10, line_id=11, quantity="1.000000", token=30):
    command = ZeroValueDisposalCommand(
        operation="inventory_issue", source="inventory:zero:42", source_version=1, posting_date="2026-10-03",
        policy_id=7, basis_digest="a" * 64, destination_account="20", destination_dimensions={"order": "42"},
        inventory_layers=[{"source_entry_id": entry_id, "source_line_id": line_id, "inventory_account": "43",
                           "inventory_dimensions": {"warehouse": "MAIN", "sku": "A", "lot": "L1"}, "quantity": quantity}],
        explanation="Verified zero-value disposal",
    )
    return AuthenticatedZeroValueDisposal(1, 1, date(2026, 10, 3), token, "chief", command, receipt_digest(1, "chief", command))


def allocation_event(*, sale=False, method="fifo", token=30, layers=None, account="43"):
    layers = layers or [
        {"source_entry_id": 10, "source_line_id": 11, "inventory_account": "43",
         "inventory_dimensions": {"warehouse": "MAIN", "sku": "A", "lot": "L1"}, "quantity": "1.000000"},
        {"source_entry_id": 12, "source_line_id": 13, "inventory_account": "43",
         "inventory_dimensions": {"warehouse": "MAIN", "sku": "A", "lot": "L2"}, "quantity": "0.100000"},
    ]
    layers = [{**item, "inventory_account": account} for item in layers]
    quantity = sum((Decimal(item["quantity"]) for item in layers), Decimal(0))
    document = {"source": "inventory:zero:v4", "source_version": 1, "document_date": "2026-10-02",
                "operation_date": "2026-10-03", "posting_date": "2026-10-03", "policy_id": 7,
                "account": account, "warehouse": "MAIN", "sku": "A", "lot": "", "quantity": str(quantity),
                "expense_account": "90.4" if sale else "20", "expense_dimensions": {},
                "explanation": "Verified zero allocation"}
    if sale:
        document.update({"net_amount": "100.00", "vat_rate": "20", "vat_basis": "Synthetic reviewed basis",
                         "buyer_account": "62", "revenue_account": "90.1", "vat_revenue_account": "90.2",
                         "vat_payable_account": "68.2", "buyer_dimensions": {"counterparty": "C", "contract": "D", "settlement_document": "S"}})
    command = AllocatedZeroValueDisposalCommand(
        command_version=4, operation="inventory_sale" if sale else "inventory_issue", source=document["source"],
        source_version=1, posting_date=document["posting_date"], policy_id=7, basis_digest="a" * 64,
        destination_account=document["expense_account"], destination_dimensions={}, inventory_layers=layers,
        explanation=document["explanation"], document_date=document["document_date"], operation_date=document["operation_date"],
        valuation_method=method, document=document,
    )
    return AuthenticatedZeroValueDisposal(9, 1, date(2026, 10, 3), token, "chief", command,
                                          receipt_digest(1, "chief", command))


def data(quantity):
    return SimpleNamespace(warehouse="MAIN", sku="A", lot="L1", quantity=Decimal(str(quantity)), posting_date=date(2026, 10, 4),
                           account="43", policy_id=7, model_dump=lambda **_: {"quantity": str(quantity)})


@pytest.mark.parametrize("method,amounts", [("fifo", ["0.00", "10.00"]),
                                          ("weighted_average", ["5.00", "5.00"])])
def test_versioned_source_allocation_preserves_origin_and_legacy_result(method, amounts):
    rows = [row(10, 11, date(2026, 10, 1), quantity=1, amount=10),
            row(20, 21, date(2026, 10, 2), quantity=None, amount=10, side="credit",
                operation="production_output_cost_correction"),
            row(30, 31, date(2026, 10, 3), quantity=1, amount=10)]
    policy = SimpleNamespace(id=7, inventory_method=method, normative_verified=False)
    options = {"verified_value_lines": frozenset({(20, 21)})}
    legacy = issue_result(policy, rows, 1, data(2), **options)
    allocated = issue_result(policy, rows, 1, data(2), include_source_identity=True, **options)
    assert [(item["source_entry_id"], item["source_line_id"]) for item in allocated["inventory_layers"]] == [(10, 11), (30, 31)]
    assert [item["amount_byn"] for item in allocated["inventory_layers"]] == amounts
    assert allocated["issue_cost_byn"] == legacy["issue_cost_byn"] == "10.00"
    assert allocated["basis_digest"] != legacy["basis_digest"]
    assert all("source_entry_id" not in item for item in legacy["inventory_layers"])
    assert issue_result(policy, rows, 1, data(2), **options) == legacy
    packet = {"allocation_version": 1, "valuation_method": method, "quantity": "2", "amount_byn": "10.00",
              "layers": [{"source_entry_id": item["source_entry_id"], "source_line_id": item["source_line_id"],
                          "inventory_account": "43", "inventory_dimensions": item["dimensions"],
                          "quantity": item["quantity"], "amount_byn": item["amount_byn"]}
                         for item in allocated["inventory_layers"]]}
    selection = InventoryDispositionAllocation.model_validate(packet)
    assert len(selection.layers) == 2
    live, _ = _valuation_layers(rows, {"warehouse": "MAIN", "sku": "A", "lot": "L1"},
                                date(2026, 10, 4), method=method, **options)
    original = [dict(layer) for layer in live]
    remaining = replay_source_allocation(live, selection)
    assert all(layer["quantity"] == 0 and layer["amount"] == 0 for layer in remaining)
    assert live == original
    with pytest.raises(AccountingError, match="exceeds"):
        replay_source_allocation(remaining, selection)
    swapped = {**packet, "layers": list(reversed(packet["layers"]))}
    with pytest.raises(AccountingError, match="policy-selected"):
        replay_source_allocation(live, swapped)
    assert live == original
    for field, invalid in (("quantity", "1"), ("amount_byn", "9.99")):
        with pytest.raises(ValueError, match="conserve"):
            InventoryDispositionAllocation.model_validate({**packet, field: invalid})
    with pytest.raises(ValueError, match="repeats"):
        InventoryDispositionAllocation.model_validate({**packet, "layers": [packet["layers"][0]] * 2})


def test_weighted_source_allocation_preserves_partial_cent_rounding():
    rows = [row(10, 11, date(2026, 10, 1), quantity=1, amount="0.01"),
            row(30, 31, date(2026, 10, 2), quantity=2, amount="0.01")]
    policy = SimpleNamespace(id=7, inventory_method="weighted_average", normative_verified=False)
    result = issue_result(policy, rows, 1, data(2), include_source_identity=True)
    assert [item["amount_byn"] for item in result["inventory_layers"]] == ["0.01", "0.00"]
    packet = {"allocation_version": 1, "valuation_method": "weighted_average", "quantity": "2",
              "amount_byn": "0.01", "layers": [{"source_entry_id": item["source_entry_id"],
              "source_line_id": item["source_line_id"], "inventory_account": "43",
              "inventory_dimensions": item["dimensions"], "quantity": item["quantity"],
              "amount_byn": item["amount_byn"]} for item in result["inventory_layers"]]}
    live, _ = _valuation_layers(rows, {"warehouse": "MAIN", "sku": "A", "lot": "L1"},
                                date(2026, 10, 3), method="weighted_average")
    original = [dict(layer) for layer in live]
    remaining = replay_source_allocation(live, InventoryDispositionAllocation.model_validate(packet))
    assert [(item["quantity"], item["amount"]) for item in remaining] == [(Decimal("0"), Decimal("0")), (Decimal("1"), Decimal("0.01"))]
    assert live == original


def test_weighted_selection_never_creates_negative_cent_portion():
    layers = [{"entry_id": index, "line_id": index + 10, "dimensions": {"warehouse": "MAIN", "sku": "A", "lot": "L1"},
               "quantity": Decimal(quantity), "amount": Decimal("0.01"), "lot": "L1"}
              for index, quantity in enumerate(("1", "1", "1", "5"), 1)]
    from modules.accounting.inventory_cost import _select_policy_layers

    _, _, _, selected = _select_policy_layers(layers, Decimal("3.1"), "weighted_average")
    assert [cost for _, _, cost in selected] == [Decimal("0.01"), Decimal("0.01"), Decimal("0.00"), Decimal("0.00")]
    assert sum(cost for _, _, cost in selected) == Decimal("0.02")


def projection_pool():
    return [{"entry_id": identity, "line_id": identity + 1,
             "dimensions": {"warehouse": "MAIN", "sku": "A", "lot": lot},
             "lot": lot, "quantity": Decimal(quantity), "amount": Decimal(amount)}
            for identity, lot, quantity, amount in ((10, "L1", "5", "31.25"), (20, "L2", "3", "30.00"))]


def projection_selection(pool, method, quantities, amounts):
    return InventoryDispositionAllocation.model_validate({
        "allocation_version": 1, "valuation_method": method,
        "quantity": sum((Decimal(q) for q in quantities), Decimal(0)),
        "amount_byn": sum((Decimal(a) for a in amounts), Decimal(0)),
        "layers": [{"source_entry_id": layer["entry_id"], "source_line_id": layer["line_id"],
                    "inventory_account": "10.1", "inventory_dimensions": layer["dimensions"],
                    "quantity": q, "amount_byn": a}
                   for layer, q, a in zip(pool, quantities, amounts, strict=True)],
    })


@pytest.mark.parametrize("method,amounts,issue_delta,remaining_delta", [
    ("fifo", ["31.25", "10.00"], "5.00", "0.00"),
    ("weighted_average", ["38.28", "7.66"], "3.75", "1.25"),
])
def test_late_value_projection_preserves_sources_and_revalues_remaining_pool(method, amounts, issue_delta, remaining_delta):
    from copy import deepcopy
    from decimal import localcontext

    baseline = projection_pool()
    prospective = deepcopy(baseline)
    prospective[0]["amount"] += Decimal("5.00")
    selection = projection_selection(baseline, method, ["5", "1"], amounts)
    original = deepcopy((baseline, prospective, selection.model_dump()))
    with localcontext() as context:
        context.prec = 4
        result = project_source_allocation(baseline, prospective, selection)
    assert result["delta_byn"] == Decimal(issue_delta)
    assert result["prospective_layers"][0]["quantity"] == 0
    assert sum(layer["amount"] for layer in result["prospective_layers"]) - sum(
        layer["amount"] for layer in result["baseline_layers"]) == Decimal(remaining_delta)
    assert result["delta_byn"] + Decimal(remaining_delta) == Decimal("5.00")
    assert (baseline, prospective, selection.model_dump()) == original
    # Strict historical replay still rejects the new money as an old receipt.
    with pytest.raises(AccountingError, match="policy-selected"):
        replay_source_allocation(baseline, result["allocation"])


def test_projected_weighted_pool_flows_into_next_disposition_without_losing_a_cent():
    from copy import deepcopy

    baseline = projection_pool()
    prospective = deepcopy(baseline)
    prospective[0]["amount"] += Decimal("5.00")
    first = project_source_allocation(baseline, prospective,
        projection_selection(baseline, "weighted_average", ["5", "1"], ["38.28", "7.66"]))
    second = project_source_allocation(first["baseline_layers"], first["prospective_layers"],
        projection_selection(first["baseline_layers"][1:], "weighted_average", ["1"], ["7.66"]))
    remaining_delta = sum(layer["amount"] for layer in second["prospective_layers"]) - sum(
        layer["amount"] for layer in second["baseline_layers"])
    assert (first["delta_byn"], second["delta_byn"], remaining_delta) == (
        Decimal("3.75"), Decimal("0.62"), Decimal("0.63"))


@pytest.mark.parametrize("method", ["fifo", "weighted_average"])
def test_zero_cost_allocation_can_gain_value_without_inventing_an_entry(method):
    baseline = [{**projection_pool()[0], "quantity": Decimal("100"), "amount": Decimal("0.01")}]
    prospective = [{**baseline[0], "amount": Decimal("1.01")}]
    selection = projection_selection(baseline, method, ["1"], ["0.00"])
    result = project_source_allocation(baseline, prospective, selection)
    assert result["delta_byn"] == Decimal("0.01")
    assert selection.amount_byn == 0
    assert result["allocation"].layers[0].source_entry_id == 10
    assert result["prospective_layers"][0]["amount"] == Decimal("1.00")


@pytest.mark.parametrize("change", ["quantity", "identity", "dimensions", "order", "amount", "old_cost"])
def test_projection_rejects_changed_physical_pool_or_forged_historical_cost(change):
    from copy import deepcopy

    baseline = projection_pool()
    prospective = deepcopy(baseline)
    selection = projection_selection(baseline, "fifo", ["5", "1"], ["31.25", "10.00"])
    if change == "quantity":
        prospective[1]["quantity"] += 1
    elif change == "identity":
        prospective[0]["line_id"] = 999
    elif change == "dimensions":
        prospective[0]["dimensions"]["sku"] = "OTHER"
    elif change == "order":
        prospective.reverse()
    elif change == "amount":
        prospective[0]["amount"] = Decimal("-0.01")
    else:
        selection = projection_selection(baseline, "fifo", ["5", "1"], ["31.24", "10.01"])
    with pytest.raises(AccountingError):
        project_source_allocation(baseline, prospective, selection)


@pytest.mark.parametrize("method", ["fifo", "weighted_average"])
@pytest.mark.parametrize("changed_pool", ["baseline", "prospective"])
def test_projection_never_loses_value_on_exhausted_origin(method, changed_pool):
    from copy import deepcopy

    baseline = projection_pool()
    baseline[0].update(quantity=Decimal(0), amount=Decimal(0))
    baseline[1].update(quantity=Decimal(1), amount=Decimal("1.00"))
    prospective = deepcopy(baseline)
    selection = projection_selection(baseline[1:], method, ["1"], ["1.00"])
    (baseline if changed_pool == "baseline" else prospective)[0]["amount"] = Decimal("5.00")
    with pytest.raises(AccountingError, match="exhausted"):
        project_source_allocation(baseline, prospective, selection)


def test_specific_replays_zero_disposal_after_negative_correction_and_respects_cutoff():
    origin = row(10, 11, date(2026, 10, 1), quantity=2, amount=100)
    correction = row(20, 21, date(2026, 10, 2), quantity=None, amount=100, side="credit", operation="production_output_cost_correction")
    policy = SimpleNamespace(id=7, inventory_method="specific", normative_verified=False)
    result = issue_result(policy, [origin, correction], 1, data(1), verified_value_lines=frozenset({(20, 21)}), zero_value_disposals=(event(),))
    assert (result["book_quantity"], result["book_value_byn"], result["remaining_quantity"], result["issue_cost_byn"]) == ("1.000000", "0.00", "0.000000", "0.00")
    before = issue_result(policy, [origin, correction], 1, data(1), verified_value_lines=frozenset({(20, 21)}), zero_value_disposals=(event(),), before_registration_token=30)
    assert (before["book_quantity"], before["book_value_byn"]) == ("2.000000", "0.00")


def test_rejects_wrong_source_and_overdraw_of_authenticated_zero_event():
    origin = row(10, 11, date(2026, 10, 1), quantity=2, amount=100)
    correction = row(20, 21, date(2026, 10, 2), quantity=None, amount=100, side="credit", operation="production_output_cost_correction")
    policy = SimpleNamespace(id=7, inventory_method="specific", normative_verified=False)
    with pytest.raises(AccountingError, match="source layer"):
        issue_result(policy, [origin, correction], 1, data(1), verified_value_lines=frozenset({(20, 21)}), zero_value_disposals=(event(entry_id=99),))
    with pytest.raises(AccountingError, match="exhausted"):
        issue_result(policy, [origin, correction], 1, data(1), verified_value_lines=frozenset({(20, 21)}), zero_value_disposals=(event(quantity="3.000000"),))


def test_weighted_average_zero_event_removes_quantity_but_preserves_nonzero_pool_value():
    rows = [row(10, 11, date(2026, 10, 1), quantity=3, amount="0.01"), row(12, 13, date(2026, 10, 2), quantity=3, amount="0.01")]
    layers, evidence = _valuation_layers(rows, {"warehouse": "MAIN", "sku": "A", "lot": "L1"}, date(2026, 10, 4), method="weighted_average", zero_value_disposals=(event(),), organization_id=1)
    assert sum(layer["quantity"] for layer in layers) == 5
    assert sum(layer["amount"] for layer in layers) == Decimal("0.02")
    assert evidence[-1]["receipt_id"] == 1 and evidence[-1]["entry_id"] is None


def test_weighted_average_rejects_guessed_zero_cost_and_mutated_or_duplicate_receipts():
    valued_rows = [row(10, 11, date(2026, 10, 1), quantity=2, amount=100), row(12, 13, date(2026, 10, 2), quantity=2, amount=100)]
    with pytest.raises(AccountingError, match="still carries"):
        _valuation_layers(valued_rows, {"warehouse": "MAIN", "sku": "A", "lot": "L1"}, date(2026, 10, 4), method="weighted_average", zero_value_disposals=(event(),), organization_id=1)
    valid_rows = [row(10, 11, date(2026, 10, 1), quantity=3, amount="0.01"), row(12, 13, date(2026, 10, 2), quantity=3, amount="0.01")]
    changed = event()
    changed.command.explanation = "Changed after authentication"
    with pytest.raises(AccountingError, match="identity or digest changed"):
        _valuation_layers(valid_rows, {"warehouse": "MAIN", "sku": "A", "lot": "L1"}, date(2026, 10, 4), method="weighted_average", zero_value_disposals=(changed,), organization_id=1)
    with pytest.raises(AccountingError, match="identity or digest changed"):
        _valuation_layers(valid_rows, {"warehouse": "MAIN", "sku": "A", "lot": "L1"}, date(2026, 10, 4), method="weighted_average", zero_value_disposals=(event(), event()), organization_id=1)


def test_weighted_rejects_grouped_zero_slice_that_rounds_to_a_cent():
    rows = [row(10, 11, date(2026, 10, 1), quantity=5, amount="0.01")]
    with pytest.raises(AccountingError, match="rounded pool value"):
        _valuation_layers(rows, {"warehouse": "MAIN", "sku": "A", "lot": "L1"}, date(2026, 10, 4), method="weighted_average", zero_value_disposals=(event(quantity="3.000000"),), organization_id=1)


def test_specific_allows_a_partial_zero_rounding_slice_but_not_the_full_cent():
    origin = row(10, 11, date(2026, 10, 1), quantity=3, amount="0.01")
    policy = SimpleNamespace(id=7, inventory_method="specific", normative_verified=False)
    result = issue_result(policy, [origin], 1, data(1), zero_value_disposals=(event(quantity="1.000000"),))
    assert (result["book_quantity"], result["book_value_byn"]) == ("2.000000", "0.01")
    with pytest.raises(AccountingError, match="valued or exhausted"):
        issue_result(policy, [origin], 1, data(1), zero_value_disposals=(event(quantity="3.000000"),))


def test_specific_checks_whole_command_across_same_lot_origins():
    rows = [row(n, n + 1, date(2026, 10, 1), quantity=5, amount="0.01") for n in (10, 12, 14)]
    saved = event()
    payload = saved.command.model_dump(mode="json")
    template = payload["inventory_layers"][0]
    payload["inventory_layers"] = [{**template, "source_entry_id": n, "source_line_id": n + 1} for n in (10, 12, 14)]
    command = ZeroValueDisposalCommand(**payload)
    saved = replace(saved, command=command, digest=receipt_digest(1, "chief", command))
    policy = SimpleNamespace(id=7, inventory_method="specific", normative_verified=False)
    with pytest.raises(AccountingError, match="rounded command cost"):
        issue_result(policy, rows, 1, data(1), zero_value_disposals=(saved,))


@pytest.mark.parametrize("sale", [False, True])
@pytest.mark.parametrize("method", ["fifo", "weighted_average"])
@pytest.mark.parametrize("inventory_account", [None, "43"])
def test_v4_replays_full_multi_source_selection_and_projects_requested_fifo_lot(sale, method, inventory_account):
    rows = [row(10, 11, date(2026, 10, 1), quantity=1, amount="0.01", dimensions={"warehouse": "MAIN", "sku": "A", "lot": "L1"}),
            row(20, 21, date(2026, 10, 1), quantity=None, amount="0.01", side="credit", operation="production_output_cost_correction", dimensions={"warehouse": "MAIN", "sku": "A", "lot": "L1"}),
            row(12, 13, date(2026, 10, 2), quantity=3, amount="0.01", dimensions={"warehouse": "MAIN", "sku": "A", "lot": "L2"})]
    receipt = allocation_event(sale=sale, method=method)
    original = [(line.quantity, line.amount) for _, line in rows]
    layers, evidence = _valuation_layers(rows, {"warehouse": "MAIN", "sku": "A", "lot": "L2"}, date(2026, 10, 4),
                                         method=method, zero_value_disposals=(receipt,), organization_id=1,
                                         inventory_account=inventory_account, verified_value_lines=frozenset({(20, 21)}))
    assert [(layer["lot"], layer["quantity"]) for layer in layers] == [("L2", Decimal("2.9"))]
    assert sum(layer["amount"] for layer in layers) == Decimal("0.01")
    assert evidence[-1]["receipt_id"] == 9 and evidence[-1]["registration_token"] == 30
    assert evidence[-1]["quantity"] == "1.100000" and evidence[-1]["amount_byn"] == "0.00"
    assert [(line.quantity, line.amount) for _, line in rows] == original


def test_v4_receipt_for_another_account_skips_missing_foreign_sources():
    rows = [row(10, 11, date(2026, 10, 1), quantity=3, amount="0.01")]
    foreign = allocation_event(account="41")
    layers, _ = _valuation_layers(rows, {"warehouse": "MAIN", "sku": "A", "lot": "L1"}, date(2026, 10, 4),
                                  method="fifo", zero_value_disposals=(foreign,), organization_id=1,
                                  inventory_account="43")
    assert [(layer["quantity"], layer["amount"]) for layer in layers] == [(Decimal("3"), Decimal("0.01"))]


def test_v4_weighted_partial_zero_replay_preserves_remaining_pool_value():
    rows = [row(10, 11, date(2026, 10, 1), quantity=3, amount="0.01", dimensions={"warehouse": "MAIN", "sku": "A", "lot": "L1"}),
            row(12, 13, date(2026, 10, 2), quantity=3, amount="0.01", dimensions={"warehouse": "MAIN", "sku": "A", "lot": "L2"})]
    receipt = allocation_event(method="weighted_average", layers=[{"source_entry_id": 10, "source_line_id": 11,
        "inventory_account": "43", "inventory_dimensions": {"warehouse": "MAIN", "sku": "A", "lot": "L1"}, "quantity": "0.100000"}])
    layers, _ = _valuation_layers(rows, {"warehouse": "MAIN", "sku": "A", "lot": ""}, date(2026, 10, 4),
                                  method="weighted_average", zero_value_disposals=(receipt,),
                                  organization_id=1, inventory_account="43")
    assert sum(layer["quantity"] for layer in layers) == Decimal("5.9")
    assert sum(layer["amount"] for layer in layers) == Decimal("0.02")


def test_v4_rejects_reordered_selection_duplicate_receipt_cutoff_and_method_mismatch():
    rows = [row(10, 11, date(2026, 10, 1), quantity=1, amount="0.01", dimensions={"warehouse": "MAIN", "sku": "A", "lot": "L1"}),
            row(20, 21, date(2026, 10, 1), quantity=None, amount="0.01", side="credit", operation="production_output_cost_correction", dimensions={"warehouse": "MAIN", "sku": "A", "lot": "L1"}),
            row(12, 13, date(2026, 10, 2), quantity=3, amount="0.01", dimensions={"warehouse": "MAIN", "sku": "A", "lot": "L2"})]
    receipt = allocation_event()
    reversed_layers = list(reversed([item.model_dump(mode="json") for item in receipt.command.inventory_layers]))
    forged = allocation_event(layers=reversed_layers)
    with pytest.raises(AccountingError, match="policy-selected"):
        _valuation_layers(rows, {"warehouse": "MAIN", "sku": "A", "lot": ""}, date(2026, 10, 4), method="fifo",
                          zero_value_disposals=(forged,), organization_id=1, inventory_account="43",
                          verified_value_lines=frozenset({(20, 21)}))
    with pytest.raises(AccountingError, match="identity or digest changed"):
        _valuation_layers(rows, {"warehouse": "MAIN", "sku": "A", "lot": ""}, date(2026, 10, 4), method="fifo",
                          zero_value_disposals=(receipt, receipt), organization_id=1, inventory_account="43",
                          verified_value_lines=frozenset({(20, 21)}))
    before, _ = _valuation_layers(rows, {"warehouse": "MAIN", "sku": "A", "lot": ""}, date(2026, 10, 4), method="fifo",
                                    zero_value_disposals=(receipt,), organization_id=1, inventory_account="43",
                                    before_registration_token=30, verified_value_lines=frozenset({(20, 21)}))
    assert sum(layer["quantity"] for layer in before) == Decimal("4")
    with pytest.raises(AccountingError, match="policy differs"):
        _valuation_layers(rows, {"warehouse": "MAIN", "sku": "A", "lot": ""}, date(2026, 10, 4), method="weighted_average",
                          zero_value_disposals=(receipt,), organization_id=1, inventory_account="43",
                          verified_value_lines=frozenset({(20, 21)}))


def test_specific_costing_explicitly_rejects_v4_replay():
    policy = SimpleNamespace(id=7, inventory_method="specific", normative_verified=False)
    rows = [row(10, 11, date(2026, 10, 1), quantity=3, amount="0.01")]
    with pytest.raises(AccountingError, match="requires FIFO"):
        issue_result(policy, rows, 1, data(1), zero_value_disposals=(allocation_event(layers=[{
            "source_entry_id": 10, "source_line_id": 11, "inventory_account": "43",
            "inventory_dimensions": {"warehouse": "MAIN", "sku": "A", "lot": "L1"}, "quantity": "1"}], token=30),))


@pytest.mark.parametrize("method", ["specific", "fifo", "weighted_average"])
def test_future_zero_disposal_requires_chronological_costing(method):
    origin = row(10, 11, date(2026, 10, 1), quantity=5, amount="0.01")
    request = data(1)
    request.posting_date = date(2026, 10, 2)
    policy = SimpleNamespace(id=7, inventory_method=method, normative_verified=False)
    with pytest.raises(AccountingError, match="later movements"):
        issue_result(policy, [origin], 1, request, zero_value_disposals=(event(),))
    result = issue_result(policy, [origin], 1, request, zero_value_disposals=(event(),), before_registration_token=30)
    assert result["book_quantity"] == "5.000000"
