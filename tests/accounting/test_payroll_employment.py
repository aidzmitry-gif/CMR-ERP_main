"""Global HR identities need explicit, dated employer evidence before payroll math."""
from uuid import uuid4

from sqlalchemy import func, select

from modules.accounting import statutory_requirements
from modules.accounting.models import AccessGrant, Organization, PayrollEmploymentBinding, Period
from modules.hr.models import Employee
from tests.accounting.test_payroll_calculation import command, rate_input


def binding_command(employee_id, **changes):
    result = {
        "request_key": str(uuid4()),
        "employee_id": employee_id,
        "contract_ref": "synthetic-contract-7",
        "effective_from": "2026-01-01",
        "state": "active",
        "source_document": "synthetic-contract-document-7",
        "evidence": "Synthetic accountant supplied employer and contract evidence",
    }
    result.update(changes)
    return result


async def test_binding_is_explicit_idempotent_and_retains_identity_snapshot(client, db, book):
    employee = Employee(full_name="Original Employee", department="repair", position="technician")
    db.add(employee)
    await db.flush()
    employee_id = employee.id
    rate = await statutory_requirements.create(db, book[0], rate_input(), "tester")
    await db.commit()
    url = f"/accounting/organizations/{book[0]}/payroll-employments"
    preview_url = f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-component-preview"

    missing = await client.post(preview_url, json=command(book[1], rate["requirement_id"], 9999))
    assert missing.status_code == 422
    assert "Explicit payroll employment binding" in missing.text

    payload = binding_command(employee_id)
    created = await client.post(url, json=payload)
    assert created.status_code == 200, created.text
    again = await client.post(url, json=payload)
    assert again.status_code == 200
    assert again.json() == created.json()
    assert await db.scalar(select(func.count(PayrollEmploymentBinding.id))) == 1
    assert created.json()["personnel_identifier"] is None

    changed = await client.post(url, json={**payload, "contract_ref": "different-contract"})
    assert changed.status_code == 409
    employee.full_name = "Renamed Employee"
    await db.flush()
    preview = await client.post(preview_url, json=command(
        book[1], rate["requirement_id"], created.json()["binding_id"],
    ))
    assert preview.status_code == 200, preview.text
    assert preview.json()["basis"]["employee"] == "Original Employee"
    assert preview.json()["basis"]["contract_ref"] == "synthetic-contract-7"
    assert preview.json()["statutory_payroll_certified"] is False


async def test_binding_is_organization_scoped_and_ended_version_blocks_preview(client, db, book):
    employee = Employee(full_name="Shared Employee", department="sales", position="manager")
    db.add(employee)
    other = Organization(name="Other synthetic employer", unp="888888888")
    db.add(other)
    await db.flush()
    employee_id, other_id = employee.id, other.id
    rate = await statutory_requirements.create(db, book[0], rate_input(), "tester")
    await db.commit()
    org_url = f"/accounting/organizations/{book[0]}/payroll-employments"
    preview_url = f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-component-preview"
    active = await client.post(org_url, json=binding_command(employee_id))
    assert active.status_code == 200, active.text

    # Membership, rather than the global employee ID, gates another book.
    foreign = await client.post(f"/accounting/organizations/{other_id}/payroll-employments",
                                json=binding_command(employee_id))
    assert foreign.status_code == 403
    missing_other = await client.get(
        f"/accounting/organizations/{other_id}/payroll-employments?as_of=2026-10-15",
    )
    assert missing_other.status_code == 403

    db.add(AccessGrant(organization_id=other_id, subject="tester", role="chief"))
    await db.commit()
    other_binding = await client.post(
        f"/accounting/organizations/{other_id}/payroll-employments",
        json=binding_command(employee_id, contract_ref="other-employer-contract"),
    )
    assert other_binding.status_code == 200, other_binding.text
    crossed = await client.post(preview_url, json=command(
        book[1], rate["requirement_id"], other_binding.json()["binding_id"],
    ))
    assert crossed.status_code == 422
    assert "Explicit payroll employment binding" in crossed.text

    ended = await client.post(org_url, json=binding_command(
        employee_id, state="ended", effective_from="2026-10-01",
    ))
    assert ended.status_code == 200, ended.text
    current = await client.get(f"{org_url}?as_of=2026-10-15")
    assert current.status_code == 200
    assert len(current.json()) == 1
    assert current.json()[0]["binding_id"] == ended.json()["binding_id"]
    blocked = await client.post(preview_url, json=command(
        book[1], rate["requirement_id"], active.json()["binding_id"],
    ))
    assert blocked.status_code == 422
    assert "ended or superseded" in blocked.text

    earlier = await client.get(f"{org_url}?as_of=2026-09-15")
    assert earlier.json()[0]["binding_id"] == active.json()["binding_id"]


async def test_binding_rejects_unmapped_employee_and_requires_chief(client, db, book):
    url = f"/accounting/organizations/{book[0]}/payroll-employments"
    unknown = await client.post(url, json=binding_command(987654))
    assert unknown.status_code == 422
    assert "HR employee does not exist" in unknown.text
    employee = Employee(full_name="Synthetic Employee", department="repair", position="technician")
    db.add(employee)
    await db.flush()
    employee_id = employee.id
    await db.commit()
    ended_without_active = await client.post(url, json=binding_command(
        employee_id, state="ended",
    ))
    assert ended_without_active.status_code == 422
    assert "prior active binding" in ended_without_active.text
    grant = await db.scalar(select(AccessGrant).where(
        AccessGrant.organization_id == book[0], AccessGrant.subject == "tester",
    ))
    grant.role = "accountant"
    denied = await client.post(url, json=binding_command(employee_id))
    assert denied.status_code == 403
    grant.role = "reader"
    denied_reader = await client.post(url, json=binding_command(employee_id))
    assert denied_reader.status_code == 403


async def test_closed_period_rejects_new_backdated_binding_but_keeps_idempotent_replay(
        client, db, book):
    employee = Employee(full_name="Synthetic Employee", department="repair", position="technician")
    db.add(employee)
    await db.flush()
    url = f"/accounting/organizations/{book[0]}/payroll-employments"
    original = binding_command(employee.id)
    created = await client.post(url, json=original)
    assert created.status_code == 200, created.text

    db.add(Period(organization_id=book[0], month="2026-10", closed=True, generation=0))
    await db.commit()
    assert (await client.post(url, json=original)).json() == created.json()
    changed = await client.post(url, json=binding_command(
        employee.id, state="ended", effective_from="2026-10-15",
    ))
    assert changed.status_code == 422
    assert "Closed period blocks" in changed.text
    assert await db.scalar(select(func.count(PayrollEmploymentBinding.id))) == 1


async def test_personnel_identifier_is_unique_while_active_and_can_be_reused_after_end(
        client, db, book):
    first = Employee(full_name="First Worker", department="repair", position="worker")
    second = Employee(full_name="Second Worker", department="repair", position="worker")
    db.add_all([first, second])
    await db.flush()
    first_id, second_id = first.id, second.id
    url = f"/accounting/organizations/{book[0]}/payroll-employments"
    original = binding_command(
        first_id, personnel_identifier=" AB-001 ",
        personnel_identifier_evidence="Synthetic signed staff register, row one")
    created = await client.post(url, json=original)
    assert created.status_code == 200, created.text
    assert created.json()["personnel_identifier"] == "AB-001"
    assert created.json()["personnel_identifier_source_verified"] is False
    assert (await client.post(url, json=original)).json() == created.json()
    assert (await client.post(url, json={**original, "personnel_identifier": "AB-002"})).status_code == 409

    duplicate = await client.post(url, json=binding_command(
        second_id, contract_ref="second-contract", personnel_identifier="ab-001",
        personnel_identifier_evidence="Synthetic signed staff register, row two"))
    assert duplicate.status_code == 422
    assert "already active" in duplicate.text
    assert (await client.post(url, json=binding_command(
        second_id, contract_ref="second-contract", personnel_identifier="   ",
        personnel_identifier_evidence="Synthetic signed staff register"))).status_code == 422
    assert (await client.post(url, json=binding_command(
        second_id, contract_ref="second-contract", personnel_identifier="AB-002"))).status_code == 422

    ended = await client.post(url, json=binding_command(
        first_id, state="ended", effective_from="2026-09-30"))
    assert ended.status_code == 200, ended.text
    reused = await client.post(url, json=binding_command(
        second_id, contract_ref="second-contract", effective_from="2026-10-01",
        personnel_identifier="ab-001",
        personnel_identifier_evidence="Synthetic replacement staff register, row three"))
    assert reused.status_code == 200, reused.text
    assert reused.json()["personnel_identifier"] == "ab-001"
