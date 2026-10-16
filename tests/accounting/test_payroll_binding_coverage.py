"""A monthly gross receipt must account for each known employer binding."""
import base64
from datetime import date
from uuid import uuid4

import pytest
from fastapi import HTTPException

from modules.accounting import models, service
from modules.accounting.schemas import CloseInput
from modules.hr.models import Employee


async def _binding(client, db, prefix, name):
    employee = Employee(full_name=name, department="repair")
    db.add(employee)
    await db.commit()
    response = await client.post(prefix + "/payroll-employments", json={
        "request_key": str(uuid4()), "employee_id": employee.id,
        "contract_ref": f"contract-{employee.id}", "effective_from": "2026-10-01",
        "state": "active", "source_document": f"contract-{employee.id}",
        "evidence": "Synthetic signed source for known employer binding",
    })
    assert response.status_code == 200, response.text
    return employee.id, response.json()["binding_id"]


async def _accrual(db, book, source, binding_id):
    entry = models.Entry(
        organization_id=book[0], source=f"payroll:accrual:{source}", source_version=1,
        operation="payroll_accrual_import", document_date=date(2026, 10, 31),
        operation_date=date(2026, 10, 31), posting_date=date(2026, 10, 31),
        policy_id=book[1], rule_version="verified-payroll-accrual-import-v1",
        explanation="Synthetic source-bound gross payroll receipt",
        opening=False, correction_of=None, digest="a" * 64, actor="tester",
    )
    db.add(entry)
    await db.flush()
    line = {"source_line_id": source, "amount_byn": "100.00"}
    if binding_id is not None:
        line["employment_binding_id"] = binding_id
    db.add(models.PayrollAccrualReceipt(
        entry_id=entry.id, organization_id=book[0], month="2026-10",
        request_key=str(uuid4()), source_document=source, source_version=1,
        source_digest="b" * 64, command={"lines": [line]},
        source={"lines": [line]}, posting={}, digest="c" * 64, actor="tester",
    ))
    await db.commit()


def _file(kind, *, binding_id=None, reference="source"):
    return {
        "request_key": str(uuid4()), "kind": kind, "month": "2026-10",
        "employment_binding_id": binding_id, "reference": reference,
        "filename": "source.pdf",
        "data_url": "data:application/pdf;base64," + base64.b64encode(
            b"%PDF-1.7\nsynthetic chief reviewed document\n").decode(),
        "evidence": "Synthetic chief reviewed the source for this period",
    }


async def test_mixed_accrual_and_individual_zero_cover_all_known_bindings(
        client, db, book, tmp_path, monkeypatch):
    root = tmp_path / "payroll"
    root.mkdir()
    monkeypatch.setenv("AIOS_PAYROLL_DATA_DIR", str(root.resolve()))
    prefix = f"/accounting/organizations/{book[0]}"
    first_employee, first_id = await _binding(client, db, prefix, "First employee")
    second_employee, second_id = await _binding(client, db, prefix, "Second employee")
    await _accrual(db, book, "one-reviewed-source", first_id)
    url = prefix + "/periods/2026-10/closing-controls"
    close = CloseInput(expected_generation=0, evidence={
        step: "Synthetic control checked" for step in service.CLOSE_STEPS
    })
    controls = (await client.get(url)).json()
    assert controls["payroll"]["missing_binding_ids"] == [second_id]
    assert controls["payroll"]["coverage_incomplete"] is True
    assert "payroll_binding_coverage_incomplete" in {
        item["code"] for item in controls["blockers"]}
    with pytest.raises(service.AccountingError, match="binding coverage is incomplete"):
        await service.validate_close_period(db, book[0], "2026-10", close)

    zero_command = _file("payroll_zero_individual", binding_id=second_id,
                         reference="second-no-accrual")
    zero = await client.post(prefix + "/payroll-evidence-files", json=zero_command)
    assert zero.status_code == 200, zero.text
    assert (await client.post(prefix + "/payroll-evidence-files", json=zero_command)).json() == zero.json()
    controls = (await client.get(url)).json()
    assert controls["payroll"]["individual_zero_file_ids"] == [zero.json()["file_id"]]
    assert controls["payroll"]["coverage_incomplete"] is False

    roster = await client.post(prefix + "/payroll-evidence-files", json=_file(
        "payroll_population", reference="two-employee-roster"))
    assert roster.status_code == 200, roster.text
    review = await client.post(prefix + "/periods/2026-10/payroll-population-reviews", json={
        "request_key": str(uuid4()), "source_file_id": roster.json()["file_id"],
        "source_system": "synthetic-hr", "source_document": "two-employee-roster",
        "source_employee_count": 2, "binding_ids": sorted([first_id, second_id]),
        "employee_ids": sorted([first_employee, second_employee]),
        "evidence": "Synthetic chief compared both employee sources",
    })
    assert review.status_code == 200, review.text
    await service.validate_close_period(db, book[0], "2026-10", close)

    stored = root / str(book[0]) / (zero_command["request_key"].replace("-", "") + ".pdf")
    original = stored.read_bytes()
    stored.write_bytes(b"%PDF-1.7\ntampered individual source\n")
    with pytest.raises(HTTPException, match="missing or differs"):
        await service.validate_close_period(db, book[0], "2026-10", close)

    await _accrual(db, book, "second-reviewed-source", second_id)
    controls = (await client.get(url)).json()
    assert controls["payroll"]["individual_zero_file_ids"] == []
    assert controls["payroll"]["accrual_binding_ids"] == sorted([first_id, second_id])
    # The later source supersedes the individual zero; its damaged bytes are
    # retained for audit, but no longer constitute the closing basis.
    await service.validate_close_period(db, book[0], "2026-10", close)

    await _accrual(db, book, "unmapped-legacy-source", None)
    controls = (await client.get(url)).json()
    assert controls["payroll"]["unmapped_accrual_lines"] == 1
    assert controls["payroll"]["coverage_incomplete"] is True
    with pytest.raises(service.AccountingError, match="binding coverage is incomplete"):
        await service.validate_close_period(db, book[0], "2026-10", close)
    stored.write_bytes(original)
