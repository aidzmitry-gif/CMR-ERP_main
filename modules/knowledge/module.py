"""Модуль Knowledge (База знаний) — реализация ModuleContract."""
from __future__ import annotations

from core.runtime.contract import ModuleContract, Widget
from core.runtime.core import Core
from modules.knowledge import routes


class KnowledgeModule(ModuleContract):
    name = "knowledge"
    version = "0.1.0"
    api_prefix = "/knowledge"

    def register(self, core: Core) -> None:
        core.include_router(routes.router, prefix=self.api_prefix)
        core.register_widget(Widget("knowledge", "База знаний", source="knowledge.courses"))


def get_module() -> ModuleContract:
    return KnowledgeModule()
