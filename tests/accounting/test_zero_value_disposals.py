from decimal import Decimal

import pytest
from pydantic import ValidationError

from modules.accounting.zero_value_disposals import (
    ZeroValueDisposalCommand,
    parse_zero_value_command,
    receipt_digest,
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
