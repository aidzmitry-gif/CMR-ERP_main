"""Фабрика приложения: собирает сервисы, загружает модули, монтирует роуты.

Порядок: построить общие сервисы → создать ядро → загрузить включённые модули
(они регистрируют свои возможности) → собрать FastAPI и подключить роуты.
При старте проверяется соединение с БД.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from config.modules import ENABLED_MODULES
from core.runtime import approval_routes, system_routes, telegram_routes
from core.runtime.access import AccessControlMiddleware, build_prefix_map
from core.runtime.core import Core
from core.runtime.loader import load_modules
from core.runtime.reference_registry import register_system_references
from core.runtime.reference_routes import build_reference_router
from core.services import build_services
from core.services.eventbus import EventContext

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("aios.app")


async def _run_hooks(hooks) -> None:
    for hook in hooks:
        result = hook()
        if inspect.isawaitable(result):
            await result


async def _background_loop(services, tick_hooks=()) -> None:
    """Фоновый цикл: доставка событий из outbox + эскалация согласований + tick-хуки.

    В проде доставка — консьюмер Redis Streams, эскалация — таймеры Temporal.
    ``tick_hooks`` — периодические шаги модулей (``core.on_tick``), напр. жизненный
    цикл резерва под счёт (SALES-51); транзакцией каждого шага владеет цикл.
    """
    while True:
        await asyncio.sleep(2)
        try:
            assert services.db.session_factory is not None
            async with services.db.session_factory() as session:
                await services.event_bus.relay_once(session, EventContext(session, services))
            async with services.db.session_factory() as session:
                await services.approvals.escalate_once(session)
            for hook in tick_hooks:
                async with services.db.session_factory() as session:
                    await hook(session, services)
                    await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("background loop error")


def create_app() -> FastAPI:
    """Собрать и вернуть приложение FastAPI."""
    services = build_services()
    core = Core(services)
    load_modules(core, ENABLED_MODULES)
    # системные справочники ядра (public): единицы, валюты+курсы, страны, банки, НДС,
    # контрагенты, контакты, номенклатура, сотрудники — в реестр-витрину «Справочники».
    register_system_references(core)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # SECURITY.md P1-1: dev-режим AuthN доверяет заголовку X-User-Roles (вход без пароля).
        # Прод-гард (config/settings.py) уже запрещает auth_mode≠oidc при environment≠dev; здесь
        # — ГРОМКАЯ страховка, чтобы любой запуск в dev-режиме был виден в логах (а не «тихо»).
        if services.config.auth_mode != "oidc":
            logger.warning(
                "AuthN в DEV-режиме (auth_mode=%s): доверяю заголовку X-User-Roles — вход БЕЗ "
                "пароля. НЕ для публичного/прод-доступа. Выставьте AIOS_AUTH_MODE=oidc + Keycloak "
                "(SECURITY.md P1-1).",
                services.config.auth_mode,
            )
        await services.db.connect()
        await _run_hooks(core.startup_hooks)
        background_task = asyncio.create_task(_background_loop(services, core.tick_hooks))
        logger.info("Приложение запущено")
        yield
        background_task.cancel()
        await _run_hooks(core.shutdown_hooks)
        await services.db.disconnect()
        logger.info("Приложение остановлено")

    app = FastAPI(title=services.config.app_name, version="0.1.0", lifespan=lifespan)
    app.state.core = core

    # системные роуты ядра (/health, /system/modules, /system/events, /system/owner)
    app.include_router(system_routes.router)
    # CRUD системных справочников ядра под /system/refs/* (см. каталог /system/references)
    app.include_router(build_reference_router())
    # согласования (human-in-the-loop)
    app.include_router(approval_routes.router)
    # Telegram-интерфейс (часть 11): команды и согласования в боте
    app.include_router(telegram_routes.router)

    # роуты модулей под их префиксами
    for reg in core.routers:
        app.include_router(reg.router, prefix=reg.prefix)

    # ограничение доступа к модулям по матрице ролей (config/access.py)
    app.add_middleware(AccessControlMiddleware, prefixes=build_prefix_map(core))

    return app
