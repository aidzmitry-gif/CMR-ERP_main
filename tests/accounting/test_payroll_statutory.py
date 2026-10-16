from datetime import date
from types import SimpleNamespace

import pytest

from modules.accounting import payroll_statutory
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


def policy():
    from modules.accounting.models import Policy

    return Policy(id=7, organization_id=11, effective_from=date(2026, 10, 1),
                  reference="Reviewed accounting policy", inventory_method="specific",
                  allocation_basis="direct_cost", depreciation_method="straight_line",
                  normative_reference="Reviewed accounting policy", normative_verified=False,
                  approved_by="chief@example.test")


def command(**changes):
    value = {
        "request_key": "00000000-0000-0000-0000-000000000011",
        "source_document": "payroll:2026-10:statutory-1",
        "source_version": 1,
        "source_digest": "b" * 64,
        "verified_by": "chief@example.test",
        "source_evidence": "Проверенный расчёт удержаний и взносов за период",
        "policy_id": 7,
        "posting_date": "2026-10-31",
        "payroll_account": "70",
        "lines": [
            {"source_line_id": "deduction-1", "employee": "E-1", "department": "SALES",
             "kind": "employee_deduction", "liability_account": "68.1", "amount_byn": "13.00",
             "dimensions": {"contract": "STAFF"},
             "evidence": "Проверенный расчёт удержания по работнику E-1"},
            {"source_line_id": "contribution-1", "employee": "E-1", "department": "SALES",
             "kind": "employer_contribution", "liability_account": "69", "cost_account": "26",
             "amount_byn": "34.00", "dimensions": {"contract": "STAFF"},
             "evidence": "Проверенный расчёт взноса по работнику E-1"},
        ],
    }
    value.update(changes)
    return payroll_statutory.PayrollStatutoryInput.model_validate(value)


async def prepare(monkeypatch, data=None):
    async def unlock(*_args):
        return SimpleNamespace(id=11)

    async def accounts_on(*_args):
        return {
            "26": SimpleNamespace(category="expense", cash=False, currency_tracking=False,
                                   quantity_tracking=False, required_dimensions=["employee", "department"]),
            "68.1": SimpleNamespace(category="liability", cash=False, currency_tracking=False,
                                      quantity_tracking=False, required_dimensions=["employee", "department"]),
            "69": SimpleNamespace(category="liability", cash=False, currency_tracking=False,
                                   quantity_tracking=False, required_dimensions=["employee", "department"]),
            "70": SimpleNamespace(category="liability", cash=False, currency_tracking=False,
                                   quantity_tracking=False, required_dimensions=["employee", "department"]),
        }

    async def valid_posting(*_args, **_kwargs):
        return {}, policy()

    monkeypatch.setattr(payroll_statutory, "lock_organization", unlock)
    monkeypatch.setattr(payroll_statutory.service, "accounts_on", accounts_on)
    monkeypatch.setattr(payroll_statutory.service, "validate_posting", valid_posting)
    return await payroll_statutory.prepare_payroll_statutory(
        Session(policy()), 11, "2026-10", data or command(),
    )


@pytest.mark.asyncio
async def test_reviewed_statutory_import_builds_deduction_and_contribution_posting(monkeypatch):
    result = await prepare(monkeypatch)
    assert result["status"] == "reviewed_verified_payroll_statutory"
    assert result["statutory_payroll_certified"] is False
    assert result["deductions_and_contributions_available"] is True
    assert result["employee_deductions_byn"] == "13.00"
    assert result["employer_contributions_byn"] == "34.00"
    posting = result["posting_document"]
    assert posting["operation"] == "payroll_statutory_import"
    assert [(line["account"], line["side"], line["amount"]) for line in posting["lines"]] == [
        ("70", "debit", "13.00"), ("68.1", "credit", "13.00"),
        ("26", "debit", "34.00"), ("69", "credit", "34.00"),
    ]


@pytest.mark.asyncio
async def test_employer_contribution_requires_cost_account():
    base = command().model_dump(mode="json")
    base["lines"][1].pop("cost_account")
    with pytest.raises(ValueError, match="cost account"):
        payroll_statutory.PayrollStatutoryInput.model_validate(base)


@pytest.mark.asyncio
async def test_statutory_operation_requires_dedicated_service_flag():
    posting = payroll_statutory.PostingInput.model_validate({
        "source": "payroll:statutory:11:manual", "source_version": 1,
        "operation": "payroll_statutory_import", "document_date": "2026-10-31",
        "operation_date": "2026-10-31", "posting_date": "2026-10-31", "policy_id": 7,
        "rule_version": "test", "explanation": "test", "lines": [
            {"account": "70", "side": "debit", "amount": "1.00", "dimensions": {}},
            {"account": "68.1", "side": "credit", "amount": "1.00", "dimensions": {}},
        ],
    })
    with pytest.raises(AccountingError, match="dedicated reviewed confirmation"):
        await payroll_statutory.service.validate_posting(None, 11, posting)


@pytest.mark.asyncio
async def test_statutory_access_endpoint_is_private_and_role_scoped(client, book):
    response = await client.get(f"/accounting/organizations/{book[0]}/payroll-statutory-access")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {"organization_id": book[0], "principal": "tester", "can_confirm": True}


@pytest.mark.asyncio
async def test_statutory_preview_endpoint_is_private_and_scoped(client, book, monkeypatch):
    async def fake_prepare(*_args, **_kwargs):
        return {
            "organization_id": book[0], "month": "2026-10",
            "status": "reviewed_verified_payroll_statutory", "posting_available": True,
            "posted": False, "statutory_payroll_certified": False,
            "deductions_and_contributions_available": True,
        }

    monkeypatch.setattr(payroll_statutory, "prepare_payroll_statutory", fake_prepare)
    response = await client.post(
        f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-statutory-import-preview",
        json=command(policy_id=book[1]).model_dump(mode="json"),
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["status"] == "reviewed_verified_payroll_statutory"
