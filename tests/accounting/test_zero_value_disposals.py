from decimal import Decimal

import pytest
from pydantic import ValidationError

from modules.accounting.zero_value_disposals import (
    AllocatedZeroValueDisposalCommand,
    ZeroValueDisposalCommand,
    parse_zero_value_command,
    preview_standalone_zero_value_issue_basis,
    receipt_digest,
    register_standalone_zero_value_issue,
    scoped_replay,
    source_identity,
)


def command(**changes):
    value = {
        "operation": "inventory_issue", "source": "inventory:issue:zero:42", "source_version": 1,
        "posting_date": "2026-10-31", "policy_id": 7, "basis_digest": "a" * 64,
        "destination_account": "20", "destination_dimensions": {"order": "42"},
        "inventory_layers": [
            {"source_entry_id": 10, "source_line_id": 11, "inventory_account": "43", "inventory_dimensions": {"warehouse": "MAIN", "sku": "A", "lot": "L1"}, "quantity": "1.250000"},
            {"source_entry_id": 12, "source_line_id": 13, "inventory_account": "43", "inventory_dimensions": {"warehouse": "MAIN", "sku": "A", "lot": "L2"}, "quantity": "0.750000"},
        ], "explanation": "Confirmed zero layer allocation",
    }
    value.update(changes)
    return ZeroValueDisposalCommand(**value)


def test_command_preserves_multiple_exact_layers_and_canonical_digest():
    value = command()
    assert [layer.quantity for layer in value.inventory_layers] == [Decimal("1.250000"), Decimal("0.750000")]
    assert value.identity == ("inventory:issue:zero:42", 1, "inventory_issue")
    assert receipt_digest(1, "chief", value) == receipt_digest(1, "chief", command())


def test_command_rejects_float_duplicate_layer_and_incomplete_analytics():
    with pytest.raises(ValidationError, match="exact decimal string"):
        command(inventory_layers=[{"source_entry_id": 10, "source_line_id": 11, "inventory_account": "43", "inventory_dimensions": {"warehouse": "MAIN", "sku": "A", "lot": "L1"}, "quantity": 1.25}])
    with pytest.raises(ValidationError, match="must not repeat"):
        command(inventory_layers=[
            {"source_entry_id": 10, "source_line_id": 11, "inventory_account": "43", "inventory_dimensions": {"warehouse": "MAIN", "sku": "A", "lot": "L1"}, "quantity": "1"},
            {"source_entry_id": 10, "source_line_id": 11, "inventory_account": "43", "inventory_dimensions": {"warehouse": "MAIN", "sku": "A", "lot": "L1"}, "quantity": "2"},
        ])
    with pytest.raises(ValidationError, match="needs warehouse"):
        command(inventory_layers=[{"source_entry_id": 10, "source_line_id": 11, "inventory_account": "43", "inventory_dimensions": {"sku": "A", "lot": "L1"}, "quantity": "1"}])


def test_identity_keeps_operation_as_part_of_the_unique_key():
    assert source_identity("document:42", 1, "inventory_issue") != source_identity("document:42", 1, "inventory_sale")
    with pytest.raises(ValueError):
        source_identity("document:42", True, "inventory_issue")
    with pytest.raises(ValueError):
        receipt_digest(True, "chief", command())


def test_invalid_calendar_date_rejected():
    with pytest.raises(ValidationError):
        command(posting_date="2026-02-30")


def test_distinct_source_lines_with_same_analytics_stay_separate():
    original = command()
    layers = [layer.model_dump(mode="json") for layer in original.inventory_layers]
    layers[1]["inventory_dimensions"] = dict(layers[0]["inventory_dimensions"])
    value = command(inventory_layers=layers)
    assert len(value.inventory_layers) == 2
    assert receipt_digest(1, "chief", value) != receipt_digest(1, "chief", original)


def test_dated_snapshot_preserves_legacy_digest_and_separate_dates():
    legacy = command()
    snapshot = legacy.model_dump(mode="json")
    decoded = parse_zero_value_command(snapshot)
    assert decoded.model_dump(mode="json") == snapshot
    assert receipt_digest(1, "chief", decoded) == receipt_digest(1, "chief", legacy)
    dated = {**snapshot, "command_version": 2, "document_date": "2026-10-29", "operation_date": "2026-10-30"}
    decoded = parse_zero_value_command(dated)
    assert decoded.model_dump(mode="json") == dated
    assert receipt_digest(1, "chief", decoded) != receipt_digest(1, "chief", legacy)
    changed = parse_zero_value_command({**dated, "document_date": "2026-10-28"})
    assert receipt_digest(1, "chief", changed) != receipt_digest(1, "chief", decoded)
    for invalid in ({**dated, "command_version": 3}, {**dated, "command_version": 2.0},
                    {**dated, "operation_date": "2026-02-30"},
                    {key: value for key, value in dated.items() if key != "document_date"}):
        with pytest.raises(ValueError):
            parse_zero_value_command(invalid)


def allocation_snapshot(*, sale=False, valuation_method="fifo"):
    document = {
        "source": "inventory:issue:zero:allocation", "source_version": 1,
        "document_date": "2026-10-29", "operation_date": "2026-10-30", "posting_date": "2026-10-31",
        "policy_id": 7, "account": "43", "warehouse": "MAIN", "sku": "A", "lot": "", "quantity": "2.000000",
        "expense_account": "90.4" if sale else "20", "expense_dimensions": {},
        "explanation": "Confirmed zero allocation",
    }
    if sale:
        document.update({"net_amount": "100.00", "vat_rate": "20", "vat_basis": "Synthetic reviewed basis",
                         "buyer_account": "62", "revenue_account": "90.1", "vat_revenue_account": "90.2",
                         "vat_payable_account": "68.2", "buyer_dimensions": {"counterparty": "C", "contract": "D", "settlement_document": "S"}})
    return {**{key: document[key] for key in ("source", "source_version", "document_date", "operation_date", "posting_date", "policy_id", "explanation")},
            "command_version": 4, "operation": "inventory_sale" if sale else "inventory_issue",
            "basis_digest": "a" * 64, "destination_account": document["expense_account"],
            "destination_dimensions": {}, "valuation_method": valuation_method, "document": document,
            "inventory_layers": [
                {"source_entry_id": 10, "source_line_id": 11, "inventory_account": "43", "inventory_dimensions": {"warehouse": "MAIN", "sku": "A", "lot": "L1"}, "quantity": "1.250000"},
                {"source_entry_id": 12, "source_line_id": 13, "inventory_account": "43", "inventory_dimensions": {"warehouse": "MAIN", "sku": "A", "lot": "L2"}, "quantity": "0.750000"},
            ]}


@pytest.mark.parametrize("sale", [False, True])
@pytest.mark.parametrize("valuation_method", ["fifo", "weighted_average"])
def test_v4_all_zero_allocation_normalizes_full_issue_or_sale_document(sale, valuation_method):
    command = parse_zero_value_command(allocation_snapshot(sale=sale, valuation_method=valuation_method))
    assert isinstance(command, AllocatedZeroValueDisposalCommand)
    assert command.command_version == 4
    assert command.allocation.amount_byn == Decimal("0.00")
    assert [(item.source_entry_id, item.source_line_id, item.amount_byn) for item in command.allocation.layers] == [
        (10, 11, Decimal("0.00")), (12, 13, Decimal("0.00")),
    ]
    serialized = command.model_dump(mode="json")
    assert "allocation" not in serialized
    assert parse_zero_value_command(serialized).model_dump(mode="json") == serialized


@pytest.mark.parametrize("mutate", [
    lambda value: value["document"].update(quantity="1.9"),
    lambda value: value["document"].update(operation_date="2026-10-28"),
    lambda value: value["document"].update(expense_account="21"),
    lambda value: value["inventory_layers"][1]["inventory_dimensions"].update(sku="OTHER"),
    lambda value: value["document"].update(lot="L1"),
    lambda value: value["inventory_layers"][1].update(source_entry_id=10, source_line_id=11),
    lambda value: value.update(command_version=4.0),
    lambda value: value.update(command_version=True),
    lambda value: value.update(command_version="4"),
    lambda value: value["inventory_layers"][0].update(quantity=1.25),
    lambda value: value["inventory_layers"][0].update(source_entry_id=True),
])
def test_v4_rejects_document_or_source_identity_mismatch(mutate):
    value = allocation_snapshot()
    mutate(value)
    with pytest.raises((ValidationError, ValueError)):
        parse_zero_value_command(value)


@pytest.mark.asyncio
async def test_v4_runtime_is_fail_closed_before_migration_and_replay_integration():
    command = parse_zero_value_command(allocation_snapshot())
    with pytest.raises(ValueError, match="migration and replay integration"):
        await preview_standalone_zero_value_issue_basis(None, 1, command)
    with pytest.raises(ValueError, match="migration and replay integration"):
        await register_standalone_zero_value_issue(None, 1, "chief", command)


async def test_mutual_replay_checks_each_prefix_once_and_discards_scope():
    calls = []
    version = [1]

    @scoped_replay
    async def zeros(session, organization_id, cutoff):
        calls.append(("zero", cutoff))
        for before in range(cutoff):
            await allocations(session, organization_id, before)
        return version[0]

    @scoped_replay
    async def allocations(session, organization_id, cutoff):
        calls.append(("allocation", cutoff))
        for before in range(cutoff):
            await zeros(session, organization_id, before)
        return version[0]

    session = object()
    assert await zeros(session, 1, 20) == 1
    assert len(calls) == len(set(calls)) == 40
    calls.clear()
    version[0] = 2
    assert await zeros(session, 1, 20) == 2
    assert len(calls) == 40


async def test_failed_replay_does_not_preserve_cached_prefixes():
    calls = []

    @scoped_replay
    async def prefix(session, organization_id):
        calls.append(organization_id)
        return len(calls)

    @scoped_replay
    async def failing(session, organization_id):
        await prefix(session, organization_id)
        await prefix(session, organization_id)
        raise ValueError("replay failed")

    session = object()
    with pytest.raises(ValueError, match="replay failed"):
        await failing(session, 1)
    assert calls == [1]
    assert await prefix(session, 1) == 2
