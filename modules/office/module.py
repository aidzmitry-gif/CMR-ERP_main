"""Модуль Office (Офис-менеджер) — реализация ModuleContract."""
from __future__ import annotations

from core.runtime.contract import ModuleContract, Widget
from core.runtime.core import Core
from modules.office import routes


class OfficeModule(ModuleContract):
    name = "office"
    version = "0.1.0"
    api_prefix = "/office"

    def register(self, core: Core) -> None:
        core.include_router(routes.router, prefix=self.api_prefix)
        core.register_widget(Widget("office", "Офис-менеджер", source="office.docs"))


def get_module() -> ModuleContract:
    return OfficeModule()
