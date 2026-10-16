from datetime import date
from types import SimpleNamespace

import pytest

from modules.accounting import payroll_import
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


def policy():
    return Policy(id=7, organization_id=11, effective_from=date(2026, 10, 1),
                  reference="Reviewed accounting policy", inventory_method="specific",
                  allocation_basis="direct_cost", depreciation_method="straight_line",
                  normative_reference="Reviewed accounting policy", normative_verified=False,
                  approved_by="chief@example.test")


def command(**changes):
    value = {
        "request_key": "00000000-0000-0000-0000-000000000001",
        "source_document": "payroll:2026-10:batch-1",
        "source_version": 1,
        "source_digest": "a" * 64,
        "verified_by": "chief@example.test",
        "source_evidence": "Проверенная ведомость начислений и табель за период",
        "policy_id": 7,
        "posting_date": "2026-10-31",
        "payroll_account": "70",
        "lines": [
            {"source_line_id": "line-1", "employee": "E-1", "department": "SALES",
             "debit_account": "26", "amount_byn": "100.00",
             "dimensions": {"contract": "STAFF"},
             "evidence": "Табель и расчёт по работнику E-1"},
            {"source_line_id": "line-2", "employee": "E-2", "department": "SHOP",
             "debit_account": "20", "amount_byn": "50.00",
             "dimensions": {"order": "ORDER-42"},
             "evidence": "Табель и расчёт по работнику E-2"},
        ],
    }
    value.update(changes)
    return payroll_import.PayrollAccrualInput.model_validate(value)


async def prepare(monkeypatch, data=None):
    async def unlock(*_args):
        return SimpleNamespace(id=11)

    async def accounts_on(*_args):
        return {
            "20": SimpleNamespace(category="asset", cash=False, currency_tracking=False,
                                   quantity_tracking=False, required_dimensions=["employee", "department", "order"]),
            "26": SimpleNamespace(category="expense", cash=False, currency_tracking=False,
                                   quantity_tracking=False, required_dimensions=["employee", "department"]),
            "70": SimpleNamespace(category="liability", cash=False, currency_tracking=False,
                                   quantity_tracking=False, required_dimensions=["employee"]),
        }

    async def valid_posting(*_args, **_kwargs):
        return {}, policy()

    monkeypatch.setattr(payroll_import, "lock_organization", unlock)
    monkeypatch.setattr(payroll_import.service, "accounts_on", accounts_on)
    monkeypatch.setattr(payroll_import.service, "validate_posting", valid_posting)
    return await payroll_import.prepare_payroll_accrual(
        Session(policy()), 11, "2026-10", data or command(),
    )


@pytest.mark.asyncio
async def test_verified_payroll_builds_explicit_gross_posting(monkeypatch):
    result = await prepare(monkeypatch)
    assert result["status"] == "reviewed_verified_payroll"
    assert result["posting_available"] is True
    assert result["statutory_payroll_certified"] is False
    assert result["deductions_and_contributions_available"] is False
    posting = result["posting_document"]
    assert posting["operation"] == "payroll_accrual_import"
    assert posting["source"] == "payroll:accrual:11:payroll:2026-10:batch-1"
    assert [(line["account"], line["side"], line["amount"], line["dimensions"])
            for line in posting["lines"]] == [
                ("26", "debit", "100.00", {"contract": "STAFF", "employee": "E-1", "department": "SALES"}),
                ("70", "credit", "100.00", {"employee": "E-1", "department": "SALES"}),
                ("20", "debit", "50.00", {"order": "ORDER-42", "employee": "E-2", "department": "SHOP"}),
                ("70", "credit", "50.00", {"employee": "E-2", "department": "SHOP"}),
            ]


@pytest.mark.asyncio
async def test_payroll_source_version_must_use_correction_workflow():
    with pytest.raises(ValueError, match="dedicated correction workflow"):
        command(source_version=2)


@pytest.mark.asyncio
async def test_payroll_line_identities_are_unique():
    base = command().model_dump(mode="json")
    base["lines"][1]["source_line_id"] = "line-1"
    with pytest.raises(ValueError, match="identities must be unique"):
        payroll_import.PayrollAccrualInput.model_validate(base)


@pytest.mark.asyncio
async def test_payroll_dimensions_cannot_override_employee_identity():
    with pytest.raises(ValueError, match="employee analytic"):
        command(lines=[{**command().lines[0].model_dump(mode="json"),
                        "dimensions": {"employee": "OTHER"}}])


@pytest.mark.asyncio
async def test_payroll_confirmation_persists_immutable_receipt(monkeypatch):
    base = command()
    posting = (await prepare(monkeypatch, base))["posting_document"]
    digest = payroll_import.service.digest(payroll_import.PostingInput.model_validate(posting))
    data = payroll_import.PayrollAccrualConfirmInput.model_validate({
        **base.model_dump(mode="json"), "digest": digest,
    })
    prepared = {
        "digest": digest, "source_digest": base.source_digest,
        "source": {"scope": "verified_payroll_accrual_import"},
        "posting_document": posting,
    }

    async def fake_prepare(*_args, **_kwargs):
        return prepared

    class Posted:
        id = 99

    async def fake_post(*_args, **_kwargs):
        assert _kwargs["payroll_accrual_import"] is True
        return Posted()

    async def unlock(*_args):
        return None

    monkeypatch.setattr(payroll_import, "lock_organization", unlock)
    monkeypatch.setattr(payroll_import, "prepare_payroll_accrual", fake_prepare)
    monkeypatch.setattr(payroll_import.service, "post", fake_post)
    session = Session(None, None)
    entry = await payroll_import.confirm_payroll_accrual(
        session, 11, "2026-10", data, "chief@example.test",
    )
    assert entry.id == 99
    receipt = session.added[0]
    assert receipt.source_document == base.source_document
    assert receipt.source_digest == base.source_digest
    assert receipt.entry_id == 99


@pytest.mark.asyncio
async def test_payroll_operation_requires_dedicated_service_flag():
    posting = payroll_import.PostingInput.model_validate({
        "source": "payroll:accrual:11:manual", "source_version": 1,
        "operation": "payroll_accrual_import", "document_date": "2026-10-31",
        "operation_date": "2026-10-31", "posting_date": "2026-10-31", "policy_id": 7,
        "rule_version": "test", "explanation": "test", "lines": [
            {"account": "26", "side": "debit", "amount": "1.00", "dimensions": {}},
            {"account": "70", "side": "credit", "amount": "1.00", "dimensions": {}},
        ],
    })
    with pytest.raises(AccountingError, match="dedicated reviewed confirmation"):
        await payroll_import.service.validate_posting(None, 11, posting)


@pytest.mark.asyncio
async def test_payroll_preview_endpoint_is_private_and_scoped(client, book, monkeypatch):
    async def fake_prepare(*_args, **_kwargs):
        return {"organization_id": book[0], "month": "2026-10",
                "status": "reviewed_verified_payroll", "posting_available": True,
                "posted": False, "statutory_payroll_certified": False,
                "deductions_and_contributions_available": False}

    monkeypatch.setattr(payroll_import, "prepare_payroll_accrual", fake_prepare)
    response = await client.post(
        f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-accrual-import-preview",
        json=command(policy_id=book[1]).model_dump(mode="json"),
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["status"] == "reviewed_verified_payroll"


@pytest.mark.asyncio
async def test_payroll_access_endpoint_is_private_and_role_scoped(client, book):
    response = await client.get(f"/accounting/organizations/{book[0]}/payroll-accrual-access")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {"organization_id": book[0], "principal": "tester", "can_confirm": True}
