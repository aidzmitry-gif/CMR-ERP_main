"""Persist the platform's seller; never infer ownership or grant book access."""
from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError

from core.domain.installation import PlatformInstallation
from core.domain.models import AuditLog
from core.services.auth import GUEST
from core.services.instance_organization import resolve_instance_organization


class InstallationOrganizationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_id: StrictInt = Field(gt=0)
    expected_revision: StrictInt = Field(ge=0)
    request_id: UUID


def authenticated(user):
    if not user.username or user.username == GUEST or GUEST in user.roles:
        raise HTTPException(401, "Войдите в систему.")


async def options(session, user, gateway):
    authenticated(user)
    if gateway is None or not callable(getattr(gateway, "source_organizations", None)):
        raise HTTPException(503, "Сервис юридических лиц недоступен.")
    rows = await gateway.source_organizations(session, user)
    if not isinstance(rows, list) or any(
        not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] <= 0
        or not isinstance(row.get("name"), str) or not row["name"].strip()
        or not isinstance(row.get("unp"), str) or not re.fullmatch(r"[0-9]{9}", row["unp"])
        for row in rows
    ) or len({row["id"] for row in rows}) != len(rows):
        raise HTTPException(503, "Сервис юридических лиц вернул некорректные данные.")
    return [{"id": row["id"], "name": row["name"], "unp": row["unp"]} for row in rows]


async def current_instance(session, user, gateway, fallback_unp):
    authenticated(user)
    saved = await session.get(PlatformInstallation, 1, populate_existing=True)
    if saved is None:
        return await resolve_instance_organization(session, user, gateway, fallback_unp)
    result = await resolve_instance_organization(session, user, gateway, saved.organization_unp)
    if result["organization"]["id"] != saved.organization_id:
        raise HTTPException(409, "Принадлежность юрлица установки изменилась. Проверьте настройки.")
    return {"organization": result["organization"], "configuration": "platform_settings", "revision": saved.revision}


async def read_settings(session, user, gateway, fallback_unp, can_manage):
    rows = await options(session, user, gateway)
    saved = await session.get(PlatformInstallation, 1, populate_existing=True)
    matches = [row for row in rows if (
        row["id"] == saved.organization_id and row["unp"] == saved.organization_unp
        if saved else row["unp"] == fallback_unp
    )]
    organization = matches[0] if len(matches) == 1 else None
    return {
        "organization": organization, "revision": saved.revision if saved else 0,
        "configuration": "platform_settings" if saved else "AIOS_SELLER_UNP" if fallback_unp else None,
        "can_manage": can_manage, "organizations": rows if can_manage else [],
    }


async def save_settings(session, user, gateway, command: InstallationOrganizationUpdate):
    rows = await options(session, user, gateway)
    selected = next((row for row in rows if row["id"] == command.organization_id), None)
    if selected is None:
        raise HTTPException(403, "Выбранное юрлицо недоступно. Права на организацию не изменены.")
    request_id = str(command.request_id)
    digest = hashlib.sha256(json.dumps(command.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
    saved = await session.get(PlatformInstallation, 1, populate_existing=True)
    if saved and saved.request_id == request_id:
        if saved.command_digest != digest or saved.organization_unp != selected["unp"]:
            raise HTTPException(409, "Состав команды настройки изменился.")
        return {"organization": selected, "configuration": "platform_settings", "revision": saved.revision}
    if (saved.revision if saved else 0) != command.expected_revision:
        raise HTTPException(409, "Настройку уже изменили. Перечитайте её перед новой командой.")
    revision = command.expected_revision + 1
    actor = user.keycloak_user_id or user.username
    previous = saved.organization_id if saved else None
    values = dict(revision=revision, organization_id=selected["id"], organization_unp=selected["unp"],
                  request_id=request_id, command_digest=digest, actor=actor)
    if saved is None:
        session.add(PlatformInstallation(id=1, **values))
    else:
        result = await session.execute(update(PlatformInstallation).where(
            PlatformInstallation.id == 1, PlatformInstallation.revision == command.expected_revision,
        ).values(**values, updated_at=func.now()).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            await session.rollback()
            raise HTTPException(409, "Настройку уже изменили. Перечитайте её перед новой командой.")
    session.add(AuditLog(actor=actor, action="system.installation_organization.changed", entity_ref="platform:1",
                         detail={"revision": revision, "request_id": request_id,
                                 "before_organization_id": previous, "organization_id": selected["id"]}))
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Настройку уже изменили. Перечитайте её перед новой командой.") from exc
    return {"organization": selected, "configuration": "platform_settings", "revision": revision}
