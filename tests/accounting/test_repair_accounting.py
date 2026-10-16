from datetime import date

import pytest

from modules.accounting import repair_accounting
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
                  reference="Reviewed service policy", normative_verified=False)


def command(**changes):
    value = {
        "request_key": "00000000-0000-0000-0000-000000000001",
        "service_request_id": 42,
        "source_document": "service-request:42",
        "source_version": 1,
        "source_digest": "a" * 64,
        "serial_number": "SN-100",
        "owner_type": "customer",
        "owner_reference": "customer-7",
        "coverage": "paid",
        "counterparty_reference": "customer-7",
        "policy_id": 7,
        "posting_date": "2026-10-31",
        "service_amount_byn": "150.00",
        "settlement_account": "62",
        "revenue_account": "90.1",
        "source_evidence": "Акт ремонта, серийный номер и подтверждение клиента",
        "lines": [
            {"source_line_id": "part-1", "kind": "material", "material_owner": "own",
             "description": "Запчасть", "amount_byn": "50.00", "debit_account": "90.2",
             "credit_account": "10.1", "dimensions": {},
             "evidence": "Накладная на запчасть и акт установки"},
            {"source_line_id": "customer-part", "kind": "material", "material_owner": "customer",
             "description": "Деталь клиента", "amount_byn": "0.00", "dimensions": {},
             "evidence": "Акт передачи имущества клиента без оприходования"},
        ],
    }
    value.update(changes)
    return repair_accounting.RepairAccountingInput.model_validate(value)


async def prepare(monkeypatch, data=None):
    async def unlock(*_args):
        return None

    async def valid_posting(*_args, **_kwargs):
        return {}, policy()

    monkeypatch.setattr(repair_accounting, "lock_organization", unlock)
    monkeypatch.setattr(repair_accounting.service, "validate_posting", valid_posting)
    return await repair_accounting.prepare_repair(Session(policy()), 11, "2026-10", data or command())


@pytest.mark.asyncio
async def test_paid_repair_keeps_customer_material_out_of_owned_cost(monkeypatch):
    result = await prepare(monkeypatch)
    assert result["status"] == "reviewed_repair"
    assert result["financial_result"] == {
        "service_amount_byn": "150.00",
        "cost_amount_byn": "50.00",
        "gross_result_byn": "100.00",
        "customer_material_lines": ["customer-part"],
    }
    posting = result["posting_document"]
    assert len(posting["lines"]) == 4
    assert all(line["amount"] != "0.00" for line in posting["lines"])
    assert all(line["dimensions"]["serial"] == "SN-100" for line in posting["lines"])


@pytest.mark.asyncio
async def test_customer_material_cannot_carry_an_accounting_value():
    with pytest.raises(ValueError, match="Customer-owned material"):
        command(lines=[{
            "source_line_id": "customer-part", "kind": "material", "material_owner": "customer",
            "description": "Деталь клиента", "amount_byn": "10.00", "credit_account": "10.1",
            "evidence": "Акт передачи имущества клиента без оприходования",
        }])


@pytest.mark.asyncio
async def test_warranty_repair_has_no_revenue_terms(monkeypatch):
    with pytest.raises(ValueError, match="Warranty repair"):
        command(coverage="warranty", service_amount_byn="0.00", settlement_account=None,
                revenue_account=None, counterparty_reference=None,
                lines=[{
                    "source_line_id": "part-1", "kind": "material", "material_owner": "customer",
                    "description": "Деталь клиента", "amount_byn": "0.00",
                    "evidence": "Акт передачи имущества клиента без оприходования",
                }])


@pytest.mark.asyncio
async def test_confirmation_saves_repair_receipt(monkeypatch):
    base = command()
    prepared = await prepare(monkeypatch, base)
    data = repair_accounting.RepairAccountingConfirmInput.model_validate({
        **base.model_dump(mode="json"), "digest": prepared["digest"],
    })

    class Posted:
        id = 99

    async def fake_post(*_args, **kwargs):
        assert kwargs.get("event_bus") is None
        assert kwargs["repair_accounting"] is True
        return Posted()

    monkeypatch.setattr(repair_accounting.service, "post", fake_post)
    # confirm checks replay/source identity before rebuilding the posting;
    # keep the policy as the third scalar result used by prepare_repair.
    session = Session(None, None, policy())
    entry = await repair_accounting.confirm_repair(session, 11, "2026-10", data, "chief@example.test")
    assert entry.id == 99
    receipt = session.added[0]
    assert receipt.service_request_id == 42
    assert receipt.coverage == "paid"
    assert receipt.source_digest == "a" * 64


@pytest.mark.asyncio
async def test_generic_posting_cannot_admit_repair_operation(monkeypatch):
    prepared = await prepare(monkeypatch)
    posting = repair_accounting.PostingInput.model_validate(prepared["posting_document"])
    monkeypatch.undo()
    with pytest.raises(AccountingError, match="dedicated reviewed confirmation"):
        await repair_accounting.service.validate_posting(None, 11, posting)


def test_repair_source_version_requires_dedicated_correction():
    with pytest.raises(ValueError, match="dedicated correction workflow"):
        command(source_version=2)


@pytest.mark.asyncio
async def test_prepare_rejects_missing_policy(monkeypatch):
    async def unlock(*_args):
        return None

    monkeypatch.setattr(repair_accounting, "lock_organization", unlock)
    with pytest.raises(AccountingError, match="effective approved"):
        await repair_accounting.prepare_repair(Session(None), 11, "2026-10", command())
