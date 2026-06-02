"""Модуль Integrations — реализация ModuleContract."""
from __future__ import annotations

from core.runtime.contract import ModuleContract, Permission
from core.runtime.core import Core
from modules.integrations import routes
from modules.integrations.client import OneCClient
from modules.integrations.registry import RegistryClient
from modules.integrations.stock import StockService


class IntegrationsModule(ModuleContract):
    name = "integrations"
    version = "0.1.0"
    api_prefix = "/integrations"

    def register(self, core: Core) -> None:
        core.include_router(routes.router, prefix=self.api_prefix)
        core.declare_permissions([Permission("integrations.sync", "Синхронизация с 1С")])
        # опубликовать 1С-коннектор и складской шлюз в фасаде ядра — другие модули
        # пишут/читают в 1С и резервируют остатки через core.services, не импортируя
        # этот модуль (§2.4).
        core.services.onec = OneCClient(core.config.onec_base_url)
        core.services.stock = StockService()
        core.services.registry = RegistryClient()


def get_module() -> ModuleContract:
    return IntegrationsModule()
