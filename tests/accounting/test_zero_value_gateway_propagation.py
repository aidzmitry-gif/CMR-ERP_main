"""Regression for authenticated late-cost evidence inside zero allocation replay."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.accounting import inventory_allocation_loader, inventory_cost, late_cost_receipts
from modules.accounting.service import AccountingError
from modules.accounting.zero_value_disposals import (
    AllocatedZeroValueDisposalCommand,
    scoped_replay,
    verify_allocated_zero_selection,
)
from tests.accounting.test_zero_value_disposals import allocation_snapshot


async def test_zero_replay_uses_gateway_for_value_and_recursive_allocation(monkeypatch):
    snapshot = allocation_snapshot()
    snapshot["document"]["account"] = "10.1"
    for layer in snapshot["inventory_layers"]:
        layer["inventory_account"] = "10.1"
    command = AllocatedZeroValueDisposalCommand.model_validate(snapshot)
    # An earlier late-cost line must be authenticated even if its SKU is outside
    # the zero-cost selection. Keep the real verified_value_lines guard here.
    rows = [(SimpleNamespace(id=15, operation="inventory_late_cost"),
             SimpleNamespace(id=16, quantity=None))]
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=SimpleNamespace(id=7, inventory_method="fifo", production_costing=None)),
        execute=AsyncMock(return_value=SimpleNamespace(all=lambda: rows)),
    )
    gateway = object()
    authentication = AsyncMock()
    prior = AsyncMock(return_value=())
    monkeypatch.setattr(late_cost_receipts, "verify_receipt", authentication)
    monkeypatch.setattr(inventory_allocation_loader, "load_authenticated_inventory_dispositions", prior)
    def calculated(*args, **kwargs):
        assert kwargs["verified_value_lines"] == frozenset({(15, 16)})
        assert kwargs["before_registration_token"] == 20
        return {"method": "fifo", "issue_quantity": "2", "issue_cost_byn": "0.00",
                "inventory_layers": [{"source_entry_id": item.source_entry_id,
                    "source_line_id": item.source_line_id, "dimensions": item.inventory_dimensions,
                    "quantity": str(item.quantity), "amount_byn": "0.00"}
                    for item in command.inventory_layers]}
    monkeypatch.setattr(inventory_cost, "issue_result", calculated)
    await verify_allocated_zero_selection(session, 1, command,
        before_registration_token=20, prior_zeros=(), procurement=gateway)
    authentication.assert_awaited_once_with(session, 1, 15, gateway)
    prior.assert_awaited_once_with(session, 1, before_entry_id=20,
                                 inventory_account="10.1", procurement=gateway)
    with pytest.raises(AccountingError, match="procurement source gateway"):
        await verify_allocated_zero_selection(session, 1, command,
            before_registration_token=20, prior_zeros=())
    assert authentication.await_count == prior.await_count == 1


async def test_replay_cache_does_not_reuse_other_gateway_authority():
    first, second = object(), object()
    calls = []
    @scoped_replay
    async def prefix(session, organization_id, *, procurement=None):
        calls.append(procurement)
        if procurement is None:
            raise AccountingError("Missing source authority")
        return procurement
    @scoped_replay
    async def history(session, organization_id):
        assert await prefix(session, organization_id, procurement=first) is first
        assert await prefix(session, organization_id, procurement=first) is first
        assert await prefix(session, organization_id, procurement=second) is second
        with pytest.raises(AccountingError, match="Missing source authority"):
            await prefix(session, organization_id)
    await history(object(), 1)
    assert calls == [first, second, None]

