"""Pydantic-схемы модуля Production."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ProductionOrderCreate(BaseModel):
    product: str
    qty: int = 1
    status: str = "planned"


class ProductionOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product: str
    qty: int
    status: str


class StatusUpdate(BaseModel):
    status: str
