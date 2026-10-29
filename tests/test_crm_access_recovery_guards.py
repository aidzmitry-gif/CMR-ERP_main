"""CRM access recovery keeps local access closed across drift and lost commits."""
# ruff: noqa: F811 -- reuse the existing isolated API fixture.
import pytest
from sqlalchemy import func, select

from core.domain.models import AuditLog, User
from core.services.keycloak_admin import (
    KeycloakAdminConflict,
    KeycloakAdminNotConfigured,
    KeycloakRoleChange,
)
from tests.test_crm_staff import (
    _active_sales_user,
    crm_staff_api,  # noqa: F401
)

KEY = "synthetic-crm-recovery-key-001"
ROLE_COMMAND = {"role": "sales_head", "expected_current_role": "sales"}
VISIBILITY_COMMAND = {"deal_visibility": "own", "expected_current_visibility": "all"}


async def _user_state(session, user_id):
    user = await session.get(User, user_id, populate_existing=True)
    return None if user is None else (user.role, user.status, user.department, user.deal_visibility)


@pytest.mark.parametrize("kind", ["crm-role", "crm-visibility"])
@pytest.mark.parametrize("problem", [
    "missing_user", "foreign_department", "inactive_user", "privileged_role",
    "inactive_hr", "foreign_hr", "same_value",
])
async def test_crm_change_refuses_ineligible_target_before_any_intent_or_provider_call(
    session, crm_staff_api, kind, problem,
):
    api, gateway = crm_staff_api
    employee, user = await _active_sales_user(session)
    employee_id, user_id = employee.id, user.id
    payload = dict(ROLE_COMMAND if kind == "crm-role" else VISIBILITY_COMMAND)
    if problem == "missing_user":
        await session.delete(user)
    elif problem == "foreign_department":
        user.department = "Закупки"
    elif problem == "inactive_user":
        user.status = "onboarding"
    elif problem == "privileged_role":
        user.role = "director"
    elif problem == "inactive_hr":
        employee.status = "inactive"
    elif problem == "foreign_hr":
        employee.department = "Закупки"
    elif kind == "crm-role":
        payload["role"] = "sales"
    else:
        payload["deal_visibility"] = "all"
    await session.commit()
    state = await _user_state(session, user_id)
    count = await session.scalar(select(func.count()).select_from(AuditLog))
    response = await api.post(f"/system/users/{employee_id}/{kind}", headers={"Idempotency-Key": KEY}, json=payload)
    expected = 404 if problem == "missing_user" else 403 if kind == "crm-role" and problem == "privileged_role" else 409
    assert response.status_code == expected, response.text
    assert gateway.calls == gateway.access_calls == []
    assert await _user_state(session, user_id) == state
    assert await session.scalar(select(func.count()).select_from(AuditLog)) == count


@pytest.mark.parametrize("outcome", ["payload_mismatch", "pending", "failed", "success_local_drift"])
async def test_role_journal_refuses_duplicate_or_uncertain_effect_without_provider_retry(
    session, crm_staff_api, outcome,
):
    api, gateway = crm_staff_api
    employee, user = await _active_sales_user(session)
    employee_id, user_id = employee.id, user.id
    operation = AuditLog(actor="director", action="identity.user.crm_role_change_requested",
                         entity_ref=f"employee:{employee_id}", detail={
                             "idempotency_key": KEY, "expected_current_role": "sales",
                             "target_role": "sales_cli" if outcome == "payload_mismatch" else "sales_head",
                         })
    session.add(operation)
    await session.flush()
    if outcome in {"failed", "success_local_drift"}:
        session.add(AuditLog(
            actor="director", entity_ref=f"employee:{employee_id}",
            action="identity.user.crm_role_change_failed" if outcome == "failed" else "identity.user.crm_role_changed",
            detail={"request_id": operation.id},
        ))
    await session.commit()
    state = await _user_state(session, user_id)
    response = await api.post(f"/system/users/{employee_id}/crm-role",
                              headers={"Idempotency-Key": KEY}, json=ROLE_COMMAND)
    assert response.status_code == 409, response.text
    assert gateway.calls == [] and await _user_state(session, user_id) == state


@pytest.mark.parametrize("problem", ["payload_mismatch", "local_drift"])
async def test_visibility_journal_is_bound_to_payload_and_current_persisted_scope(session, crm_staff_api, problem):
    api, gateway = crm_staff_api
    employee, user = await _active_sales_user(session)
    employee_id, user_id = employee.id, user.id
    session.add(AuditLog(actor="director", action="identity.user.crm_visibility_changed",
                         entity_ref=f"employee:{employee_id}", detail={
                             "idempotency_key": KEY, "previous_visibility": "all",
                             "deal_visibility": "all" if problem == "payload_mismatch" else "own",
                         }))
    await session.commit()
    state = await _user_state(session, user_id)
    response = await api.post(f"/system/users/{employee_id}/crm-visibility",
                              headers={"Idempotency-Key": KEY}, json=VISIBILITY_COMMAND)
    assert response.status_code == 409 and await _user_state(session, user_id) == state
    assert gateway.calls == gateway.access_calls == []


@pytest.mark.parametrize("error_type, expected", [(KeycloakAdminNotConfigured, 503), (KeycloakAdminConflict, 409)])
async def test_unavailable_or_conflicting_provider_effect_is_frozen_for_reconciliation(
    session, crm_staff_api, monkeypatch, error_type, expected,
):
    api, gateway = crm_staff_api
    employee, user = await _active_sales_user(session)
    employee_id, user_id = employee.id, user.id
    seen = []

    async def fail(**kwargs):
        seen.append(kwargs)
        raise error_type("synthetic_gateway_refusal")

    monkeypatch.setattr(gateway, "change_crm_role", fail)
    response = await api.post(f"/system/users/{employee_id}/crm-role",
                              headers={"Idempotency-Key": KEY}, json=ROLE_COMMAND)
    assert response.status_code == expected, response.text
    assert (await _user_state(session, user_id))[:2] == ("sales", "role_change_failed")
    for key in (KEY, KEY + "-new"):
        replay = await api.post(f"/system/users/{employee_id}/crm-role",
                                headers={"Idempotency-Key": key}, json=ROLE_COMMAND)
        assert replay.status_code == 409
    assert len(seen) == 1


@pytest.mark.parametrize("fail_at, expected", [(1, 409), (2, 502)])
async def test_role_change_commit_failure_never_claims_success_or_repeats_external_effect(
    session, crm_staff_api, monkeypatch, fail_at, expected,
):
    api, gateway = crm_staff_api
    employee, user = await _active_sales_user(session)
    employee_id, user_id = employee.id, user.id
    commit, calls = session.commit, 0

    async def guarded_commit():
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise RuntimeError("Synthetic commit failure")
        await commit()

    monkeypatch.setattr(session, "commit", guarded_commit)
    response = await api.post(f"/system/users/{employee_id}/crm-role",
                              headers={"Idempotency-Key": KEY}, json=ROLE_COMMAND)
    assert response.status_code == expected, response.text
    state = await _user_state(session, user_id)
    assert state[:2] == ("sales", "active" if fail_at == 1 else "role_changing")
    assert len(gateway.calls) == (0 if fail_at == 1 else 1)
    if fail_at == 2:
        replay = await api.post(f"/system/users/{employee_id}/crm-role",
                                headers={"Idempotency-Key": KEY}, json=ROLE_COMMAND)
        assert replay.status_code == 409 and len(gateway.calls) == 1


@pytest.mark.parametrize("drift", ["subject", "hr_status", "hr_department", "user_department"])
async def test_post_provider_drift_does_not_grant_the_requested_role(session, crm_staff_api, monkeypatch, drift):
    api, gateway = crm_staff_api
    employee, user = await _active_sales_user(session)
    employee_id, user_id = employee.id, user.id
    seen = []

    async def changed(**kwargs):
        seen.append(kwargs)
        if drift != "subject":
            await session.refresh(employee)
            await session.refresh(user)
            if drift == "hr_status":
                employee.status = "inactive"
            elif drift == "hr_department":
                employee.department = "Закупки"
            else:
                user.department = "Закупки"
            await session.commit()
        return KeycloakRoleChange(
            user_id="synthetic-wrong-subject" if drift == "subject" else kwargs["user_id"],
            role=kwargs["target_role"], effective_roles=(kwargs["target_role"], "offline_access"),
        )

    monkeypatch.setattr(gateway, "change_crm_role", changed)
    response = await api.post(f"/system/users/{employee_id}/crm-role",
                              headers={"Idempotency-Key": KEY}, json=ROLE_COMMAND)
    assert response.status_code == 409, response.text
    assert (await _user_state(session, user_id))[:2] == ("sales", "role_change_failed")
    assert len(seen) == 1
