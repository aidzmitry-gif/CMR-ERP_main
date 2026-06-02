"""Фабрика приложения: собирает сервисы, загружает модули, монтирует роуты.

Порядок: построить общие сервисы → создать ядро → загрузить включённые модули
(они регистрируют свои возможности) → собрать FastAPI и подключить роуты.
При старте проверяется соединение с БД.
"""
from __future__ import annotations

import inspect
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from config.modules import ENABLED_MODULES
from core.runtime import system_routes
from core.runtime.core import Core
from core.runtime.loader import load_modules
from core.services import build_services

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("aios.app")


async def _run_hooks(hooks) -> None:
    for hook in hooks:
        result = hook()
        if inspect.isawaitable(result):
            await result


def create_app() -> FastAPI:
    """Собрать и вернуть приложение FastAPI."""
    services = build_services()
    core = Core(services)
    load_modules(core, ENABLED_MODULES)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await services.db.connect()
        await _run_hooks(core.startup_hooks)
        logger.info("Приложение запущено")
        yield
        await _run_hooks(core.shutdown_hooks)
        await services.db.disconnect()
        logger.info("Приложение остановлено")

    app = FastAPI(title=services.config.app_name, version="0.1.0", lifespan=lifespan)
    app.state.core = core

    # системные роуты ядра (/health, /system/modules)
    app.include_router(system_routes.router)

    # роуты модулей под их префиксами
    for reg in core.routers:
        app.include_router(reg.router, prefix=reg.prefix)

    return app
