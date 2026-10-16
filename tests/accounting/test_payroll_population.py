"""Monthly source roster must stay aligned with the book before close."""
import base64
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from modules.accounting.models import AccessGrant
from modules.accounting.payroll_population import verify_for_close
from modules.hr.models import Employee


def roster_file(month="2026-10", *, reference="synthetic-roster"):
    return {
        "request_key": str(uuid4()), "kind": "payroll_population",
        "month": month, "reference": reference, "filename": "roster.pdf",
        "data_url": "data:application/pdf;base64," + base64.b64encode(
            b"%PDF-1.7\nsynthetic reviewed payroll roster\n").decode(),
        "evidence": "Synthetic source roster attested by the chief accountant",
    }


async def bind_employee(client, db, prefix, name):
    employee = Employee(full_name=name, department="repair")
    db.add(employee)
    await db.commit()
    response = await client.post(prefix + "/payroll-employments", json={
        "request_key": str(uuid4()), "employee_id": employee.id,
        "contract_ref": f"contract-{employee.id}", "effective_from": "2026-10-01",
        "state": "active", "source_document": f"contract-{employee.id}",
        "evidence": "Synthetic employment source for roster acceptance",
    })
    assert response.status_code == 200, response.text
    return employee.id, response.json()["binding_id"]


async def test_population_review_rejects_partial_roster_and_requires_new_revision(
        client, db, book, tmp_path, monkeypatch):
    root = tmp_path / "payroll"
    root.mkdir()
    monkeypatch.setenv("AIOS_PAYROLL_DATA_DIR", str(root.resolve()))
    prefix = f"/accounting/organizations/{book[0]}"
    first_employee, first_binding = await bind_employee(client, db, prefix, "First worker")
    source = await client.post(prefix + "/payroll-evidence-files", json=roster_file())
    assert source.status_code == 200, source.text
    url = prefix + "/periods/2026-10/payroll-population-reviews"
    command = {
        "request_key": str(uuid4()), "source_file_id": source.json()["file_id"],
        "source_system": "synthetic-hr", "source_document": "synthetic-roster",
        "source_employee_count": 1, "binding_ids": [first_binding],
        "employee_ids": [first_employee],
        "evidence": "Synthetic chief compared every known source employee",
    }
    accepted = await client.post(url, json=command)
    assert accepted.status_code == 200, accepted.text
    assert (await client.post(url, json=command)).json() == accepted.json()
    assert accepted.json()["complete_employee_population_proven"] is False
    stored = root / str(book[0]) / (source.json()["request_key"].replace("-", "") + ".pdf")
    original = stored.read_bytes()
    stored.write_bytes(b"%PDF-1.7\ntampered roster\n")
    with pytest.raises(HTTPException, match="missing or differs"):
        await verify_for_close(db, book[0], "2026-10")
    stored.write_bytes(original)
    await verify_for_close(db, book[0], "2026-10")

    second_employee, second_binding = await bind_employee(client, db, prefix, "Second worker")
    state = (await client.get(prefix + "/periods/2026-10/payroll-population")).json()
    assert state["matches_current_bindings"] is False
    assert state["known_binding_ids"] == sorted([first_binding, second_binding])
    controls = (await client.get(prefix + "/periods/2026-10/closing-controls")).json()
    assert "payroll_population_review_missing" in {
        item["code"] for item in controls["blockers"]
    }
    partial = await client.post(url, json={
        **command, "request_key": str(uuid4()),
        "supersedes_id": accepted.json()["review_id"],
    })
    assert partial.status_code == 422
    new_source = await client.post(prefix + "/payroll-evidence-files", json=roster_file(
        reference="synthetic-roster-revised"))
    assert new_source.status_code == 200, new_source.text
    revised = await client.post(url, json={
        **command, "request_key": str(uuid4()),
        "source_file_id": new_source.json()["file_id"],
        "source_document": "synthetic-roster-revised",
        "source_employee_count": 2,
        "binding_ids": sorted([first_binding, second_binding]),
        "employee_ids": sorted([first_employee, second_employee]),
        "supersedes_id": accepted.json()["review_id"],
    })
    assert revised.status_code == 200, revised.text
    assert revised.json()["revision"] == 2
    assert (await client.get(prefix + "/periods/2026-10/payroll-population")).json()[
        "matches_current_bindings"] is True


async def test_population_review_requires_chief_and_scoped_source(
        client, db, book, tmp_path, monkeypatch):
    root = tmp_path / "payroll"
    root.mkdir()
    monkeypatch.setenv("AIOS_PAYROLL_DATA_DIR", str(root.resolve()))
    prefix = f"/accounting/organizations/{book[0]}"
    source = await client.post(prefix + "/payroll-evidence-files", json=roster_file())
    assert source.status_code == 200, source.text
    grant = await db.scalar(select(AccessGrant).where(
        AccessGrant.organization_id == book[0], AccessGrant.subject == "tester",
    ))
    grant.role = "accountant"
    await db.commit()
    command = {
        "request_key": str(uuid4()), "source_file_id": source.json()["file_id"],
        "source_system": "synthetic-hr", "source_document": "synthetic-roster",
        "source_employee_count": 0, "binding_ids": [], "employee_ids": [],
        "evidence": "Synthetic chief attestations require chief role",
    }
    assert (await client.post(prefix + "/periods/2026-10/payroll-population-reviews",
                              json=command)).status_code == 403
    grant.role = "chief"
    await db.commit()
    wrong_month = await client.post(prefix + "/periods/2026-11/payroll-population-reviews",
                                    json=command)
    assert wrong_month.status_code == 422
    assert (await client.post(prefix + "/periods/2026-10/payroll-population-reviews",
                              json=command)).status_code == 200
