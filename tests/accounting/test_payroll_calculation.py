"""One source-bound arithmetic component is not an accepted payroll run."""
from datetime import date

from sqlalchemy import func, select

from modules.accounting import statutory_requirements
from modules.accounting.models import AccessGrant, Entry, Organization, Policy
from modules.accounting.schemas import StatutoryRequirementInput


def rate_input(*, request_key="00000000-0000-0000-0000-000000000601", value="10",
               effective_from="2026-01-01", code="SYNTHETIC-PAYROLL-RATE"):
    return StatutoryRequirementInput.model_validate({
        "request_key": request_key,
        "kind": "rate",
        "code": code,
        "title": "Synthetic payroll component for arithmetic test",
        "effective_from": effective_from,
        "source_reference": "Synthetic documented rule, never a Belarusian default",
        "evidence": "Synthetic accountant-reviewed rule evidence",
        "rate_value": value,
        "rate_unit": "percent",
        "rate_basis": "Synthetic supplied payroll base",
    })


def command(policy_id, requirement_id, **changes):
    result = {
        "policy_id": policy_id,
        "calculation_date": "2026-10-15",
        "employee": "employee-7",
        "department": "repair",
        "requirement_id": requirement_id,
        "base_byn": "101.05",
        "base_document": "reviewed-timesheet-7",
        "base_evidence": "Synthetic verified base supplied for arithmetic test",
        "rounding": "half_up_cent",
        "rounding_evidence": "Synthetic reviewed rounding method for arithmetic test",
    }
    result.update(changes)
    return result


async def test_payroll_component_uses_org_rate_and_never_posts(client, db, book):
    rate = await statutory_requirements.create(db, book[0], rate_input(), "tester")
    before = await db.scalar(select(func.count(Entry.id)))
    response = await client.post(
        f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-component-preview",
        json=command(book[1], rate["requirement_id"]),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["amount_byn"] == "10.11"
    assert body["basis"]["requirement_id"] == rate["requirement_id"]
    assert body["basis"]["requirement_digest"] == rate["digest"]
    assert body["basis"]["base_document"] == "reviewed-timesheet-7"
    assert body["basis"]["rounding_evidence"] == "Synthetic reviewed rounding method for arithmetic test"
    assert len(body["basis_digest"]) == 64
    assert body["status"] == "arithmetic_preview_only"
    assert body["posting_available"] is False
    assert body["statutory_payroll_certified"] is False
    assert response.headers["cache-control"] == "private, no-store"
    assert await db.scalar(select(func.count(Entry.id))) == before


async def test_payroll_component_rejects_superseded_and_cross_org_rates(client, db, book):
    original = await statutory_requirements.create(db, book[0], rate_input(), "tester")
    await statutory_requirements.create(
        db, book[0], rate_input(request_key="00000000-0000-0000-0000-000000000602", value="20"),
        "tester",
    )
    stale = await client.post(
        f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-component-preview",
        json=command(book[1], original["requirement_id"]),
    )
    assert stale.status_code == 422
    assert "superseded" in stale.text

    other = Organization(name="Other synthetic company", unp="777777777")
    db.add(other)
    await db.flush()
    foreign_rate = await statutory_requirements.create(
        db, other.id, rate_input(request_key="00000000-0000-0000-0000-000000000603"), "tester",
    )
    crossed = await client.post(
        f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-component-preview",
        json=command(book[1], foreign_rate["requirement_id"]),
    )
    assert crossed.status_code == 422
    assert "not effective for this organization" in crossed.text


async def test_payroll_component_requires_verified_policy(client, db, book):
    rate = await statutory_requirements.create(db, book[0], rate_input(), "tester")
    policy = Policy(organization_id=book[0], effective_from=date(2026, 10, 1),
                    reference="Synthetic unverified policy", inventory_method="specific",
                    allocation_basis="direct_cost", depreciation_method="straight_line",
                    normative_reference="Synthetic control", normative_verified=False,
                    approved_by="tester")
    db.add(policy)
    await db.flush()
    blocked = await client.post(
        f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-component-preview",
        json=command(policy.id, rate["requirement_id"]),
    )
    assert blocked.status_code == 422


async def test_payroll_component_requires_whole_month_policy_and_accountant(client, db, book):
    rate = await statutory_requirements.create(db, book[0], rate_input(), "tester")
    db.add(Policy(organization_id=book[0], effective_from=date(2026, 10, 15),
                  reference="Synthetic changed mid-month", inventory_method="specific",
                  allocation_basis="direct_cost", depreciation_method="straight_line",
                  normative_reference="Synthetic control", normative_verified=True,
                  approved_by="tester"))
    await db.flush()
    mid_month = await client.post(
        f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-component-preview",
        json=command(book[1], rate["requirement_id"]),
    )
    assert mid_month.status_code == 422
    grant = await db.scalar(select(AccessGrant).where(
        AccessGrant.organization_id == book[0], AccessGrant.subject == "tester",
    ))
    grant.role = "reader"
    denied = await client.post(
        f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-component-preview",
        json=command(book[1], rate["requirement_id"]),
    )
    assert denied.status_code == 403


async def test_payroll_component_rejects_unverified_base_shape_and_nonpercent_rate(client, db, book):
    rate = await statutory_requirements.create(
        db, book[0], rate_input(value="10"), "tester",
    )
    floating = await client.post(
        f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-component-preview",
        json=command(book[1], rate["requirement_id"], base_byn=101.05),
    )
    assert floating.status_code == 422
    no_rounding = command(book[1], rate["requirement_id"])
    del no_rounding["rounding"]
    missing_method = await client.post(
        f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-component-preview",
        json=no_rounding,
    )
    assert missing_method.status_code == 422

    other_unit = rate_input(
        request_key="00000000-0000-0000-0000-000000000604",
        code="SYNTHETIC-FIXED-RATE",
    ).model_copy(update={"rate_unit": "BYN"})
    fixed = await statutory_requirements.create(db, book[0], other_unit, "tester")
    response = await client.post(
        f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-component-preview",
        json=command(book[1], fixed["requirement_id"]),
    )
    assert response.status_code == 422
    assert "incomplete provenance" in response.text
