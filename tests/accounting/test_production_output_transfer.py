from datetime import date

import pytest

from modules.accounting import production_output_transfer
from modules.accounting.models import Policy


class Session:
    def __init__(self, *values):
        self.values = list(values)
        self.added = []

    async def scalar(self, _statement):
        return self.values.pop(0)

    async def get(self, _model, _key):
        return None

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None


def policy():
    return Policy(id=7, organization_id=11, effective_from=date(2026, 10, 1),
                  reference="Reviewed production policy", production_costing={
                      "overhead_accounts": ["25"], "wip_account": "20", "finished_goods_account": "43",
                      "pool_dimensions": ["department"], "order_dimension": "order",
                      "rounding": "largest_remainder_cent", "reference": "Reviewed production policy",
                  })


def command(**changes):
    value = {"policy_id": 7, "order_id": 42, "analytical_order": "A", "department": "SHOP",
             "warehouse": "Main", "posting_date": "2026-10-31", "output_document_ids": [101]}
    value.update(changes)
    return production_output_transfer.ProductionOutputTransferInput.model_validate(value)


def review():
    return {"organization_id": 11, "month": "2026-10", "policy_id": 7, "basis_digest": "a" * 64,
            "status": "ready_for_transfer_review", "candidate_transfer_byn": "100.00",
            "output": {"planned_quantity": "2.00", "confirmed_quantity": "2.00", "accepted_quantity": "2.00",
                       "rejected_quantity": "0.00", "pending_quantity": "0.00", "sku_code": "WIDGET",
                       "lot": "LOT-1", "documents": [{"document_id": 101, "operation_date": "2026-10-10"}]},
            "target": {"finished_goods_account": "43"}, "wip": {"account": "20"}}


@pytest.mark.asyncio
async def test_prepare_builds_explicit_finished_goods_transfer(monkeypatch):
    async def fake_preview(*_args, **_kwargs):
        return review()

    async def fake_accounts(*_args, **_kwargs):
        class Account:
            def __init__(self, dimensions):
                self.required_dimensions = dimensions
        return {"43": Account({"warehouse", "sku", "lot"}), "20": Account({"department", "order"})}

    async def fake_validate(*_args, **_kwargs):
        return None

    monkeypatch.setattr(production_output_transfer, "preview_output_cost_basis", fake_preview)
    monkeypatch.setattr(production_output_transfer, "validate_accounts", fake_accounts)
    monkeypatch.setattr(production_output_transfer.service, "validate_posting", fake_validate)
    result = await production_output_transfer.prepare_output_transfer(
        Session(policy()), 11, "2026-10", command(), object(), object())
    assert result["posting_available"] is True and result["final_cost_certified"] is False
    posting = result["posting_document"]
    assert posting["operation"] == "production_output_transfer"
    assert posting["lines"] == [
        {"account": "43", "side": "debit", "amount": "100.00", "dimensions": {"warehouse": "Main", "sku": "WIDGET", "lot": "LOT-1"},
         "currency": "BYN", "original_amount": None, "rate": None, "rate_scale": None, "rate_date": None, "rate_source": None,
         "quantity": "2.00", "cash_activity": None},
        {"account": "20", "side": "credit", "amount": "100.00", "dimensions": {"department": "SHOP", "order": "A"},
         "currency": "BYN", "original_amount": None, "rate": None, "rate_scale": None, "rate_date": None, "rate_source": None,
         "quantity": None, "cash_activity": None},
    ]


@pytest.mark.asyncio
async def test_output_transfer_requires_exact_output_document_set(monkeypatch):
    async def fake_preview(*_args, **_kwargs):
        return review()

    monkeypatch.setattr(production_output_transfer, "preview_output_cost_basis", fake_preview)
    with pytest.raises(ValueError, match="Output document set"):
        await production_output_transfer.prepare_output_transfer(
            Session(policy()), 11, "2026-10", command(output_document_ids=[102]), object(), object())


@pytest.mark.asyncio
async def test_output_transfer_preview_endpoint_is_private_and_company_scoped(client, book, monkeypatch):
    async def fake_prepare(*_args, **_kwargs):
        return {"organization_id": book[0], "month": "2026-10", "policy_id": book[1],
                "scope": "production_output_cost_basis", "posting_available": True, "final_cost_certified": False}

    monkeypatch.setattr(production_output_transfer, "prepare_output_transfer", fake_prepare)
    response = await client.post(
        f"/accounting/organizations/{book[0]}/periods/2026-10/production-output-transfer-preview",
        json=command(policy_id=book[1]).model_dump(mode="json"),
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["posting_available"] is True
