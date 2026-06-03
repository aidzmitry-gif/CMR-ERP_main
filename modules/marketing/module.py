"""Модуль Marketing (Маркетинг) — реализация ModuleContract."""
from __future__ import annotations

from core.runtime.contract import ModuleContract, Widget
from core.runtime.core import Core
from modules.marketing import routes


class MarketingModule(ModuleContract):
    name = "marketing"
    version = "0.1.0"
    api_prefix = "/marketing"

    def register(self, core: Core) -> None:
        core.include_router(routes.router, prefix=self.api_prefix)
        core.register_widget(Widget("marketing", "Маркетинг", source="marketing.campaigns"))


def get_module() -> ModuleContract:
    return MarketingModule()
