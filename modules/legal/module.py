"""Модуль Legal (Юр. отдел) — реализация ModuleContract."""

from __future__ import annotations

from core.runtime.contract import ModuleContract, Permission, Widget
from core.runtime.core import Core
from modules.legal import routes


class LegalModule(ModuleContract):
    name = "legal"
    version = "0.1.0"
    api_prefix = "/legal"

    def register(self, core: Core) -> None:
        core.declare_permissions([Permission("legal.case.write", "Создание и изменение дел")])
        core.include_router(routes.router, prefix=self.api_prefix)
        core.register_widget(Widget("legal", "Юр. отдел", source="legal.cases"))


def get_module() -> ModuleContract:
    return LegalModule()
