from datetime import date
from types import SimpleNamespace

import pytest

from modules.accounting import production_labor_cost
from modules.accounting.models import Policy
from modules.accounting.service import AccountingError


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


class Production:
    async def cost_orders(self, _session, _org, order_ids):
        return [{"order_id": order_id, "product": "Widget", "quantity": 2} for order_id in order_ids]


def policy():
    return Policy(id=7, organization_id=11, effective_from=date(2026, 10, 1),
                  reference="Reviewed production policy", production_costing={
                      "overhead_accounts": ["25"], "wip_account": "20",
                      "pool_dimensions": ["department"], "order_dimension": "order",
                      "rounding": "largest_remainder_cent", "reference": "Reviewed production policy",
                  })


def command(**changes):
    value = {
        "request_key": "00000000-0000-0000-0000-000000000001",
        "source_document": "payroll:2026-10:batch-1",
        "source_version": 1,
        "source_digest": "a" * 64,
        "verified_by": "chief@example.test",
        "source_evidence": "Проверенная ведомость и расчёт начислений за период",
        "policy_id": 7,
        "posting_date": "2026-10-31",
        "payroll_account": "70",
        "lines": [
            {"source_line_id": "line-1", "employee": "E-1", "order_id": 42,
             "order_analytics": "ORDER-42", "department": "SHOP", "cost_account": "20",
             "role": "direct", "amount_byn": "100.00",
             "evidence": "Табель и расчёт по работнику E-1"},
            {"source_line_id": "line-2", "employee": "E-2", "order_id": 43,
             "order_analytics": "ORDER-43", "department": "SHOP", "cost_account": "25",
             "role": "overhead", "amount_byn": "50.00",
             "evidence": "Табель и расчёт по работнику E-2"},
        ],
    }
    value.update(changes)
    return production_labor_cost.ProductionLaborInput.model_validate(value)


async def prepare(monkeypatch, data=None):
    async def unlock(*_args):
        return None

    async def valid_accounts(*_args):
        return None

    async def accounts_on(*_args):
        return {
            "20": SimpleNamespace(category="asset", cash=False, currency_tracking=False,
                                   quantity_tracking=False, required_dimensions=["department", "order"]),
            "25": SimpleNamespace(category="expense", cash=False, currency_tracking=False,
                                   quantity_tracking=False, required_dimensions=["department"]),
            "70": SimpleNamespace(category="liability", cash=False, currency_tracking=False,
                                   quantity_tracking=False, required_dimensions=[]),
        }

    async def valid_posting(*_args, **_kwargs):
        return {}, policy()

    monkeypatch.setattr(production_labor_cost, "lock_organization", unlock)
    monkeypatch.setattr(production_labor_cost, "validate_accounts", valid_accounts)
    monkeypatch.setattr(production_labor_cost.service, "accounts_on", accounts_on)
    monkeypatch.setattr(production_labor_cost.service, "validate_posting", valid_posting)
    return await production_labor_cost.prepare_labor_import(
        Session(policy()), 11, "2026-10", data or command(), Production())


@pytest.mark.asyncio
async def test_verified_payroll_builds_direct_and_overhead_posting(monkeypatch):
    result = await prepare(monkeypatch)
    assert result["status"] == "reviewed_verified_payroll"
    assert result["posting_available"] is True
    assert result["final_cost_certified"] is False
    posting = result["posting_document"]
    assert posting["operation"] == "production_labor_import"
    assert posting["source"] == "production:labor:11:payroll:2026-10:batch-1"
    assert [(line["account"], line["side"], line["amount"], line["dimensions"])
            for line in posting["lines"]] == [
                ("20", "debit", "100.00", {"department": "SHOP", "order": "ORDER-42"}),
                ("70", "credit", "100.00", {"employee": "E-1"}),
                ("25", "debit", "50.00", {"department": "SHOP"}),
                ("70", "credit", "50.00", {"employee": "E-2"}),
            ]


@pytest.mark.asyncio
async def test_payroll_source_version_must_use_import_workflow(monkeypatch):
    with pytest.raises(ValueError, match="dedicated correction workflow"):
        command(source_version=2)


@pytest.mark.asyncio
async def test_direct_labor_cannot_use_overhead_account(monkeypatch):
    data = command(lines=[{**command().lines[0].model_dump(mode="json"), "cost_account": "25"},
                          command().lines[1].model_dump(mode="json")])
    with pytest.raises(AccountingError, match="configured WIP account"):
        await prepare(monkeypatch, data)


@pytest.mark.asyncio
async def test_payroll_source_line_ids_are_unique():
    base = command().model_dump(mode="json")
    base["lines"][1]["source_line_id"] = "line-1"
    with pytest.raises(ValueError, match="identities must be unique"):
        production_labor_cost.ProductionLaborInput.model_validate(base)


@pytest.mark.asyncio
async def test_confirmation_persists_immutable_receipt(monkeypatch):
    base = command()
    settings = production_labor_cost.ProductionCostPolicyInput.model_validate(policy().production_costing)
    posting_document = production_labor_cost._posting(11, "2026-10", base, policy(), settings)
    data = production_labor_cost.ProductionLaborConfirmInput.model_validate({
        **base.model_dump(mode="json"), "digest": production_labor_cost.service.digest(posting_document),
    })
    prepared = {"digest": "b" * 64, "source_digest": "a" * 64,
                "source": {"scope": "verified_payroll_import"},
                "posting_document": posting_document.model_dump(mode="json")}
    prepared["digest"] = data.digest
    async def fake_prepare(*_args, **_kwargs):
        return prepared

    class Posted:
        id = 99

    async def fake_post(*_args, **_kwargs):
        assert _kwargs["production_labor_import"] is True
        return Posted()

    async def unlock(*_args):
        return None

    monkeypatch.setattr(production_labor_cost, "lock_organization", unlock)
    monkeypatch.setattr(production_labor_cost, "prepare_labor_import", fake_prepare)
    monkeypatch.setattr(production_labor_cost.service, "post", fake_post)
    session = Session(None, None)
    entry = await production_labor_cost.confirm_labor_import(
        session, 11, "2026-10", data, "chief@example.test", production=Production())
    assert entry.id == 99
    receipt = session.added[0]
    assert receipt.source_document == "payroll:2026-10:batch-1"
    assert receipt.source_digest == "a" * 64
    assert receipt.entry_id == 99


@pytest.mark.asyncio
async def test_labor_import_preview_endpoint_is_private_and_scoped(client, book, monkeypatch):
    async def fake_prepare(*_args, **_kwargs):
        return {"organization_id": book[0], "month": "2026-10",
                "status": "reviewed_verified_payroll", "posting_available": True,
                "final_cost_certified": False}

    monkeypatch.setattr(production_labor_cost, "prepare_labor_import", fake_prepare)
    response = await client.post(
        f"/accounting/organizations/{book[0]}/periods/2026-10/production-labor-import-preview",
        json=command(policy_id=book[1]).model_dump(mode="json"),
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["status"] == "reviewed_verified_payroll"
