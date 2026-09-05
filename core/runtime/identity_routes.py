"""Управляемые identity-операции: безопасное приглашение сотрудника в Keycloak."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import blake2b
from typing import Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config.access import (
    ACCESS_MATRIX,
    DEPARTMENT_ROLES,
    ONBOARDING_ROLE,
    ROLE_TITLES,
    is_role_allowed_for_department,
    is_super,
)
from core.domain.models import (
    AuditLog,
    IdentityAccessActivationRequest,
    IdentityInvitationRequest,
    User,
)
from core.runtime.deps import get_session
from core.services.auth import CurrentUser, require_permission
from core.services.keycloak_admin import (
    KeycloakAdminClient,
    KeycloakAdminConflict,
    KeycloakAdminError,
    KeycloakAdminNotConfigured,
    KeycloakInvitation,
    KeycloakRoleChange,
)
from modules.hr.models import Employee

router = APIRouter(prefix="/system/users", tags=["identity"])
# Действия разделены намеренно: технический aios-inviter может подготовить и
# отправить ровно одно приглашение, но не читать реестр всех сотрудников и
# приглашений. Директор/коммерческий директор остаются супер-ролями.
IDENTITY_INVITE_PREPARE = "identity.invite.prepare"
IDENTITY_INVITE_SEND = "identity.invite.send"
IDENTITY_INVITE_READ = "identity.invite.read"
# Только супер-роли получают это право через ``has_permission``. Технический
# inviter им не обладает: он не может сам превратить onboarding в доступ к данным.
IDENTITY_INVITE_ACTIVATE = "identity.invite.activate"
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_USERNAME_RE = re.compile(r"[^a-z0-9._-]+")
_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{11,127}$")
CRM_DEPARTMENT = "Продажи"
CRM_STAFF_ROLES: tuple[str, ...] = ("sales_head", "sales", "sales_cli")


class IdentityGateway(Protocol):
    async def invite_user(
        self,
        *,
        username: str,
        full_name: str,
        email: str,
        expected_department: str,
        expected_role: str,
    ) -> KeycloakInvitation: ...

    async def stage_activation_target(self, *, user_id: str, expected_role: str) -> object: ...

    async def remove_onboarding_role(self, *, user_id: str) -> None: ...

    async def change_crm_role(
        self, *, user_id: str, current_role: str, target_role: str
    ) -> KeycloakRoleChange: ...


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
    department: str | None
    role: str
    expected_department: str
    expected_role: str
    keycloak_user_id: str
    status: str
    invited_at: datetime


class InvitationPreflightOut(BaseModel):
    """Результат проверки без обращения к Keycloak и без отправки письма."""

    employee_id: int
    full_name: str
    username: str
    email: str
    department: str
    role: str
    ready: bool


class ActivatedEmployeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    username: str
    department: str
    role: str
    status: str


class CrmStaffCreateIn(BaseModel):
    """Минимальная HR-карточка для дальнейшего CRM-приглашения.

    Адрес и Keycloak не попадают в эту операцию: e-mail сначала проходит
    существующий preflight/invite с явным подтверждением отправки.
    """

    full_name: str = Field(min_length=2, max_length=255)
    position: str | None = Field(default=None, max_length=255)

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Укажите ФИО сотрудника")
        return value

    @field_validator("position")
    @classmethod
    def normalize_position(cls, value: str | None) -> str | None:
        value = value.strip() if value is not None else None
        return value or None


class CrmRoleOptionOut(BaseModel):
    slug: str
    label: str
    modules: list[str]
    capabilities: list[str]


class CrmStaffOut(BaseModel):
    employee_id: int
    full_name: str
    department: str
    position: str | None
    employee_status: str | None
    email: str | None
    username: str | None
    user_status: str | None
    role: str | None
    deal_visibility: Literal["all", "own"]
    allowed_roles: list[CrmRoleOptionOut]
    created: bool = False


class CrmRoleChangeIn(BaseModel):
    role: str = Field(min_length=2, max_length=64)
    expected_current_role: str = Field(min_length=2, max_length=64)

    @field_validator("role", "expected_current_role")
    @classmethod
    def strip_role(cls, value: str) -> str:
        return value.strip()


class CrmRoleChangeOut(BaseModel):
    employee_id: int
    previous_role: str
    role: str
    status: str
    operation_id: int


class CrmVisibilityChangeIn(BaseModel):
    deal_visibility: Literal["all", "own"]
    expected_current_visibility: Literal["all", "own"]


class CrmVisibilityChangeOut(BaseModel):
    employee_id: int
    previous_visibility: Literal["all", "own"]
    deal_visibility: Literal["all", "own"]
    status: str
    operation_id: int


class IdentityOperationOut(BaseModel):
    """Безопасная операторская проекция журнала identity-изменений.

    В ответ намеренно не попадают технические идентификаторы Keycloak,
    idempotency-ключи и иные значения, позволяющие повторить внешний эффект.
    """

    operation_kind: Literal["invite", "activation"]
    request_id: int
    employee_id: int
    full_name: str | None
    email: str | None
    username: str | None
    target_department: str
    target_role: str
    status: str
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None
    requires_reconciliation: bool


@dataclass(frozen=True)
class _ResolvedInvitation:
    employee: Employee
    username: str
    existing_user: User | None


def _username(payload: InviteEmployeeIn) -> str:
    raw = payload.username or payload.email.split("@", 1)[0]
    username = _USERNAME_RE.sub("-", raw.lower()).strip("-._")
    if len(username) < 2:
        raise HTTPException(status_code=422, detail="Не удалось сформировать логин")
    return username


def _same_user_payload(user: User, payload: InviteEmployeeIn, username: str) -> bool:
    return (
        user.username == username
        and (user.email or "").lower() == payload.email
        and user.department is None
        and user.role == ONBOARDING_ROLE
        and user.expected_department == payload.department
        and user.expected_role == payload.role
    )


def _same_request_payload(
    invite: IdentityInvitationRequest, payload: InviteEmployeeIn, username: str
) -> bool:
    return (
        invite.employee_id == payload.employee_id
        and invite.username == username
        and invite.email.lower() == payload.email
        and invite.department == payload.department
        and invite.role == payload.role
    )


def _idempotency_key(request: Request) -> str:
    value = request.headers.get("Idempotency-Key", "").strip()
    if not _IDEMPOTENCY_KEY_RE.fullmatch(value):
        raise HTTPException(
            status_code=400,
            detail="Для отправки нужен Idempotency-Key длиной 12–128 безопасных символов",
        )
    return value


async def _resolve_invitation(
    session: AsyncSession, payload: InviteEmployeeIn, *, lock_employee: bool = False
) -> _ResolvedInvitation:
    """Проверить HR-сотрудника и локальные конфликты до внешнего эффекта."""

    employee_query = select(Employee).where(Employee.id == payload.employee_id)
    if lock_employee:
        # PostgreSQL сериализует две конкурентные отправки одному сотруднику.
        # SQLite в тестах игнорирует FOR UPDATE, но логика остаётся корректной.
        employee_query = employee_query.with_for_update()
    employee = (await session.execute(employee_query)).scalar_one_or_none()
    if employee is None:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    if (employee.status or "").strip().lower() != "active":
        raise HTTPException(
            status_code=409,
            detail="Приглашение возможно только для активного сотрудника HR",
        )
    employee_department = (employee.department or "").strip()
    if not employee_department:
        raise HTTPException(
            status_code=422,
            detail="Сначала укажите отдел сотрудника в HR; inviter его не изменяет",
        )
    if employee_department != payload.department:
        raise HTTPException(
            status_code=422,
            detail="Отдел приглашения должен совпадать с отделом сотрудника в HR",
        )
    if not is_role_allowed_for_department(payload.department, payload.role):
        raise HTTPException(status_code=422, detail="Роль не разрешена для выбранного отдела")

    username = _username(payload)
    matches = (
        (
            await session.execute(
                select(User).where(
                    or_(
                        User.employee_id == employee.id,
                        User.username == username,
                        func.lower(User.email) == payload.email,
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    current = next((user for user in matches if user.employee_id == employee.id), None)
    if any(user.employee_id != employee.id for user in matches):
        raise HTTPException(status_code=409, detail="Логин или email уже занят")
    if current is not None and not _same_user_payload(current, payload, username):
        raise HTTPException(
            status_code=409,
            detail="Сотрудник уже связан с другой identity; изменение роли требует отдельной операции",
        )
    return _ResolvedInvitation(employee=employee, username=username, existing_user=current)


async def _failed_request(
    session: AsyncSession,
    invite: IdentityInvitationRequest | IdentityAccessActivationRequest,
    *,
    actor: CurrentUser,
    code: str,
) -> None:
    """Зафиксировать неуспешный внешний эффект без секретов и PII."""

    invite.status = "failed"
    invite.error_code = code
    session.add(
        AuditLog(
            actor=actor.username,
            action=(
                "identity.user.invitation_failed"
                if isinstance(invite, IdentityInvitationRequest)
                else "identity.user.activation_failed"
            ),
            entity_ref=f"employee:{invite.employee_id}",
            detail={"request_id": invite.id, "error_code": code},
        )
    )
    await session.commit()


async def _request_result_user(session: AsyncSession, invite: IdentityInvitationRequest) -> User:
    if invite.status != "sent" or invite.user_id is None:
        raise HTTPException(
            status_code=409,
            detail="Приглашение уже обрабатывается или требует ручной сверки; повтор не отправлен",
        )
    user = await session.get(User, invite.user_id)
    if user is None:
        raise HTTPException(
            status_code=409,
            detail="Журнал приглашения требует ручной сверки; повтор не отправлен",
        )
    return user


def _same_activation_request(activation: IdentityAccessActivationRequest, user: User) -> bool:
    return (
        activation.user_id == user.id
        and activation.employee_id == user.employee_id
        and activation.expected_department == user.expected_department
        and activation.expected_role == user.expected_role
    )


async def _activation_result_user(
    session: AsyncSession, activation: IdentityAccessActivationRequest
) -> User:
    if activation.status != "succeeded":
        raise HTTPException(
            status_code=409,
            detail="Активация уже обрабатывается или требует ручной сверки; повтор не выполнен",
        )
    user = await session.get(User, activation.user_id)
    if (
        user is None
        or user.status != "active"
        or not user.department
        or not user.role
        or user.department != activation.expected_department
        or user.role != activation.expected_role
        or user.expected_department is not None
        or user.expected_role is not None
    ):
        raise HTTPException(
            status_code=409,
            detail="Журнал активации не согласован с пользователем; требуется ручная сверка",
        )
    return user


def _crm_role_options() -> list[CrmRoleOptionOut]:
    """Узкая проекция разрешённых ролей CRM без полной матрицы организации."""

    return [
        CrmRoleOptionOut(
            slug=role,
            label=ROLE_TITLES[role],
            modules=list(ACCESS_MATRIX[role]),
            capabilities=(
                ["sales.deal.read", "sales.deal.write", "sales.deal.approve"]
                if role == "sales_head"
                else ["sales.deal.read", "sales.deal.write"]
            ),
        )
        for role in CRM_STAFF_ROLES
    ]


def _has_unsafe_effective_crm_roles(effective_roles: tuple[str, ...], target_role: str) -> bool:
    """Defence in depth for gateway fakes and future client implementations."""

    system_roles = {"offline_access", "uma_authorization", "default-roles-aios"}
    roles = set(effective_roles)
    return (
        target_role not in roles
        or ONBOARDING_ROLE in roles
        or "identity_provisioner" in roles
        or bool(roles - system_roles - {target_role})
    )


def _crm_staff_out(employee: Employee, user: User | None, *, created: bool = False) -> CrmStaffOut:
    return CrmStaffOut(
        employee_id=employee.id,
        full_name=employee.full_name,
        department=CRM_DEPARTMENT,
        position=employee.position,
        employee_status=employee.status,
        email=user.email if user else None,
        username=user.username if user else None,
        user_status=user.status if user else None,
        role=user.role if user else None,
        # Legacy rows receive the safe product default until migration 0111 has
        # materialised it.  New code writes the constrained model field.
        deal_visibility=(getattr(user, "deal_visibility", "all") if user else "all"),
        allowed_roles=_crm_role_options(),
        created=created,
    )


async def _role_change_outcome(
    session: AsyncSession, *, request_id: int, employee_id: int
) -> AuditLog | None:
    """Найти терминальный audit outcome одного внешнего role-change намерения."""

    outcomes = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.entity_ref == f"employee:{employee_id}",
                AuditLog.action.in_(
                    {"identity.user.crm_role_changed", "identity.user.crm_role_change_failed"}
                ),
            )
        )
    ).scalars()
    return next(
        (
            event
            for event in outcomes
            if isinstance(event.detail, dict) and event.detail.get("request_id") == request_id
        ),
        None,
    )


async def _record_crm_role_change_failure(
    session: AsyncSession,
    *,
    actor: CurrentUser,
    employee_id: int,
    request_id: int,
    code: str,
) -> None:
    """Не маскировать неопределённый внешний эффект локальным успехом."""

    user = (
        await session.execute(select(User).where(User.employee_id == employee_id).with_for_update())
    ).scalar_one_or_none()
    # The application auth guard treats this durable status as fail-closed.  Do
    # not restore `active`: a timeout can mean Keycloak already changed roles.
    if user is not None and user.status == "role_changing":
        user.status = "role_change_failed"
    session.add(
        AuditLog(
            actor=actor.username,
            action="identity.user.crm_role_change_failed",
            entity_ref=f"employee:{employee_id}",
            detail={"request_id": request_id, "error_code": code, "requires_reconciliation": True},
        )
    )
    await session.commit()


async def _lock_crm_staff_name(session: AsyncSession, full_name: str) -> None:
    """Serialize same-name CRM card creation on Postgres without a schema change."""

    bind = session.bind
    if bind is None or bind.dialect.name != "postgresql":
        return
    # A stable signed bigint is required by pg_advisory_xact_lock.  It is an
    # implementation lock only; no PII is stored in the database or audit.
    digest = blake2b(
        f"crm-staff:{full_name.casefold()}".encode("utf-8"), digest_size=8
    ).digest()
    lock_key = int.from_bytes(digest, byteorder="big", signed=True)
    await session.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})


@router.get("/departments")
async def identity_departments(
    _: CurrentUser = Depends(require_permission(IDENTITY_INVITE_PREPARE)),
) -> dict:
    """Справочник допустимых ролей по отделам для preflight клиента."""
    return {"departments": {name: list(roles) for name, roles in DEPARTMENT_ROLES.items()}}


@router.get("/crm-staff", response_model=list[CrmStaffOut])
async def list_crm_staff(
    actor: CurrentUser = Depends(require_permission(IDENTITY_INVITE_READ)),
    session: AsyncSession = Depends(get_session),
):
    """Минимальный реестр сотрудников отдела CRM для оператора доступа.

    Первоначально endpoint доступен только супер-ролям: технический inviter не
    получает кадровый реестр и не может читать e-mail других сотрудников.
    """

    if not is_super(actor.roles):
        raise HTTPException(status_code=403, detail="CRM-реестр доступен только руководителю доступа")
    rows = (
        await session.execute(
            select(Employee, User)
            .outerjoin(User, User.employee_id == Employee.id)
            .where(Employee.department == CRM_DEPARTMENT)
            .order_by(Employee.full_name, Employee.id)
        )
    ).all()
    return [_crm_staff_out(employee, user) for employee, user in rows]


@router.post("/crm-staff", response_model=CrmStaffOut, status_code=201)
async def create_crm_staff(
    payload: CrmStaffCreateIn,
    actor: CurrentUser = Depends(require_permission(IDENTITY_INVITE_ACTIVATE)),
    session: AsyncSession = Depends(get_session),
):
    """Создать только HR-карточку активного сотрудника отдела CRM.

    Здесь нет Keycloak, пароля, письма или роли. Поэтому ошибка в ФИО не
    создаёт учётную запись и может быть безопасно исправлена до preflight.
    """

    if not is_super(actor.roles):
        raise HTTPException(status_code=403, detail="Создание CRM-сотрудника доступно только руководителю доступа")
    await _lock_crm_staff_name(session, payload.full_name)
    # Сравнение после выборки намеренно casefold(), а не DB-specific lower():
    # кириллический LOWER в SQLite (контрактных тестах) не эквивалентен Postgres.
    candidates = (
        await session.execute(
            select(Employee).where(Employee.department == CRM_DEPARTMENT).with_for_update()
        )
    ).scalars()
    existing = next(
        (employee for employee in candidates if employee.full_name.strip().casefold() == payload.full_name.casefold()),
        None,
    )
    if existing is not None:
        # Повтор UI не создаёт вторую кадровую карточку и не меняет первую.
        user = (
            await session.execute(select(User).where(User.employee_id == existing.id))
        ).scalar_one_or_none()
        return _crm_staff_out(existing, user, created=False)

    employee = Employee(
        full_name=payload.full_name,
        position=payload.position,
        department=CRM_DEPARTMENT,
        status="active",
    )
    session.add(employee)
    try:
        await session.flush()
        session.add(
            AuditLog(
                actor=actor.username,
                action="identity.crm_staff.created",
                entity_ref=f"employee:{employee.id}",
                detail={"department": CRM_DEPARTMENT, "position": employee.position},
            )
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="CRM-сотрудник уже существует") from exc
    await session.refresh(employee)
    return _crm_staff_out(employee, None, created=True)


@router.post("/{employee_id}/crm-role", response_model=CrmRoleChangeOut)
async def change_crm_role(
    employee_id: int,
    payload: CrmRoleChangeIn,
    request: Request,
    actor: CurrentUser = Depends(require_permission(IDENTITY_INVITE_ACTIVATE)),
    session: AsyncSession = Depends(get_session),
    identity: IdentityGateway = Depends(get_identity_gateway),
):
    """Сменить подтверждённую рабочую CRM-роль активного сотрудника.

    Операция фиксирует намерение до Keycloak и не повторяет uncertain external
    effect.  Она не умеет менять отдел, onboarding, технические или
    привилегированные роли и не редактирует самого оператора.
    """

    if not is_super(actor.roles):
        raise HTTPException(status_code=403, detail="Смена CRM-роли доступна только руководителю доступа")
    if payload.role not in CRM_STAFF_ROLES or payload.expected_current_role not in CRM_STAFF_ROLES:
        raise HTTPException(status_code=422, detail="Разрешены только роли CRM: РОП, продажи, работа с клиентами")
    if payload.role == payload.expected_current_role:
        raise HTTPException(status_code=409, detail="Выбрана текущая CRM-роль; изменение не выполнено")
    idempotency_key = _idempotency_key(request)
    user = (
        await session.execute(select(User).where(User.employee_id == employee_id).with_for_update())
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Связанный CRM-пользователь не найден")
    if user.username == actor.username:
        raise HTTPException(status_code=403, detail="Нельзя менять собственный доступ через эту операцию")
    if user.role in {"admin", "director", "commercial"}:
        raise HTTPException(status_code=403, detail="Нельзя менять доступ привилегированного пользователя")
    if user.department != CRM_DEPARTMENT or user.role not in CRM_STAFF_ROLES or not user.keycloak_user_id:
        raise HTTPException(status_code=409, detail="Рабочий CRM-доступ не согласован; требуется ручная сверка")
    employee = (
        await session.execute(select(Employee).where(Employee.id == employee_id).with_for_update())
    ).scalar_one_or_none()
    if (
        employee is None
        or (employee.status or "").strip().lower() != "active"
        or (employee.department or "").strip() != CRM_DEPARTMENT
    ):
        raise HTTPException(status_code=409, detail="CRM-сотрудник не активен в HR; требуется ручная сверка")
    previous_requests = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.action == "identity.user.crm_role_change_requested",
                AuditLog.entity_ref == f"employee:{employee_id}",
            )
        )
    ).scalars().all()
    same_request = next(
        (
            event
            for event in previous_requests
            if isinstance(event.detail, dict) and event.detail.get("idempotency_key") == idempotency_key
        ),
        None,
    )
    if same_request is not None:
        if (
            same_request.detail.get("target_role") != payload.role
            or same_request.detail.get("expected_current_role") != payload.expected_current_role
        ):
            raise HTTPException(status_code=409, detail="Idempotency-Key уже использован с другими данными")
        outcome = await _role_change_outcome(
            session, request_id=same_request.id, employee_id=employee_id
        )
        if outcome is None or outcome.action != "identity.user.crm_role_changed":
            raise HTTPException(
                status_code=409,
                detail="Смена роли уже обрабатывается или требует ручной сверки; повтор не выполнен",
            )
        if user.role != payload.role:
            raise HTTPException(status_code=409, detail="Журнал смены роли не согласован; требуется ручная сверка")
        return CrmRoleChangeOut(
            employee_id=employee_id,
            previous_role=payload.expected_current_role,
            role=payload.role,
            status="succeeded",
            operation_id=same_request.id,
        )

    # A prior external operation without a confirmed local success is never
    # retried under another key.  It may already have altered Keycloak.
    for previous in previous_requests:
        outcome = await _role_change_outcome(session, request_id=previous.id, employee_id=employee_id)
        if outcome is None or outcome.action != "identity.user.crm_role_changed":
            raise HTTPException(
                status_code=409,
                detail="Есть незавершённая смена роли; требуется ручная сверка",
            )
    if user.status != "active":
        raise HTTPException(status_code=409, detail="Рабочий CRM-доступ не согласован; требуется ручная сверка")
    if user.role != payload.expected_current_role:
        raise HTTPException(status_code=409, detail="Текущая роль уже изменилась; обновите карточку сотрудника")

    operation = AuditLog(
        actor=actor.username,
        action="identity.user.crm_role_change_requested",
        entity_ref=f"employee:{employee_id}",
        detail={
            "idempotency_key": idempotency_key,
            "target_role": payload.role,
            "expected_current_role": payload.expected_current_role,
            "status": "sending",
        },
    )
    session.add(operation)
    # Persist a fail-closed freeze before the first external call.  Root auth
    # accepts only active/onboarding local states, so role_changing has no API
    # access even if an old Keycloak token still contains the former role.
    user.status = "role_changing"
    keycloak_user_id = user.keycloak_user_id
    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Не удалось зафиксировать операцию смены роли") from exc

    try:
        result = await identity.change_crm_role(
            user_id=keycloak_user_id,
            current_role=payload.expected_current_role,
            target_role=payload.role,
        )
    except KeycloakAdminNotConfigured as exc:
        await _record_crm_role_change_failure(
            session, actor=actor, employee_id=employee_id, request_id=operation.id, code=exc.code
        )
        raise HTTPException(status_code=503, detail=exc.code) from exc
    except KeycloakAdminConflict as exc:
        await _record_crm_role_change_failure(
            session, actor=actor, employee_id=employee_id, request_id=operation.id, code=exc.code
        )
        raise HTTPException(status_code=409, detail="identity_role_change_reconciliation_required") from exc
    except KeycloakAdminError as exc:
        await _record_crm_role_change_failure(
            session, actor=actor, employee_id=employee_id, request_id=operation.id, code=exc.code
        )
        raise HTTPException(status_code=502, detail="identity_role_change_reconciliation_required") from exc

    # Commit выше снял блокировку. Не оптимистично обновляем локальную роль:
    # сперва убеждаемся, что Keycloak подтвердил ровно допустимое множество и
    # что HR/local user не были изменены параллельно.
    user = (
        await session.execute(
            select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    employee = (
        await session.execute(
            select(Employee).where(Employee.id == employee_id).with_for_update().execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if (
        user is None
        or user.status != "role_changing"
        or user.department != CRM_DEPARTMENT
        or user.role != payload.expected_current_role
        or user.keycloak_user_id != result.user_id
        or _has_unsafe_effective_crm_roles(result.effective_roles, payload.role)
        or employee is None
        or (employee.status or "").strip().lower() != "active"
        or (employee.department or "").strip() != CRM_DEPARTMENT
    ):
        await _record_crm_role_change_failure(
            session,
            actor=actor,
            employee_id=employee_id,
            request_id=operation.id,
            code="identity_crm_role_change_state_drift",
        )
        raise HTTPException(status_code=409, detail="Роль изменилась во время операции; требуется ручная сверка")

    user.role = payload.role
    user.status = "active"
    session.add(
        AuditLog(
            actor=actor.username,
            action="identity.user.crm_role_changed",
            entity_ref=f"employee:{employee_id}",
            detail={
                "request_id": operation.id,
                "previous_role": payload.expected_current_role,
                "role": payload.role,
                "keycloak_roles_verified": True,
                "sessions_revoked": True,
            },
        )
    )
    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise HTTPException(status_code=502, detail="identity_role_change_reconciliation_required") from exc
    return CrmRoleChangeOut(
        employee_id=employee_id,
        previous_role=payload.expected_current_role,
        role=payload.role,
        status="succeeded",
        operation_id=operation.id,
    )


@router.post("/{employee_id}/crm-visibility", response_model=CrmVisibilityChangeOut)
async def change_crm_visibility(
    employee_id: int,
    payload: CrmVisibilityChangeIn,
    request: Request,
    actor: CurrentUser = Depends(require_permission(IDENTITY_INVITE_ACTIVATE)),
    session: AsyncSession = Depends(get_session),
):
    """Изменить только область видимости сделок активного CRM-сотрудника.

    Это локальная policy-настройка: роли Keycloak, отдел и другие access
    attributes не меняются.  Смена журналируется вместе с записью, поэтому
    idempotency не нуждается во внешнем retry и не создаёт второй эффект.
    """

    if not is_super(actor.roles):
        raise HTTPException(status_code=403, detail="Смена видимости CRM доступна только руководителю доступа")
    idempotency_key = _idempotency_key(request)
    user = (
        await session.execute(select(User).where(User.employee_id == employee_id).with_for_update())
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Связанный CRM-пользователь не найден")
    if user.username == actor.username:
        raise HTTPException(status_code=403, detail="Нельзя менять собственную видимость через эту операцию")
    if (
        user.status != "active"
        or user.department != CRM_DEPARTMENT
        or user.role not in CRM_STAFF_ROLES
    ):
        raise HTTPException(status_code=409, detail="Рабочий CRM-доступ не согласован; требуется ручная сверка")
    employee = (
        await session.execute(select(Employee).where(Employee.id == employee_id).with_for_update())
    ).scalar_one_or_none()
    if (
        employee is None
        or (employee.status or "").strip().lower() != "active"
        or (employee.department or "").strip() != CRM_DEPARTMENT
    ):
        raise HTTPException(status_code=409, detail="CRM-сотрудник не активен в HR; требуется ручная сверка")
    current_visibility = getattr(user, "deal_visibility", "all")
    if current_visibility not in {"all", "own"}:
        raise HTTPException(status_code=409, detail="Видимость сделок не согласована; требуется ручная сверка")

    prior = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.action == "identity.user.crm_visibility_changed",
                AuditLog.entity_ref == f"employee:{employee_id}",
            )
        )
    ).scalars()
    same_operation = next(
        (
            event
            for event in prior
            if isinstance(event.detail, dict) and event.detail.get("idempotency_key") == idempotency_key
        ),
        None,
    )
    if same_operation is not None:
        if (
            same_operation.detail.get("previous_visibility") != payload.expected_current_visibility
            or same_operation.detail.get("deal_visibility") != payload.deal_visibility
        ):
            raise HTTPException(status_code=409, detail="Idempotency-Key уже использован с другими данными")
        if current_visibility != payload.deal_visibility:
            raise HTTPException(status_code=409, detail="Журнал видимости не согласован; требуется ручная сверка")
        return CrmVisibilityChangeOut(
            employee_id=employee_id,
            previous_visibility=payload.expected_current_visibility,
            deal_visibility=payload.deal_visibility,
            status="succeeded",
            operation_id=same_operation.id,
        )
    if current_visibility != payload.expected_current_visibility:
        raise HTTPException(status_code=409, detail="Видимость уже изменилась; обновите карточку сотрудника")
    if current_visibility == payload.deal_visibility:
        raise HTTPException(status_code=409, detail="Выбрана текущая видимость; изменение не выполнено")
    if not hasattr(user, "deal_visibility"):
        # Защита от запуска endpoint до миграции: не имитируем успешную
        # настройку, которую приложение не сумеет сохранить после рестарта.
        raise HTTPException(status_code=503, detail="crm_visibility_storage_not_migrated")

    user.deal_visibility = payload.deal_visibility
    operation = AuditLog(
        actor=actor.username,
        action="identity.user.crm_visibility_changed",
        entity_ref=f"employee:{employee_id}",
        detail={
            "idempotency_key": idempotency_key,
            "previous_visibility": current_visibility,
            "deal_visibility": payload.deal_visibility,
        },
    )
    session.add(operation)
    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise HTTPException(status_code=502, detail="crm_visibility_reconciliation_required") from exc
    return CrmVisibilityChangeOut(
        employee_id=employee_id,
        previous_visibility=current_visibility,
        deal_visibility=payload.deal_visibility,
        status="succeeded",
        operation_id=operation.id,
    )


@router.get("/invitations", response_model=list[InvitedEmployeeOut])
async def list_invitations(
    _: CurrentUser = Depends(require_permission(IDENTITY_INVITE_READ)),
    session: AsyncSession = Depends(get_session),
):
    return (
        (
            await session.execute(
                # Это экран только ожидающих onboarding-приглашений. Legacy active
                # users may have NULL expected_* and не соответствуют контракту
                # InvitedEmployeeOut.
                select(User).where(User.status == "onboarding").order_by(User.id.desc())
            )
        )
        .scalars()
        .all()
    )


@router.get("/invitation-operations", response_model=list[IdentityOperationOut])
async def list_invitation_operations(
    _: CurrentUser = Depends(require_permission(IDENTITY_INVITE_READ)),
    session: AsyncSession = Depends(get_session),
):
    """Показать до 100 последних безопасных записей пригласительных операций.

    ``sending``, ``failed`` и ``cleanup_pending`` означают возможный внешний
    эффект без окончательной локальной сверки, поэтому оператору явно
    возвращается ``requires_reconciliation``.
    """

    invitations = (
        await session.execute(
            select(IdentityInvitationRequest, Employee.full_name)
            .outerjoin(Employee, Employee.id == IdentityInvitationRequest.employee_id)
            .order_by(IdentityInvitationRequest.created_at.desc())
            .limit(100)
        )
    ).all()
    activations = (
        await session.execute(
            select(IdentityAccessActivationRequest, User)
            .join(User, User.id == IdentityAccessActivationRequest.user_id)
            .order_by(IdentityAccessActivationRequest.created_at.desc())
            .limit(100)
        )
    ).all()

    reconciliation_statuses = {"sending", "failed", "cleanup_pending"}
    operations = [
        IdentityOperationOut(
            operation_kind="invite",
            request_id=invite.id,
            employee_id=invite.employee_id,
            full_name=full_name,
            email=invite.email,
            username=invite.username,
            target_department=invite.department,
            target_role=invite.role,
            status=invite.status,
            error_code=invite.error_code,
            created_at=invite.created_at,
            completed_at=invite.sent_at,
            requires_reconciliation=invite.status in reconciliation_statuses,
        )
        for invite, full_name in invitations
    ]
    operations.extend(
        IdentityOperationOut(
            operation_kind="activation",
            request_id=activation.id,
            employee_id=activation.employee_id,
            full_name=user.full_name,
            email=user.email,
            username=user.username,
            target_department=activation.expected_department,
            target_role=activation.expected_role,
            status=activation.status,
            error_code=activation.error_code,
            created_at=activation.created_at,
            completed_at=activation.activated_at,
            requires_reconciliation=activation.status in reconciliation_statuses,
        )
        for activation, user in activations
    )
    return sorted(operations, key=lambda operation: operation.created_at, reverse=True)[:100]


@router.post("/preflight", response_model=InvitationPreflightOut)
async def preflight_invitation(
    payload: InviteEmployeeIn,
    _: CurrentUser = Depends(require_permission(IDENTITY_INVITE_PREPARE)),
    session: AsyncSession = Depends(get_session),
):
    """Проверка пригласительного payload без записи в БД и без Keycloak-вызова."""

    resolved = await _resolve_invitation(session, payload)
    return InvitationPreflightOut(
        employee_id=resolved.employee.id,
        full_name=resolved.employee.full_name,
        username=resolved.username,
        email=payload.email,
        department=payload.department,
        role=payload.role,
        ready=resolved.existing_user is None,
    )


@router.post("/invite", response_model=InvitedEmployeeOut, status_code=201)
async def invite_employee(
    payload: InviteEmployeeIn,
    request: Request,
    actor: CurrentUser = Depends(require_permission(IDENTITY_INVITE_SEND)),
    session: AsyncSession = Depends(get_session),
    identity: IdentityGateway = Depends(get_identity_gateway),
):
    """Связать HR-сотрудника с Keycloak и отправить одноразовое письмо установки пароля.

    Письмо запускается максимум один раз для сотрудника. Каждый внешний вызов
    требует Idempotency-Key: повтор того же запроса вернёт прежний результат,
    а неопределённый сетевой исход блокируется до ручной сверки.
    """

    idempotency_key = _idempotency_key(request)
    resolved = await _resolve_invitation(session, payload, lock_employee=True)

    same_key = (
        await session.execute(
            select(IdentityInvitationRequest)
            .where(IdentityInvitationRequest.idempotency_key == idempotency_key)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if same_key is not None:
        if not _same_request_payload(same_key, payload, resolved.username):
            raise HTTPException(
                status_code=409,
                detail="Idempotency-Key уже использован с другими данными приглашения",
            )
        return await _request_result_user(session, same_key)

    # Устаревшая либо уже отправленная заявка никогда не инициирует второе
    # письмо автоматически. Это также делает старые записи app_user безопасными.
    if resolved.existing_user is not None:
        if (
            resolved.existing_user.status == "onboarding"
            and resolved.existing_user.keycloak_user_id
            and resolved.existing_user.invited_at
        ):
            return resolved.existing_user
        raise HTTPException(
            status_code=409,
            detail="Сотрудник уже связан с identity и требует ручной сверки; повтор не отправлен",
        )

    employee_request = (
        await session.execute(
            select(IdentityInvitationRequest)
            .where(IdentityInvitationRequest.employee_id == resolved.employee.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if employee_request is not None:
        if _same_request_payload(employee_request, payload, resolved.username):
            return await _request_result_user(session, employee_request)
        raise HTTPException(
            status_code=409,
            detail="Для сотрудника уже существует заявка приглашения; изменение требует отдельной операции",
        )

    invite_request = IdentityInvitationRequest(
        idempotency_key=idempotency_key,
        employee_id=resolved.employee.id,
        username=resolved.username,
        email=payload.email,
        department=payload.department,
        role=payload.role,
        actor=actor.username,
        status="sending",
    )
    session.add(invite_request)
    try:
        # Durable before Keycloak: после timeout запрос останется ``sending``
        # и не отправит второе письмо при автоматическом retry.
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Заявка приглашения уже создана; повтор не отправлен",
        ) from exc

    try:
        invited = await identity.invite_user(
            username=resolved.username,
            full_name=resolved.employee.full_name,
            email=payload.email,
            expected_department=payload.department,
            expected_role=payload.role,
        )
    except KeycloakAdminNotConfigured as exc:
        await _failed_request(session, invite_request, actor=actor, code=exc.code)
        raise HTTPException(status_code=503, detail=exc.code) from exc
    except KeycloakAdminConflict as exc:
        await _failed_request(session, invite_request, actor=actor, code=exc.code)
        raise HTTPException(status_code=409, detail=exc.code) from exc
    except KeycloakAdminError as exc:
        await _failed_request(session, invite_request, actor=actor, code=exc.code)
        raise HTTPException(status_code=502, detail=exc.code) from exc

    now = datetime.now(UTC).replace(tzinfo=None)
    user = User(
        username=resolved.username,
        full_name=resolved.employee.full_name,
        email=payload.email,
        employee_id=resolved.employee.id,
        # До отдельного действия руководителя сотрудник получает только
        # onboarding-роль. Не сохраняем ожидаемые отдел/роль как действующие,
        # чтобы их нельзя было случайно применить через эту операцию.
        department=None,
        role=ONBOARDING_ROLE,
        expected_department=payload.department,
        expected_role=payload.role,
        keycloak_user_id=invited.user_id,
        status="onboarding",
        invited_at=now,
    )
    session.add(user)
    try:
        await session.flush()
        invite_request.user_id = user.id
        invite_request.keycloak_user_id = invited.user_id
        invite_request.status = "sent"
        invite_request.sent_at = now
        session.add(
            AuditLog(
                actor=actor.username,
                action="identity.user.invited",
                entity_ref=f"employee:{resolved.employee.id}",
                detail={
                    "request_id": invite_request.id,
                    "username": resolved.username,
                    "department": payload.department,
                    "role": payload.role,
                    "keycloak_reused": invited.reused,
                },
            )
        )
        await session.commit()
    except Exception as exc:
        # Keycloak мог уже послать письмо. Оставляем ранее зафиксированный
        # ``sending`` и запрещаем повтор, пока оператор не проведёт сверку.
        await session.rollback()
        raise HTTPException(
            status_code=502,
            detail="identity_invite_reconciliation_required",
        ) from exc
    await session.refresh(user)
    return user


@router.post("/{employee_id}/activate", response_model=ActivatedEmployeeOut)
async def activate_employee(
    employee_id: int,
    request: Request,
    actor: CurrentUser = Depends(require_permission(IDENTITY_INVITE_ACTIVATE)),
    session: AsyncSession = Depends(get_session),
    identity: IdentityGateway = Depends(get_identity_gateway),
):
    """Подтвердить рабочий доступ сотрудника после onboarding.

    Отдел и роль не принимаются из HTTP payload: используются исключительно
    ожидаемые значения, зафиксированные при приглашении. Право есть только у
    супер-ролей; техническому ``identity_provisioner`` это право не выдаётся.
    """

    idempotency_key = _idempotency_key(request)
    user = (
        await session.execute(select(User).where(User.employee_id == employee_id).with_for_update())
    ).scalar_one_or_none()
    if user is None or user.employee_id is None:
        raise HTTPException(status_code=404, detail="Onboarding-пользователь не найден")

    same_key = (
        await session.execute(
            select(IdentityAccessActivationRequest)
            .where(IdentityAccessActivationRequest.idempotency_key == idempotency_key)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if same_key is not None:
        # Replay после успеха видит уже очищенные ``expected_*`` у User, поэтому
        # сопоставляем immutable IDs из зафиксированного намерения, а не текущие
        # рабочие поля пользователя.
        if same_key.user_id != user.id or same_key.employee_id != employee_id:
            raise HTTPException(
                status_code=409,
                detail="Idempotency-Key уже использован с другой активацией",
            )
        return await _activation_result_user(session, same_key)

    # Допускаем только полностью ожидаемое onboarding-состояние. Любой ручной
    # drift (рабочая роль, отдел, неполные expected_*) блокирует действие.
    if (
        user.status != "onboarding"
        or user.role != ONBOARDING_ROLE
        or user.department is not None
        or not user.expected_department
        or not user.expected_role
        or not user.keycloak_user_id
    ):
        raise HTTPException(
            status_code=409,
            detail="Состояние onboarding-пользователя изменено; требуется ручная сверка",
        )

    employee = (
        await session.execute(select(Employee).where(Employee.id == employee_id).with_for_update())
    ).scalar_one_or_none()
    if (
        employee is None
        or (employee.status or "").strip().lower() != "active"
        or (employee.department or "").strip() != user.expected_department
        or not is_role_allowed_for_department(user.expected_department, user.expected_role)
    ):
        raise HTTPException(
            status_code=409,
            detail="Ожидаемые отдел или роль больше не согласованы с HR; требуется ручная сверка",
        )

    existing = (
        await session.execute(
            select(IdentityAccessActivationRequest)
            .where(IdentityAccessActivationRequest.user_id == user.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is not None:
        if _same_activation_request(existing, user):
            return await _activation_result_user(session, existing)
        raise HTTPException(
            status_code=409,
            detail="Для пользователя уже существует заявка активации; требуется ручная сверка",
        )

    expected_department = user.expected_department
    expected_role = user.expected_role
    staged_keycloak_user_id = user.keycloak_user_id
    activation = IdentityAccessActivationRequest(
        idempotency_key=idempotency_key,
        user_id=user.id,
        employee_id=employee_id,
        expected_department=expected_department,
        expected_role=expected_role,
        actor=actor.username,
        status="sending",
    )
    session.add(activation)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Заявка активации уже создана; повтор не выполнен",
        ) from exc

    try:
        await identity.stage_activation_target(
            user_id=staged_keycloak_user_id, expected_role=expected_role
        )
    except KeycloakAdminNotConfigured as exc:
        await _failed_request(session, activation, actor=actor, code=exc.code)
        raise HTTPException(status_code=503, detail=exc.code) from exc
    except KeycloakAdminError as exc:
        await _failed_request(session, activation, actor=actor, code=exc.code)
        raise HTTPException(status_code=502, detail=exc.code) from exc

    # Первый commit снял row-lock. Пока шёл внешний запрос, HR или onboarding
    # данные могли измениться другим оператором. Повторно блокируем обе записи
    # и убеждаемся, что именно тот доступ, который был staged, всё ещё законен.
    user = (
        await session.execute(
            select(User)
            .where(User.id == activation.user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    employee = (
        await session.execute(
            select(Employee)
            .where(Employee.id == employee_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if (
        user is None
        or user.status != "onboarding"
        or user.role != ONBOARDING_ROLE
        or user.department is not None
        or user.expected_department != expected_department
        or user.expected_role != expected_role
        or user.keycloak_user_id != staged_keycloak_user_id
        or employee is None
        or (employee.status or "").strip().lower() != "active"
        or (employee.department or "").strip() != expected_department
        or not is_role_allowed_for_department(expected_department, expected_role)
    ):
        await _failed_request(
            session,
            activation,
            actor=actor,
            code="identity_activation_state_drift",
        )
        raise HTTPException(
            status_code=409,
            detail="Onboarding или HR изменены во время активации; требуется ручная сверка",
        )

    # Keycloak всё ещё содержит onboarding-role, поэтому токен даже с уже
    # добавленной рабочей ролью блокируется middleware. Фиксируем это состояние
    # до снятия onboarding: отказ БД здесь не способен открыть бизнес-данные.
    user.department = expected_department
    user.role = expected_role
    user.status = "active_pending_cleanup"
    now = datetime.now(UTC).replace(tzinfo=None)
    activation.status = "cleanup_pending"
    activation.activated_at = now
    session.add(
        AuditLog(
            actor=actor.username,
            action="identity.user.activation_target_assigned",
            entity_ref=f"employee:{employee_id}",
            detail={
                "activation_request_id": activation.id,
                "username": user.username,
                "department": expected_department,
                "role": expected_role,
            },
        )
    )
    try:
        await session.commit()
    except Exception as exc:
        # Keycloak уже мог выдать роль, но onboarding всё ещё присутствует и
        # middleware fail-closed. Не снимаем его и не повторяем автоматически.
        await session.rollback()
        raise HTTPException(
            status_code=502,
            detail="identity_activation_reconciliation_required",
        ) from exc
    try:
        await identity.remove_onboarding_role(user_id=staged_keycloak_user_id)
    except KeycloakAdminNotConfigured as exc:
        await _failed_request(session, activation, actor=actor, code=exc.code)
        raise HTTPException(status_code=503, detail=exc.code) from exc
    except KeycloakAdminError as exc:
        await _failed_request(session, activation, actor=actor, code=exc.code)
        raise HTTPException(status_code=502, detail=exc.code) from exc
    # Keycloak подтвердил снятие onboarding. Только теперь завершаем локальный
    # журнал. Если этот commit упадёт, рабочая роль уже разрешена по явному
    # решению руководителя, но ``cleanup_pending`` останется видимым сигналом
    # ручной сверки; повтор с тем же ключом не запускает внешние изменения.
    user.status = "active"
    user.expected_department = None
    user.expected_role = None
    activation.status = "succeeded"
    activation.error_code = None
    session.add(
        AuditLog(
            actor=actor.username,
            action="identity.user.activated",
            entity_ref=f"employee:{employee_id}",
            detail={"activation_request_id": activation.id, "username": user.username},
        )
    )
    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=502,
            detail="identity_activation_reconciliation_required",
        ) from exc
    await session.refresh(user)
    return user
