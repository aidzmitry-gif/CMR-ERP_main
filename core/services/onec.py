"""Контракт шлюза 1С — фасад ядра к внешней учётной системе.

Сам коннектор живёт в модуле ``integrations`` (часть 6) и регистрируется в
фасаде при загрузке: ``core.services.onec = OneCClient(...)``. Ядро держит лишь
этот протокол, чтобы любой модуль обращался к 1С через ``core.services.onec``,
а не импортировал модуль напрямую (правило границ, §2.4).
"""
from __future__ import annotations

from typing import Protocol


class OneCGateway(Protocol):
    """Чтение из 1С (часть 6) и запись документов (часть 9)."""

    async def fetch_counterparties(self) -> list[dict]: ...

    async def fetch_stock(self) -> list[dict]: ...

    async def post_document(self, doc_type: str, payload: dict) -> dict: ...
