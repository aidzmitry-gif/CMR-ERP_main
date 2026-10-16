"""Owned production order evidence survives cost review and closing checks."""

import hashlib
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from modules.accounting import order_snapshot
from modules.accounting import production_cost_sources as sources
from modules.accounting import production_output_revisions as revisions
from modules.accounting import production_output_transfer as transfer
from modules.accounting.service import AccountingError


def fixture():
    snapshot = {
        "order_id": 42,
        "number": "ORDER-42",
        "product": "Assembly",
        "quantity": 10,
        "created_at": "2026-09-01T10:00:00",
        "stage": "planned",
    }
    owner = NS(
        order_id=42,
        organization_id=11,
        snapshot=snapshot,
        digest=hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest(),
    )
    dims = dict(order_snapshot.dimensions_from_ownership(owner), department="SHOP")
    policy = NS(
        id=7,
        organization_id=11,
        effective_from=date(2026, 9, 1),
        reference="Synthetic reviewed policy",
        allocation_basis="direct_cost",
        production_costing={
            "overhead_accounts": ["25"],
            "wip_account": "20",
            "finished_goods_account": "43",
            "pool_dimensions": ["department"],
            "order_dimension": "order",
            "rounding": "largest_remainder_cent",
            "reference": "Synthetic reviewed policy",
        },
    )
    entry = NS(
        id=1,
        digest="a" * 64,
        source="synthetic",
        source_version=1,
        operation="manual",
        posting_date=date(2026, 9, 2),
        operation_date=date(2026, 9, 2),
        opening=False,
        correction_of=None,
    )
    line = NS(
        id=2,
        account_code="20",
        account_title="WIP",
        currency="BYN",
        cash=False,
        quantity=None,
        category="asset",
        dimensions=dims,
        amount=Decimal("177.00"),
        side="debit",
    )
    session = NS(
        scalars=AsyncMock(return_value=NS(all=lambda: [policy])),
        scalar=AsyncMock(return_value=owner),
        get=AsyncMock(return_value=policy),
        execute=AsyncMock(return_value=NS(all=lambda: [(entry, line)])),
    )
    return session, policy, owner, entry, line


@pytest.mark.parametrize(
    "case", ["owned", "legacy", "partial", "extra", "tampered", "foreign", "overhead", "custom"]
)
async def test_cost_sources_owned_order_shape_and_registry(monkeypatch, case):
    session, policy, owner, entry, line = fixture()
    monkeypatch.setattr(sources, "lock_organization", AsyncMock())
    monkeypatch.setattr(sources, "validate_accounts", AsyncMock())
    if case == "legacy":
        line.dimensions = {"department": "SHOP", "order": "ORDER-42"}
    if case == "partial":
        del line.dimensions["order_digest"]
    if case == "extra":
        line.dimensions["unapproved"] = "value"
    if case == "tampered":
        line.dimensions["order_product"] = "Changed"
    if case == "foreign":
        owner.organization_id = 99
    if case == "overhead":
        line.account_code = "25"
    if case == "custom":
        policy.production_costing["order_dimension"] = "job"
        line.dimensions["job"] = "ORDER-42"
    if case not in {"owned", "legacy"}:
        with pytest.raises(ValidationError if case == "custom" else AccountingError):
            await sources.cost_sources(session, 11, "2026-09", 7)
        return
    result = await sources.cost_sources(session, 11, "2026-09", 7)
    assert result["snapshot"]["lines"][0]["dimensions"] == line.dimensions
    assert result["snapshot"]["balances"][0]["dimensions"] == line.dimensions
    assert result["snapshot"]["balances"][0]["closing_byn"] == "177.00"
    assert result["snapshot"]["production_order_links_verified"] is False
    assert session.scalar.await_count == (1 if case == "owned" else 0)


@pytest.mark.parametrize("case", ["owned", "legacy", "tampered"])
async def test_close_source_state_preserves_owned_order_evidence(monkeypatch, case):
    session, policy, owner, entry, line = fixture()
    monkeypatch.setattr(revisions, "revisions_through", AsyncMock(return_value=[]))
    if case == "legacy":
        line.dimensions = {"department": "SHOP", "order": "ORDER-42"}
    expected = transfer._source_trace(entry, line)
    expected["dimensions"] = dict(line.dimensions)
    receipt = NS(
        organization_id=11,
        entry_id=9,
        command={"analytical_order": "ORDER-42"},
        basis={"policy_id": 7, "wip": {"account": "20", "source_lines": [expected]}},
    )
    if case == "tampered":
        line.dimensions["order_digest"] = "b" * 64
    state = await transfer.output_transfer_source_state(session, receipt, "2026-09")
    assert state == ("unavailable" if case == "tampered" else "unchanged")
