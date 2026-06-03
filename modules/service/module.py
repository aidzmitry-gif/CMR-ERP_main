"""Модуль Service (Сервис и поддержка) — реализация ModuleContract."""
from __future__ import annotations

from core.runtime.contract import ModuleContract, Widget
from core.runtime.core import Core
from modules.service import routes


class ServiceModule(ModuleContract):
    name = "service"
    version = "0.1.0"
    api_prefix = "/service"

    def register(self, core: Core) -> None:
        core.include_router(routes.router, prefix=self.api_prefix)
        core.register_widget(Widget("service", "Сервис и поддержка", source="service.tickets"))


def get_module() -> ModuleContract:
    return ServiceModule()
