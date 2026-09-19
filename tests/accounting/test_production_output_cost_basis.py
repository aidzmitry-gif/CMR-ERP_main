from datetime import date

import pytest

from modules.accounting import production_output_cost
from modules.accounting.models import Policy
from modules.accounting.service import AccountingError


class FakeSession:
    def __init__(self, policy):
        self.policy = policy

    async def scalar(self, _statement):
        return self.policy


def policy(*, target=None):
    config = {
        "overhead_accounts": ["25"],
        "wip_account": "20",
        "pool_dimensions": ["department"],
        "order_dimension": "order",
        "rounding": "largest_remainder_cent",
        "reference": "Reviewed production policy",
    }
    if target is not None:
        config["finished_goods_account"] = target
    return Policy(
        id=7,
        organization_id=11,
        effective_from=date(2026, 10, 1),
        reference="Reviewed production policy",
        production_costing=config,
    )


def source(*lines):
    return {"snapshot": {"lines": list(lines)}}


def line(line_id, *, side="debit", amount="100.00", order="A"):
    return {
        "entry_id": 10,
        "line_id": line_id,
        "source": "production-input",
        "account": "20",
        "posting_date": "2026-10-04",
        "side": side,
        "amount_byn": amount,
        "dimensions": {"department": "SHOP", "order": order},
        "opening": False,
    }


def output(
    *,
    operation_date="2026-10-10",
    planned="2",
    confirmed="2.00",
    accepted="2.00",
    rejected="0.00",
    pending="0.00",
):
    return {
        "planned_quantity": planned,
        "confirmed_quantity": confirmed,
        "accepted_quantity": accepted,
        "rejected_quantity": rejected,
        "pending_quantity": pending,
        "unit": "шт",
        "documents": [
            {
                "document_id": 1,
                "operation_date": operation_date,
                "quantity": confirmed,
                "state": "accepted",
                "receipt_id": 2,
                "accepted_quantity": accepted,
                "rejected_quantity": rejected,
            }
        ],
    }


class Production:
    def __init__(self, output):
        self.output = output

    async def cost_orders(self, _session, _org, _order_ids):
        return [{"order_id": 42, "product": "Widget", "quantity": 2}]

    async def output_reconciliation(self, _session, _org, _order_id, _warehouse):
        return self.output


async def prepare(monkeypatch, output, *, target=None, lines=None):
    monkeypatch.setattr(production_output_cost, "validate_accounts", lambda *args: _ok())
    monkeypatch.setattr(
        production_output_cost,
        "cost_sources",
        lambda *args, **kwargs: _source(source(*(lines or [line(1)]))),
    )

    async def _ok():
        return {}

    async def _source(value):
        return value

    p = policy(target=target)
    return await production_output_cost.preview_output_cost_basis(
        FakeSession(p), 11, "2026-10", 7, 42, "A", "Main", Production(output), object()
    )


@pytest.mark.asyncio
async def test_partial_output_never_becomes_a_cost_transfer(monkeypatch):
    result = await prepare(monkeypatch, output(confirmed="1.00", accepted="1.00", pending="1.00"))
    assert result["status"] == "awaiting_full_accepted_output"
    assert result["candidate_transfer_byn"] is None
    assert result["posting_available"] is False
    assert result["wip"]["balance_byn"] == "100.00"


@pytest.mark.asyncio
async def test_full_output_requires_explicit_finished_goods_policy(monkeypatch):
    result = await prepare(monkeypatch, output())
    assert result["status"] == "awaiting_finished_goods_policy"
    assert result["candidate_transfer_byn"] == "100.00"
    assert result["wip"]["unit_cost_byn"] == "50.000000"
    assert result["target"]["finished_goods_account"] is None


@pytest.mark.asyncio
async def test_explicit_target_marks_transfer_for_review_only(monkeypatch):
    result = await prepare(monkeypatch, output(), target="43")
    assert result["status"] == "ready_for_transfer_review"
    assert result["target"]["finished_goods_account"] == "43"
    assert result["final_cost_certified"] is False
    assert result["posting_available"] is False


@pytest.mark.asyncio
async def test_negative_wip_is_rejected(monkeypatch):
    with pytest.raises(AccountingError, match="negative"):
        await prepare(
            monkeypatch,
            output(planned="1", confirmed="1.00", accepted="1.00"),
            lines=[line(1, side="credit", amount="5.00")],
        )


@pytest.mark.asyncio
async def test_negative_wip_group_is_rejected_without_offsetting_another_department(monkeypatch):
    first = line(1, amount="70.00")
    second = line(2, side="credit", amount="30.00")
    second["dimensions"] = {"department": "OTHER", "order": "A"}
    with pytest.raises(AccountingError, match="analytic group"):
        await prepare(monkeypatch, output(), lines=[first, second], target="43")


@pytest.mark.asyncio
async def test_output_from_another_period_cannot_be_transferred(monkeypatch):
    result = await prepare(monkeypatch, output(operation_date="2026-09-30"))
    assert result["status"] == "awaiting_output_period_alignment"
    assert result["candidate_transfer_byn"] is None


@pytest.mark.asyncio
async def test_preview_endpoint_is_company_scoped_and_private(client, book, monkeypatch):
    async def fake_preview(*args, **kwargs):
        return {
            "organization_id": book[0],
            "month": "2026-10",
            "policy_id": book[1],
            "scope": "production_output_cost_basis",
        }

    monkeypatch.setattr(production_output_cost, "preview_output_cost_basis", fake_preview)
    response = await client.get(
        f"/accounting/organizations/{book[0]}/periods/2026-10/production-output-cost-preview",
        params={
            "policy_id": book[1],
            "order_id": 42,
            "order_analytics": "A",
            "warehouse": "Главный",
        },
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["organization_id"] == book[0]
