from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from core.runtime.identity_routes import InviteEmployeeIn, _idempotency_key, _username


def test_invite_payload_normalizes_email_and_text_fields():
    payload = InviteEmployeeIn(
        employee_id=7,
        email="  User.Name@Example.BY ",
        department="  Продажи ",
        role=" sales ",
        username="  User.Name ",
    )
    assert payload.email == "user.name@example.by"
    assert payload.department == "Продажи"
    assert payload.role == "sales"
    assert payload.username == "User.Name"


@pytest.mark.parametrize("email", ["no-at", "user@", "@example.by", "user @example.by"])
def test_invite_payload_rejects_invalid_email(email):
    with pytest.raises(ValidationError, match="Некорректный email"):
        InviteEmployeeIn(employee_id=1, email=email, department="HR", role="hr")


def test_username_uses_email_or_explicit_username_and_sanitizes():
    from_email = InviteEmployeeIn(employee_id=1, email="John.Doe@example.by", department="HR", role="hr")
    assert _username(from_email) == "john.doe"
    explicit = InviteEmployeeIn(
        employee_id=1,
        email="john@example.by",
        department="HR",
        role="hr",
        username=" User Name! ",
    )
    assert _username(explicit) == "user-name"


def test_username_rejects_value_that_becomes_empty():
    payload = InviteEmployeeIn(employee_id=1, email="ab@example.by", department="HR", role="hr", username="!!")
    with pytest.raises(HTTPException) as error:
        _username(payload)
    assert error.value.status_code == 422


@pytest.mark.parametrize("value", ["short", "with space 123", "ключ-ключ-ключ"])
def test_idempotency_key_rejects_unsafe_or_short_values(value):
    request = SimpleNamespace(headers={"Idempotency-Key": value})
    with pytest.raises(HTTPException) as error:
        _idempotency_key(request)
    assert error.value.status_code == 400


def test_idempotency_key_accepts_safe_boundary_value():
    value = "A" + "x" * 11
    assert _idempotency_key(SimpleNamespace(headers={"Idempotency-Key": value})) == value
