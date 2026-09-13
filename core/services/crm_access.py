"""Shared request-scoped CRM identity; numeric employee ownership, never names."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.access import is_super
from config.settings import get_settings
from core.domain.models import User
from core.runtime.deps import get_session
from core.services.auth import CurrentUser, get_current_user


# ``Deal.owner_id`` stores ``hr.employee.id`` (via this soft link), never the
# primary key of app_user.  Only a current CRM employee may become a confirmed
# numeric owner; a legacy text owner remains display-only.
@dataclass(frozen=True)
class CrmAccess:
    """Resolved, request-scoped visibility. ``employee_id`` is required for own."""

    visibility: str
    employee_id: int | None = None

    @property
    def own_only(self) -> bool:
        return self.visibility == "own"


async def get_crm_access(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> CrmAccess:
    """Resolve a user's persistent scope without trusting client filters.

    A signed OIDC subject is the authoritative identity: never fall back to a
    renameable username for it. Header/test authentication without a subject
    may use username. Unlinked legacy directors remain supported only through
    the explicit super-role bypass above.
    """
    # Operational liveness is intentionally identity-independent. It exposes
    # no CRM data and must stay usable before the database is reachable.
    if request.url.path == "/sales/ping":
        return CrmAccess("all")
    if is_super(user.roles):
        return CrmAccess("all")

    identity_filter = (
        User.keycloak_user_id == user.keycloak_user_id
        if user.keycloak_user_id
        else User.username == user.username
    )
    app_user = (await session.execute(select(User).where(identity_filter))).scalar_one_or_none()
    if app_user is None:
        if not user.keycloak_user_id and get_settings().auth_mode == "dev":
            return CrmAccess("all")
        raise HTTPException(status_code=403, detail="Учётная запись сотрудника не связана с CRM")
    if app_user.status != "active":
        raise HTTPException(status_code=403, detail="Учётная запись сотрудника не активна")

    visibility = getattr(app_user, "deal_visibility", "all")
    if visibility == "all":
        return CrmAccess("all", app_user.employee_id)
    if visibility != "own" or app_user.employee_id is None:
        raise HTTPException(status_code=403, detail="Не настроен безопасный доступ к сделкам")
    return CrmAccess("own", app_user.employee_id)
