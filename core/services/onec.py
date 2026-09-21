"""Контракт шлюза 1С — фасад ядра к внешней учётной системе.

Сам коннектор живёт в модуле ``integrations`` (часть 6) и регистрируется в
фасаде при загрузке: ``core.services.onec = OneCClient(...)``. Ядро держит лишь
этот протокол, чтобы любой модуль обращался к 1С через ``core.services.onec``,
а не импортировал модуль напрямую (правило границ, §2.4).
"""
from __future__ import annotations

from datetime import date
from typing import Protocol


class OneCGateway(Protocol):
    """Чтение из 1С и опциональная подтверждённая исходящая связь.

    ⚠ ``fetch_payments``/``fetch_bank_balance``/``fetch_balance_sheet`` — read-фасады для
    финотчётов (FIN-C4/Р6/Р7): СТРОГО ЧТЕНИЕ (OData GET), никакого write в 1С (мастер-данные
    заморожены, см. onec-write-frozen). Реализатор без проверенного маппинга обязан вернуть
    ``[]``/``None`` и, если возможно, объявить ``financial_source_available=False``; finance
    не может подменять такой источник демонстрационными суммами.

    Исходящий документ допускается только через адаптер, который явно объявил
    ``outbound_document_source_available=True``. Непроверенный gateway не
    возвращает успешную ссылку: CRM выпускает оригинал локально и сохраняет
    причину отсутствующей внешней связи в событии.
    """

    async def fetch_counterparties(self) -> list[dict]: ...

    async def fetch_stock(self) -> list[dict]: ...

    async def fetch_payments(self) -> list[dict]: ...

    async def fetch_bank_balance(self, account_code: str | None = None) -> dict | None: ...

    async def fetch_balance_sheet(self, on_date: date) -> dict | None: ...

    @property
    def outbound_document_source_available(self) -> bool: ...

    @property
    def outbound_document_source_reason(self) -> str: ...

    async def post_document(self, doc_type: str, payload: dict) -> dict: ...
