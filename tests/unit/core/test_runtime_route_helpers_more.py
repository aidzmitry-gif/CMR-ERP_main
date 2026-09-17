from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from sqlalchemy import Date, String

from core.runtime import identity_routes, reference_routes, system_routes


def test_quality_by_kind_keeps_dashboard_defaults_and_accumulates_unknown_kind():
    result = system_routes._quality_by_kind(
        [
            {"kind": "missing", "count": 2},
            {"kind": "missing", "count": 3},
            {"kind": "custom", "count": 1},
        ]
    )

    assert result == {
        "missing": 5,
        "duplicate": 0,
        "broken_ref": 0,
        "orphan": 0,
        "custom": 1,
    }


def test_reference_row_and_coerce_only_convert_declared_date_columns():
    record = SimpleNamespace(code="BYN", title="Белорусский рубль", ignored="x")
    assert reference_routes._row(record, ("code", "title")) == {
        "code": "BYN",
        "title": "Белорусский рубль",
    }

    model = SimpleNamespace(
        __table__=SimpleNamespace(
            columns={
                "as_of": SimpleNamespace(type=Date()),
                "title": SimpleNamespace(type=String()),
            }
        )
    )
    assert reference_routes._coerce(model, "as_of", "2026-09-17") == date(2026, 9, 17)
    assert reference_routes._coerce(model, "as_of", "2026-02-30") == "2026-02-30"
    assert reference_routes._coerce(model, "title", "2026-09-17") == "2026-09-17"
    assert reference_routes._coerce(model, "as_of", date(2026, 9, 17)) == date(2026, 9, 17)


def _invite_payload(**changes):
    values = {
        "employee_id": 7,
        "email": "user@example.com",
        "department": "Продажи",
        "role": "sales",
        "username": "user",
    }
    values.update(changes)
    return identity_routes.InviteEmployeeIn(**values)


def test_identity_payload_comparisons_reject_one_field_mismatch():
    payload = _invite_payload()
    user = SimpleNamespace(
        username="user",
        email="user@example.com",
        department=None,
        role="onboarding",
        expected_department="Продажи",
        expected_role="sales",
    )
    request = SimpleNamespace(
        employee_id=7,
        username="user",
        email="USER@example.com",
        department="Продажи",
        role="sales",
    )

    assert identity_routes._same_user_payload(user, payload, "user")
    assert identity_routes._same_request_payload(request, payload, "user")
    assert not identity_routes._same_user_payload(user, _invite_payload(role="manager"), "user")
    assert not identity_routes._same_request_payload(request, _invite_payload(department="HR"), "user")


def test_identity_idempotency_key_strips_and_accepts_maximum_safe_length():
    key = "k" * 128
    request = SimpleNamespace(headers={"Idempotency-Key": f"  {key}  "})

    assert identity_routes._idempotency_key(request) == key


def test_same_activation_request_requires_every_expected_identity_field():
    activation = SimpleNamespace(
        user_id=11,
        employee_id=7,
        expected_department="Продажи",
        expected_role="sales",
    )
    user = SimpleNamespace(
        id=11,
        employee_id=7,
        expected_department="Продажи",
        expected_role="sales",
    )

    assert identity_routes._same_activation_request(activation, user)
    assert not identity_routes._same_activation_request(
        SimpleNamespace(**{**activation.__dict__, "expected_role": "manager"}), user
    )
