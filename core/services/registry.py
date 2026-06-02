"""Контракт реестра субъектов хозяйствования (ЕГР РБ) — обогащение по УНП.

Симметрично ``onec`` / ``stock``: реализация живёт в модуле ``integrations`` и
регистрируется в фасаде при загрузке — ``core.services.registry = RegistryClient()``.
Sales подтягивает контрагента по УНП через ``core.services.registry`` (§2.4).
"""
from __future__ import annotations

from typing import Protocol


class RegistryGateway(Protocol):
    """Поиск субъекта по УНП; ``None`` — не найден."""

    async def lookup(self, unp: str) -> dict | None: ...
