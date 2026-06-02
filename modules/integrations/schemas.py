"""Pydantic-схемы модуля Integrations."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sku_code: str
    warehouse: str
    qty_available: float
    qty_reserved: float
    qty_forecast: float
    price: float


class RegistryOut(BaseModel):
    """Карточка субъекта из реестра ЕГР (обогащение по УНП)."""

    unp: str
    name: str
    address: str
    status: str
