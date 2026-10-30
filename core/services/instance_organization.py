"""Resolve the installation's configured seller without granting book access."""
from __future__ import annotations

import re

from fastapi import HTTPException

from core.services.auth import GUEST


async def resolve_instance_organization(session, user, gateway, unp: str | None) -> dict:
    if not user.username or user.username == GUEST or GUEST in user.roles:
        raise HTTPException(401, "Войдите в систему.")
    if not isinstance(unp, str) or not re.fullmatch(r"[0-9]{9}", unp.strip()):
        raise HTTPException(503, "Юрлицо установки не настроено: задайте AIOS_SELLER_UNP в настройках сервера.")
    if gateway is None or not callable(getattr(gateway, "source_organizations", None)):
        raise HTTPException(503, "Сервис юридических лиц недоступен.")
    # The existing gateway filters by this authenticated principal's grants.
    # Never pick the first/only available book when its UNP differs.
    rows = await gateway.source_organizations(session, user)
    matches = [row for row in rows if row.get("unp") == unp.strip()]
    if not matches:
        raise HTTPException(403, "Юрлицо установки недоступно. Проверьте настройку организации и права сотрудника.")
    if len(matches) != 1:
        raise HTTPException(409, "Настройка юрлица неоднозначна. Требуется проверка справочника организаций.")
    row = matches[0]
    if type(row.get("id")) is not int or row["id"] <= 0 or not isinstance(row.get("name"), str):
        raise HTTPException(503, "Сервис юридических лиц вернул некорректные данные.")
    return {"organization": {"id": row["id"], "name": row["name"], "unp": row["unp"]},
            "configuration": "AIOS_SELLER_UNP"}
