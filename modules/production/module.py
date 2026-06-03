"""Модуль Production (Производство) — реализация ModuleContract."""
from __future__ import annotations

from core.runtime.contract import ModuleContract, Widget
from core.runtime.core import Core
from modules.production import routes


class ProductionModule(ModuleContract):
    name = "production"
    version = "0.1.0"
    api_prefix = "/production"

    def register(self, core: Core) -> None:
        core.include_router(routes.router, prefix=self.api_prefix)
        core.register_widget(Widget("production", "Производство", source="production.orders"))


def get_module() -> ModuleContract:
    return ProductionModule()
