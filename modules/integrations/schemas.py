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
