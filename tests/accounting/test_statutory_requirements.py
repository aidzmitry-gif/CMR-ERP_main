from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from modules.accounting import statutory_requirements
from modules.accounting.models import AccessGrant, Organization
from modules.accounting.schemas import StatutoryRequirementInput


def requirement_payload(kind="form", **changes):
    value = {
        "request_key": "00000000-0000-0000-0000-000000000401",
        "kind": kind,
        "code": "PAYROLL-REPORT",
        "title": "Synthetic statutory requirement",
        "effective_from": "2026-10-01",
        "source_reference": "Synthetic verified external source reference",
        "evidence": "Synthetic documented statutory requirement evidence",
        "form_version": "1.0",
        "electronic_format_version": "xml-1.0",
    }
    if kind == "rate":
        value.update(form_version=None, electronic_format_version=None, rate_value="0",
                     rate_unit="percent", rate_basis="verified external payroll base")
    value.update(changes)
    return value


async def test_statutory_requirements_are_explicit_versioned_and_period_scoped(client, book):
    missing = await client.get(f"/accounting/organizations/{book[0]}/periods/2026-09/statutory-requirements")
    assert missing.status_code == 200
    assert missing.json() == []

    form = await client.post(f"/accounting/organizations/{book[0]}/statutory-requirements",
                             json=requirement_payload())
    assert form.status_code == 201, form.text
    assert form.json()["revision"] == 1
    assert form.json()["rate_value"] is None

    rate = await client.post(
        f"/accounting/organizations/{book[0]}/statutory-requirements",
        json=requirement_payload("rate", request_key="00000000-0000-0000-0000-000000000402",
                                 code="SOCIAL-RATE"),
    )
    assert rate.status_code == 201, rate.text
    assert rate.json()["rate_value"] == "0"

    correction = await client.post(
        f"/accounting/organizations/{book[0]}/statutory-requirements",
        json=requirement_payload(request_key="00000000-0000-0000-0000-000000000403",
                                 title="Synthetic statutory requirement correction"),
    )
    assert correction.status_code == 201, correction.text
    assert correction.json()["revision"] == 2

    current = await client.get(f"/accounting/organizations/{book[0]}/periods/2026-10/statutory-requirements")
    assert current.status_code == 200
    rows = {(row["kind"], row["code"]): row for row in current.json()}
    assert rows[("form", "PAYROLL-REPORT")]["revision"] == 2
    assert rows[("rate", "SOCIAL-RATE")]["rate_value"] == "0"


def test_statutory_requirement_input_requires_explicit_kind_specific_fields():
    with pytest.raises(ValueError, match="at least 1 character"):
        StatutoryRequirementInput.model_validate(requirement_payload(form_version=" "))
    with pytest.raises(ValueError, match="at least 10 characters"):
        StatutoryRequirementInput.model_validate(requirement_payload(evidence="short"))
    with pytest.raises(ValueError, match="requires value, unit and basis"):
        StatutoryRequirementInput.model_validate(requirement_payload("rate", rate_unit=None))
    with pytest.raises(ValueError, match="at least 1 character"):
        StatutoryRequirementInput.model_validate(requirement_payload("rate", rate_unit=" "))
    with pytest.raises(ValueError, match="first day"):
        StatutoryRequirementInput.model_validate(requirement_payload(effective_from="2026-10-02"))
    assert StatutoryRequirementInput.model_validate(requirement_payload("rate")).rate_value == 0


async def test_statutory_requirement_lookup_has_no_global_fallback_and_api_rejects_reader(client, db, book):
    other = Organization(name="Synthetic statutory other company", unp="888888888")
    db.add(other)
    await db.flush()
    await statutory_requirements.create(
        db, other.id,
        StatutoryRequirementInput.model_validate(requirement_payload(request_key="00000000-0000-0000-0000-000000000404")),
        "tester",
    )
    assert await statutory_requirements.effective_for(db, book[0], date(2026, 10, 1)) == []

    grant = await db.scalar(select(AccessGrant).where(
        AccessGrant.organization_id == book[0], AccessGrant.subject == "tester",
    ))
    grant.role = "reader"
    await db.commit()
    response = await client.get(f"/accounting/organizations/{book[0]}/periods/2026-10/statutory-requirements")
    assert response.status_code == 403
    response = await client.post(f"/accounting/organizations/{book[0]}/statutory-requirements",
                                 json=requirement_payload())
    assert response.status_code == 403


def test_statutory_requirement_migration_has_period_kind_and_immutability_guards():
    migration = Path("migrations/versions/0157_statutory_requirement_catalog.py").read_text(encoding="utf-8")
    assert 'down_revision = "0156"' in migration
    assert "statutory_requirement_effective_period" in migration
    assert "statutory_requirement_kind_fields" in migration
    assert "BEFORE UPDATE OR DELETE OR TRUNCATE" in migration
