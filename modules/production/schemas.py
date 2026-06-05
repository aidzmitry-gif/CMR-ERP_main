"""Pydantic-схемы модуля Production."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ProductionOrderCreate(BaseModel):
    product: str
    qty: int = 1
    progress: int = 0
    priority: str = "Средний"
    owner: str = ""
    stage: str = "queue"
    number: str = ""
    due_date: str | None = None
    insight: str = ""


class ProductionOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    number: str
    product: str
    qty: int
    progress: int
    priority: str
    owner: str
    stage: str
    due_date: str | None = None
    insight: str = ""


class StageUpdate(BaseModel):
    stage: str
