"""Pydantic-схемы модуля Office."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class OfficeDocCreate(BaseModel):
    company: str = ""
    title: str = ""
    amount: float = 0
    delivery: str = ""
    docs_status: str = ""
    priority: str = "Средний"
    owner: str = ""
    stage: str = "ready"
    next_step: str = ""
    number: str = ""
    op_date: str | None = None


class OfficeDocOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    number: str
    company: str
    title: str
    amount: float
    delivery: str
    docs_status: str
    priority: str
    owner: str
    stage: str
    next_step: str
    op_date: str | None = None


class StageUpdate(BaseModel):
    stage: str
