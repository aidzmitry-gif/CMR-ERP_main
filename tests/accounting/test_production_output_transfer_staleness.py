from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from modules.accounting import production_output_transfer
from modules.accounting.models import ProductionOutputCostRevision
from modules.accounting.service import AccountingError


class Result:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class Session:
    def __init__(self, policy, rows, receipts=()):
        self.policy = policy
        self.rows = rows
        self.receipts = receipts

    async def get(self, _model, _key):
        return self.policy

    async def execute(self, _statement):
        if _statement.column_descriptions[0]["entity"] is ProductionOutputCostRevision:
            return Result([])
        return Result(self.rows)

    async def scalars(self, _statement):
        return Result(self.receipts)


def row(entry_id, line_id, *, order="ORDER-42", department="SHOP", amount="100.00", side="debit"):
    entry = SimpleNamespace(id=entry_id, source=f"source:{entry_id}", posting_date=date(2026, 10, 10), opening=False)
    line = SimpleNamespace(id=line_id, account_code="20", currency="BYN", cash=False, quantity=None,
                           category="asset", dimensions={"department": department, "order": order},
                           amount=Decimal(amount), side=side)
    return entry, line


def receipt(expected):
    return SimpleNamespace(entry_id=50, organization_id=1, order_id=42, month="2026-10",
                           command={"analytical_order": "ORDER-42"},
                           basis={"policy_id": 7, "wip": {"account": "20", "source_lines": expected}})


def policy():
    return SimpleNamespace(organization_id=1, production_costing={
        "overhead_accounts": ["25"], "wip_account": "20", "finished_goods_account": "43",
        "pool_dimensions": ["department"], "order_dimension": "order",
        "rounding": "largest_remainder_cent", "reference": "Synthetic policy",
    })


@pytest.mark.asyncio
async def test_output_transfer_source_state_uses_trace_through_close_month_and_ignores_own_transfer(monkeypatch):
    original = row(10, 11)
    expected = [production_output_transfer._source_trace(*original)]
    own_transfer = row(50, 51, side="credit")
    other_order = row(12, 13, order="OTHER", amount="50.00")
    current = Session(policy(), [original, own_transfer, other_order])
    assert await production_output_transfer.output_transfer_source_state(current, receipt(expected), "2026-10") == "unchanged"

    late_cost = row(14, 15, amount="10.00")
    changed = Session(policy(), [original, own_transfer, late_cost, other_order])
    assert await production_output_transfer.output_transfer_source_state(changed, receipt(expected), "2026-10") == "changed"

    async def no_lock(*_args):
        return None

    monkeypatch.setattr(production_output_transfer.service, "lock_organization", no_lock)
    with pytest.raises(AccountingError, match="source basis is changed.*order 42"):
        await production_output_transfer.validate_output_transfers_for_close(
            Session(policy(), [original, own_transfer, late_cost], [receipt(expected)]), 1, "2026-10"
        )


@pytest.mark.asyncio
async def test_output_transfer_source_state_blocks_unavailable_trace_and_changed_analytics():
    original = row(10, 11)
    expected = [production_output_transfer._source_trace(*original)]
    assert await production_output_transfer.output_transfer_source_state(
        Session(policy(), [original]), receipt([{"entry_id": 10}]), "2026-10"
    ) == "unavailable"
    assert await production_output_transfer.output_transfer_source_state(
        Session(policy(), [row(10, 11, department="SHOP-2")]), receipt(expected), "2026-10"
    ) == "changed"
