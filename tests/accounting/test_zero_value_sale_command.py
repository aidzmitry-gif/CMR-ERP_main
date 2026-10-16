from copy import deepcopy

import pytest
from pydantic import ValidationError

from modules.accounting.zero_value_disposals import parse_zero_value_command, receipt_digest


def snapshot():
    sale = dict(source="sale:zero:1", source_version=1, document_date="2026-10-29",
                operation_date="2026-10-30", posting_date="2026-10-31", policy_id=7,
                account="43", warehouse="MAIN", sku="A", lot="L1", quantity="0.5",
                expense_account="90.4", expense_dimensions={}, explanation="Reviewed zero cost sale",
                net_amount="100.00", vat_rate="20", vat_basis="Synthetic reviewed basis",
                buyer_account="62", revenue_account="90.1", vat_revenue_account="90.2",
                vat_payable_account="68.2", buyer_dimensions={"counterparty": "C", "contract": "D",
                                                             "settlement_document": "S"})
    return {**{k: sale[k] for k in ("source", "source_version", "document_date", "operation_date",
                                   "posting_date", "policy_id", "explanation")},
            "command_version": 3, "operation": "inventory_sale", "basis_digest": "a" * 64,
            "destination_account": "90.4", "destination_dimensions": {}, "sale_document": sale,
            "inventory_layers": [{"source_entry_id": 10, "source_line_id": 11, "inventory_account": "43",
                                  "inventory_dimensions": {"warehouse": "MAIN", "sku": "A", "lot": "L1"},
                                  "quantity": "0.5"}]}


def test_sale_roundtrip_and_monetary_actor_binding():
    command = parse_zero_value_command(snapshot())
    digest = receipt_digest(1, "chief", command)
    assert receipt_digest(1, "chief", parse_zero_value_command(command.model_dump(mode="json"))) == digest
    assert receipt_digest(1, "other", command) != digest
    assert receipt_digest(2, "chief", command) != digest
    changed = snapshot()
    changed["sale_document"]["net_amount"] = "101.00"
    assert receipt_digest(1, "chief", parse_zero_value_command(changed)) != digest


@pytest.mark.parametrize("field,value", [("quantity", "0.6"), ("operation_date", "2026-10-28"),
                                        ("source", "sale:another"), ("policy_id", 8),
                                        ("expense_account", "20"), ("lot", "L2"),
                                        ("net_amount", "0.00"), ("net_amount", 1.2)])
def test_sale_rejects_inconsistent_or_inexact_terms(field, value):
    data = deepcopy(snapshot())
    data["sale_document"][field] = value
    with pytest.raises(ValidationError):
        parse_zero_value_command(data)
