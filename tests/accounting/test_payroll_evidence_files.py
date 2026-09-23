"""Private payroll files have server hashes, scoped access and byte-level rechecks."""
import base64
import hashlib
from uuid import uuid4

from sqlalchemy import select

from modules.accounting.models import AccessGrant, Organization, Period
from modules.hr.models import Employee

PDF = b"%PDF-1.7\nsynthetic payroll source, not a real employee document\n"


def payload(*, request_key=None, data=PDF, **changes):
    result = {
        "request_key": request_key or str(uuid4()),
        "kind": "payroll_policy",
        "reference": "synthetic-policy-source",
        "filename": "policy.pdf",
        "data_url": "data:application/pdf;base64," + base64.b64encode(data).decode(),
        "evidence": "Synthetic accountant supplied policy file for testing",
    }
    result.update(changes)
    return result


async def test_payroll_file_upload_replay_download_and_tamper_block(
        client, db, book, tmp_path, monkeypatch):
    root = tmp_path / "payroll"
    root.mkdir()
    monkeypatch.setenv("AIOS_PAYROLL_DATA_DIR", str(root.resolve()))
    url = f"/accounting/organizations/{book[0]}/payroll-evidence-files"
    command = payload()
    created = await client.post(url, json=command)
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert body["size_bytes"] == len(PDF)
    assert body["bytes_verified_at_upload"] is True
    assert body["document_facts_verified"] is False
    assert "storage_filename" not in body
    assert "data_url" not in str(body)
    assert created.headers["cache-control"] == "private, no-store"
    assert (await client.post(url, json=command)).json() == body
    changed = await client.post(url, json={**command, "reference": "another-policy"})
    assert changed.status_code == 409

    listed = await client.get(url)
    assert listed.status_code == 200
    assert listed.json()[0]["file_id"] == body["file_id"]
    downloaded = await client.get(f"{url}/{body['file_id']}/download")
    assert downloaded.status_code == 200
    assert downloaded.content == PDF
    assert downloaded.headers["x-content-type-options"] == "nosniff"

    storage_file = root / str(book[0]) / (command["request_key"].replace("-", "") + ".pdf")
    assert storage_file.is_file()
    backup_file = tmp_path / "payroll-source-backup.pdf"
    backup_file.write_bytes(storage_file.read_bytes())
    storage_file.write_bytes(b"%PDF-1.7\ntampered")
    corrupted = await client.get(f"{url}/{body['file_id']}/download")
    assert corrupted.status_code == 409
    assert (await client.post(url, json=command)).status_code == 409
    storage_file.write_bytes(backup_file.read_bytes())
    restored = await client.get(f"{url}/{body['file_id']}/download")
    assert restored.status_code == 200
    assert restored.content == PDF


async def test_payroll_file_requires_private_root_scope_and_valid_bytes(
        client, db, book, tmp_path, monkeypatch):
    url = f"/accounting/organizations/{book[0]}/payroll-evidence-files"
    monkeypatch.delenv("AIOS_PAYROLL_DATA_DIR", raising=False)
    unavailable = await client.post(url, json=payload())
    assert unavailable.status_code == 503

    root = tmp_path / "private"
    root.mkdir()
    monkeypatch.setenv("AIOS_PAYROLL_DATA_DIR", str(root.resolve()))
    invalid = await client.post(url, json=payload(data=b"wrong bytes"))
    assert invalid.status_code == 422
    assert not list(root.iterdir())
    missing_subject = await client.post(url, json=payload(kind="timesheet", month="2026-10"))
    assert missing_subject.status_code == 422

    employee = Employee(full_name="Synthetic Payroll Employee", department="repair")
    db.add(employee)
    await db.flush()
    employee_id = employee.id
    await db.commit()
    binding = await client.post(f"/accounting/organizations/{book[0]}/payroll-employments", json={
        "request_key": str(uuid4()), "employee_id": employee_id,
        "contract_ref": "synthetic-employment", "effective_from": "2026-01-01",
        "state": "active", "source_document": "synthetic-signed-contract",
        "evidence": "Synthetic accountant supplied employment evidence",
    })
    assert binding.status_code == 200, binding.text
    contract = await client.post(url, json=payload(
        kind="employment_contract", employment_binding_id=binding.json()["binding_id"],
        reference="synthetic-signed-contract",
    ))
    assert contract.status_code == 200, contract.text
    timesheet = await client.post(url, json=payload(
        kind="timesheet", employment_binding_id=binding.json()["binding_id"],
        month="2026-10", reference="synthetic-timesheet-october",
    ))
    assert timesheet.status_code == 200, timesheet.text
    selected = await client.get(f"{url}?employment_binding_id={binding.json()['binding_id']}&month=2026-10")
    assert [row["file_id"] for row in selected.json()] == [timesheet.json()["file_id"]]

    other = Organization(name="Other payroll company", unp="123123123")
    db.add(other)
    await db.flush()
    other_id = other.id
    await db.commit()
    assert (await client.get(f"/accounting/organizations/{other_id}/payroll-evidence-files")).status_code == 403
    db.add(AccessGrant(organization_id=other_id, subject="tester", role="accountant"))
    await db.commit()
    crossed = await client.get(
        f"/accounting/organizations/{other_id}/payroll-evidence-files/{contract.json()['file_id']}/download",
    )
    assert crossed.status_code == 404

    grant = await db.scalar(select(AccessGrant).where(
        AccessGrant.organization_id == book[0], AccessGrant.subject == "tester",
    ))
    grant.role = "reader"
    await db.commit()
    assert (await client.get(url)).status_code == 403
    assert (await client.post(url, json=payload())).status_code == 403


async def test_zero_activity_file_requires_chief_and_open_month(
        client, db, book, tmp_path, monkeypatch):
    root = tmp_path / "payroll"
    root.mkdir()
    monkeypatch.setenv("AIOS_PAYROLL_DATA_DIR", str(root.resolve()))
    url = f"/accounting/organizations/{book[0]}/payroll-evidence-files"
    command = payload(kind="payroll_zero_activity", month="2026-10")
    grant = await db.scalar(select(AccessGrant).where(
        AccessGrant.organization_id == book[0], AccessGrant.subject == "tester",
    ))
    grant.role = "accountant"
    await db.commit()
    assert (await client.post(url, json=command)).status_code == 403
    grant.role = "chief"
    db.add(Period(organization_id=book[0], month="2026-10", closed=True,
                  generation=0, evidence={}))
    await db.commit()
    closed = await client.post(url, json=command)
    assert closed.status_code == 422
    assert "closed month" in closed.text.lower()
    assert not list(root.iterdir())
