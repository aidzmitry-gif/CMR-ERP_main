"""Контракт ГРП МНС — строгое получение и необязательное обогащение по УНП.

Симметрично ``onec`` / ``stock``: реализация живёт в модуле ``integrations`` и
регистрируется в фасаде при загрузке — ``core.services.registry = RegistryClient()``.
Sales подтягивает контрагента по УНП через ``core.services.registry`` (§2.4).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class RegistryError(Exception):
    """Ожидаемый отказ реестра; безопасное сообщение для API без тела upstream."""

    code: str
    message: str
    status_code: int
    retry_after: int | None = None

    def __str__(self) -> str:
        return self.message


class RegistryGateway(Protocol):
    """Строгий API отличает отсутствие записи от сбоя; legacy lookup — graceful."""

    async def lookup(self, unp: str) -> dict | None: ...

    async def lookup_strict(self, unp: str) -> dict:
        """Проверенная запись или RegistryError, без записи в БД."""
        ...
