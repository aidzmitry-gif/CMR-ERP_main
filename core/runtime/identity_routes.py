"""Управляемые identity-операции: приглашение сотрудника в Keycloak."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Protocol

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.access import DEPARTMENT_ROLES, is_role_allowed_for_department
from core.domain.models import AuditLog, User
from core.runtime.deps import get_session
from core.services.auth import CurrentUser, require_permission
from core.services.keycloak_admin import (
    KeycloakAdminClient,
    KeycloakAdminConflict,
    KeycloakAdminError,
    KeycloakAdminNotConfigured,
    KeycloakInvitation,
)
from modules.hr.models import Employee

router = APIRouter(prefix="/system/users", tags=["identity"])
SYSTEM_WRITE = "system.write"
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_USERNAME_RE = re.compile(r"[^a-z0-9._-]+")


class IdentityGateway(Protocol):
    async def invite_user(
        self, *, username: str, full_name: str, email: str, department: str, role: str
    ) -> KeycloakInvitation: ...


def get_identity_gateway(request: Request) -> IdentityGateway:
    return KeycloakAdminClient(request.app.state.core.services.config)


class InviteEmployeeIn(BaseModel):
    employee_id: int = Field(gt=0)
    email: str = Field(min_length=5, max_length=255)
    department: str = Field(min_length=2, max_length=128)
    role: str = Field(min_length=2, max_length=64)
    username: str | None = Field(default=None, min_length=2, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not _EMAIL_RE.fullmatch(value):
            raise ValueError("Некорректный email")
        return value

    @field_validator("department", "role", "username")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class InvitedEmployeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    username: str
    full_name: str
    email: str
    department: str
    role: str
    keycloak_user_id: str
    status: str
    invited_at: datetime


def _username(payload: InviteEmployeeIn) -> str:
    raw = payload.username or payload.email.split("@", 1)[0]
    username = _USERNAME_RE.sub("-", raw.lower()).strip("-._")
    if len(username) < 2:
        raise HTTPException(status_code=422, detail="Не удалось сформировать логин")
    return username


@router.get("/departments")
async def identity_departments(
    _: CurrentUser = Depends(require_permission(SYSTEM_WRITE)),
) -> dict:
    """Справочник допустимых ролей по отделам для формы приглашения."""
    return {"departments": {name: list(roles) for name, roles in DEPARTMENT_ROLES.items()}}


@router.get("/invitations", response_model=list[InvitedEmployeeOut])
async def list_invitations(
    _: CurrentUser = Depends(require_permission(SYSTEM_WRITE)),
    session: AsyncSession = Depends(get_session),
):
    return (
        await session.execute(
            select(User).where(User.employee_id.isnot(None)).order_by(User.id.desc())
        )
    ).scalars().all()


@router.post("/invite", response_model=InvitedEmployeeOut, status_code=201)
async def invite_employee(
    payload: InviteEmployeeIn,
    actor: CurrentUser = Depends(require_permission(SYSTEM_WRITE)),
    session: AsyncSession = Depends(get_session),
    identity: IdentityGateway = Depends(get_identity_gateway),
):
    """Связать HR-сотрудника с Keycloak и отправить одноразовое письмо установки пароля."""
    employee = await session.get(Employee, payload.employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    if not is_role_allowed_for_department(payload.department, payload.role):
        raise HTTPException(status_code=422, detail="Роль не разрешена для выбранного отдела")

    username = _username(payload)
    existing = (
        await session.execute(
            select(User).where(
                or_(
                    User.employee_id == employee.id,
                    User.username == username,
                    func.lower(User.email) == payload.email,
                )
            )
        )
    ).scalars().first()
    if existing is not None and existing.employee_id != employee.id:
        raise HTTPException(status_code=409, detail="Логин или email уже занят")
    if existing is not None and (
        existing.username != username
        or (existing.email or "").lower() != payload.email
        or existing.department != payload.department
        or existing.role != payload.role
    ):
        raise HTTPException(
            status_code=409,
            detail="Сотрудник уже связан с другой identity; изменение роли требует отдельной операции",
        )

    try:
        invited = await identity.invite_user(
            username=username,
            full_name=employee.full_name,
            email=payload.email,
            department=payload.department,
            role=payload.role,
        )
    except KeycloakAdminNotConfigured as exc:
        raise HTTPException(status_code=503, detail=exc.code) from exc
    except KeycloakAdminConflict as exc:
        raise HTTPException(status_code=409, detail=exc.code) from exc
    except KeycloakAdminError as exc:
        raise HTTPException(status_code=502, detail=exc.code) from exc

    now = datetime.now(UTC).replace(tzinfo=None)
    user = existing or User(username=username, full_name=employee.full_name)
    user.username = username
    user.full_name = employee.full_name
    user.email = payload.email
    user.employee_id = employee.id
    user.department = payload.department
    user.role = payload.role
    user.keycloak_user_id = invited.user_id
    user.status = "invited"
    user.invited_at = now
    employee.department = payload.department
    if existing is None:
        session.add(user)
    session.add(
        AuditLog(
            actor=actor.username,
            action="identity.user.invited",
            entity_ref=f"employee:{employee.id}",
            detail={
                "username": username,
                "email": payload.email,
                "department": payload.department,
                "role": payload.role,
                "keycloak_reused": invited.reused,
            },
        )
    )
    await session.commit()
    await session.refresh(user)
    return user
