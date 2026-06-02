"""Модуль Integrations — реализация ModuleContract."""
from __future__ import annotations

from core.runtime.contract import ModuleContract, Permission
from core.runtime.core import Core
from modules.integrations import routes


class IntegrationsModule(ModuleContract):
    name = "integrations"
    version = "0.1.0"
    api_prefix = "/integrations"

    def register(self, core: Core) -> None:
        core.include_router(routes.router, prefix=self.api_prefix)
        core.declare_permissions([Permission("integrations.sync", "Синхронизация с 1С")])


def get_module() -> ModuleContract:
    return IntegrationsModule()
