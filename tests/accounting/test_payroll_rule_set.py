"""Employer payroll arithmetic rules are explicit, versioned and organization-scoped."""
from uuid import uuid4

from sqlalchemy import func, select

from modules.accounting import statutory_requirements
from modules.accounting.models import AccessGrant, PayrollRuleSet
from tests.accounting.test_payroll_calculation import rate_input


def command(policy_id, **changes):
    payload = {
        "request_key": str(uuid4()),
        "policy_id": policy_id,
        "effective_from": "2026-01-01",
        "gross_method": "monthly_salary_by_hours",
        "rounding": "half_up_cent",
        "rate_rules": [{
            "code": "SYNTHETIC-EMPLOYEE-DEDUCTION",
            "role": "employee_deduction",
            "base_mode": "gross",
            "classification_evidence": "Synthetic accountant classification of this rate",
        }],
        "source_reference": "synthetic-payroll-policy",
        "source_digest": "c" * 64,
        "evidence": "Synthetic accountant supplied policy method and rounding evidence",
    }
    payload.update(changes)
    return payload


async def test_rule_set_requires_effective_rate_and_is_idempotent(client, db, book):
    url = f"/accounting/organizations/{book[0]}/payroll-rule-sets"
    payload = command(book[1])
    missing = await client.post(url, json=payload)
    assert missing.status_code == 422
    assert "No effective organization rate" in missing.text

    rate = await statutory_requirements.create(db, book[0], rate_input(
        request_key=str(uuid4()), code="SYNTHETIC-EMPLOYEE-DEDUCTION",
    ), "tester")
    await db.commit()
    payload["expected_rate_versions"] = [{
        "code": "SYNTHETIC-EMPLOYEE-DEDUCTION",
        "requirement_id": rate["requirement_id"],
        "requirement_digest": rate["digest"],
    }]
    created = await client.post(url, json=payload)
    assert created.status_code == 200, created.text
    assert created.json()["revision"] == 1
    assert created.json()["rate_versions"] == [{
        "code": "SYNTHETIC-EMPLOYEE-DEDUCTION",
        "requirement_id": rate["requirement_id"],
        "requirement_digest": rate["digest"],
    }]
    assert created.json()["source_document_verified"] is False
    assert "obligation_code" not in created.json()["rate_rules"][0]
    legacy_candidate = (await client.get(
        f"/accounting/organizations/{book[0]}/periods/2026-10/payroll-own-candidate"
    )).json()
    assert legacy_candidate["applicability"]["rate_obligations"] == [{
        "rate_code": "SYNTHETIC-EMPLOYEE-DEDUCTION",
        "obligation_code": None, "chief_decision": None,
    }]
    assert "payroll_rate_obligation_unmapped" in legacy_candidate["blockers"]
    repeated = await client.post(url, json=payload)
    assert repeated.json() == created.json()
    assert await db.scalar(select(func.count(PayrollRuleSet.id))) == 1
    recovered = await client.get(f"{url}/by-request/{payload['request_key']}")
    assert recovered.status_code == 200
    assert recovered.json() == created.json()
    assert recovered.headers["cache-control"] == "private, no-store"
    assert (await client.get(f"{url}/by-request/{uuid4()}")).status_code == 404
    changed = await client.post(url, json={**payload, "rounding": "different"})
    assert changed.status_code == 422
    changed = await client.post(url, json={**payload, "source_reference": "different-policy"})
    assert changed.status_code == 409
    changed_version = await client.post(url, json={
        **payload, "request_key": str(uuid4()),
        "expected_rate_versions": [{**payload["expected_rate_versions"][0],
                                    "requirement_digest": "a" * 64}],
    })
    assert changed_version.status_code == 422
    assert "Payroll rate version changed" in changed_version.text
    assert await db.scalar(select(func.count(PayrollRuleSet.id))) == 1

    replacement_payload = command(
        book[1], rate_rules=[{**payload["rate_rules"][0],
                              "classification_evidence": "Corrected synthetic classification evidence"}],
    )
    replacement = await client.post(url, json=replacement_payload)
    assert replacement.status_code == 200, replacement.text
    assert replacement.json()["revision"] == 2
    assert (await client.post(url, json=replacement_payload)).json() == replacement.json()
    current = await client.get(f"{url}/current?as_of=2026-10-15")
    assert current.status_code == 200
    assert current.json()["rule_set_id"] == replacement.json()["rule_set_id"]
    assert current.headers["cache-control"] == "private, no-store"


async def test_rule_set_rejects_duplicate_codes_and_accountant_write(client, db, book):
    await statutory_requirements.create(db, book[0], rate_input(
        request_key=str(uuid4()), code="SYNTHETIC-EMPLOYEE-DEDUCTION",
    ), "tester")
    await db.commit()
    url = f"/accounting/organizations/{book[0]}/payroll-rule-sets"
    payload = command(book[1])
    duplicate = await client.post(url, json={
        **payload, "rate_rules": payload["rate_rules"] * 2,
    })
    assert duplicate.status_code == 422
    unknown_obligation = await client.post(url, json={
        **payload, "rate_rules": [{**payload["rate_rules"][0],
                                   "obligation_code": "unknown-obligation"}],
    })
    assert unknown_obligation.status_code == 422
    mid_month = await client.post(url, json={**payload, "effective_from": "2026-01-15"})
    assert mid_month.status_code == 422

    grant = await db.scalar(select(AccessGrant).where(
        AccessGrant.organization_id == book[0], AccessGrant.subject == "tester",
    ))
    grant.role = "accountant"
    await db.commit()
    denied = await client.post(url, json=payload)
    assert denied.status_code == 403
    assert await db.scalar(select(func.count(PayrollRuleSet.id))) == 0
