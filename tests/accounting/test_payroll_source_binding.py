"""External payroll lines may carry a stable, organization-owned employer link."""
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from modules.accounting.models import AccessGrant, Account, Organization
from modules.accounting.payroll_source_binding import (
    canonical_command,
    canonical_line,
    verify_lines,
)
from modules.accounting.service import AccountingError
from modules.hr.models import Employee
from tests.accounting.test_payroll_import import command as accrual_command
from tests.accounting.test_payroll_statutory import command as statutory_command


async def test_external_payroll_binding_is_scoped_and_keeps_legacy_command_shape(
        client, db, book):
    employee = Employee(full_name="Bound Employee", department="repair")
    foreign = Organization(name="Foreign payroll book", unp="456456456")
    db.add_all([employee, foreign])
    await db.flush()
    db.add(AccessGrant(organization_id=foreign.id, subject="tester", role="chief"))
    await db.commit()

    async def bind(org_id, effective="2026-01-01"):
        response = await client.post(
            f"/accounting/organizations/{org_id}/payroll-employments", json={
                "request_key": str(uuid4()), "employee_id": employee.id,
                "contract_ref": f"contract-{org_id}", "effective_from": effective,
                "state": "active", "source_document": f"contract-{org_id}",
                "evidence": "Synthetic signed employer source for this legal entity",
            },
        )
        assert response.status_code == 200, response.text
        return response.json()["binding_id"]

    local_id = await bind(book[0])
    foreign_id = await bind(foreign.id)
    line = SimpleNamespace(employment_binding_id=local_id, employee="Bound Employee")
    accepted = await verify_lines(db, book[0], date(2026, 10, 31), [line])
    assert accepted == {"mapped_line_count": 1, "mapped_binding_ids": [local_id],
                        "all_lines_mapped": True}
    with pytest.raises(AccountingError, match="another or unknown employer"):
        await verify_lines(db, book[0], date(2026, 10, 31), [
            SimpleNamespace(employment_binding_id=foreign_id, employee="Bound Employee")])
    with pytest.raises(AccountingError, match="employee name differs"):
        await verify_lines(db, book[0], date(2026, 10, 31), [
            SimpleNamespace(employment_binding_id=local_id, employee="Another Employee")])

    legacy_accrual = accrual_command()
    legacy_statutory = statutory_command()
    assert "employment_binding_id" not in canonical_line(legacy_accrual.lines[0])
    assert "employment_binding_id" not in canonical_command(legacy_accrual)["lines"][0]
    assert "employment_binding_id" not in canonical_command(legacy_statutory)["lines"][0]
    mapped = accrual_command(lines=[{
        **canonical_line(legacy_accrual.lines[0]),
        "employee": "Bound Employee", "employment_binding_id": local_id,
    }])
    assert canonical_command(mapped)["lines"][0]["employment_binding_id"] == local_id


async def test_external_payroll_binding_cannot_start_after_payroll_month(client, db, book):
    employee = Employee(full_name="Future Employee", department="repair")
    db.add(employee)
    await db.commit()
    response = await client.post(
        f"/accounting/organizations/{book[0]}/payroll-employments", json={
            "request_key": str(uuid4()), "employee_id": employee.id,
            "contract_ref": "future-contract", "effective_from": "2026-11-01",
            "state": "active", "source_document": "future-contract",
            "evidence": "Synthetic future employer source for this legal entity",
        },
    )
    assert response.status_code == 200, response.text
    with pytest.raises(AccountingError, match="starts after"):
        await verify_lines(db, book[0], date(2026, 10, 31), [
            SimpleNamespace(employment_binding_id=response.json()["binding_id"],
                            employee="Future Employee")])


async def test_accrual_preview_preserves_checked_employer_id(client, db, book):
    employee = Employee(full_name="Payroll Preview Employee", department="repair")
    db.add(employee)
    for code, category in (("26", "expense"), ("70", "liability"),
                           ("68.1", "liability"), ("69", "liability")):
        db.add(Account(
            organization_id=book[0], code=code, title="Synthetic payroll " + code,
            category=category, valid_from=date(2026, 1, 1),
            required_dimensions=["employee", "department"] if code == "26" else ["employee"],
            currency_tracking=False, quantity_tracking=False, cash=False,
            normative_ref="Synthetic source mapping test",
        ))
    await db.commit()
    prefix = f"/accounting/organizations/{book[0]}"
    binding = await client.post(prefix + "/payroll-employments", json={
        "request_key": str(uuid4()), "employee_id": employee.id,
        "contract_ref": "preview-contract", "effective_from": "2026-01-01",
        "state": "active", "source_document": "preview-contract",
        "evidence": "Synthetic employer source for payroll preview",
    })
    assert binding.status_code == 200, binding.text
    line = {
        "source_line_id": "preview-1", "employment_binding_id": binding.json()["binding_id"],
        "employee": "Payroll Preview Employee", "department": "repair",
        "debit_account": "26", "amount_byn": "100.00",
        "evidence": "Synthetic external source line matched to employer",
    }
    preview = await client.post(prefix + "/periods/2026-10/payroll-accrual-import-preview", json={
        "request_key": str(uuid4()), "source_document": "synthetic-payroll-preview",
        "source_version": 1, "source_digest": "a" * 64,
        "verified_by": "tester", "source_evidence": "Synthetic reviewed external payroll",
        "policy_id": book[1], "posting_date": "2026-10-31",
        "payroll_account": "70", "lines": [line],
    })
    assert preview.status_code == 200, preview.text
    assert preview.json()["stable_employment_mapping_complete"] is True
    assert preview.json()["source"]["lines"][0]["employment_binding_id"] == binding.json()["binding_id"]
    statutory = await client.post(prefix + "/periods/2026-10/payroll-statutory-import-preview", json={
        "request_key": str(uuid4()), "source_document": "synthetic-statutory-preview",
        "source_version": 1, "source_digest": "b" * 64,
        "verified_by": "tester", "source_evidence": "Synthetic reviewed deductions and contributions",
        "policy_id": book[1], "posting_date": "2026-10-31", "payroll_account": "70",
        "lines": [
            {"source_line_id": "deduction-1", "employment_binding_id": binding.json()["binding_id"],
             "employee": "Payroll Preview Employee", "department": "repair",
             "kind": "employee_deduction", "liability_account": "68.1",
             "amount_byn": "13.00", "evidence": "Synthetic mapped deduction from external source"},
            {"source_line_id": "contribution-1", "employment_binding_id": binding.json()["binding_id"],
             "employee": "Payroll Preview Employee", "department": "repair",
             "kind": "employer_contribution", "liability_account": "69",
             "cost_account": "26", "amount_byn": "34.00",
             "evidence": "Synthetic mapped contribution from external source"},
        ],
    })
    assert statutory.status_code == 200, statutory.text
    assert statutory.json()["stable_employment_mapping_complete"] is True
    assert {line["employment_binding_id"] for line in statutory.json()["source"]["lines"]} == {
        binding.json()["binding_id"]}
