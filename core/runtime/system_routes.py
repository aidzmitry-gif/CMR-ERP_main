"""Системные роуты ядра: health-check и интроспекция реестра подключённых модулей."""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict:
    """Проверка живости приложения."""
    return {"status": "ok"}


@router.get("/system/modules")
async def system_modules(request: Request) -> dict:
    """Показать, что именно зарегистрировали загруженные модули.

    Это «живой пример» из §6: видно, как модуль подключается к ядру —
    какие роуты, события, процессы, права, виджеты и команды он отдал.
    """
    core = request.app.state.core
    return {
        "loaded_modules": core.loaded_modules,
        "routers": [{"module": r.module, "prefix": r.prefix} for r in core.routers],
        "events": [{"module": e.module, "event_type": e.event_type} for e in core.events],
        "workflows": [{"module": w.module, "name": w.name} for w in core.workflows],
        "permissions": [p.code for p in core.permissions],
        "roles": [{"name": r.name, "permissions": list(r.permissions)} for r in core.roles],
        "telegram_commands": [c.command for c in core.telegram_commands],
        "widgets": [{"key": w.key, "title": w.title} for w in core.widgets],
    }
