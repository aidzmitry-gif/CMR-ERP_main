"""Pydantic-схемы модуля Legal."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LegalCaseCreate(BaseModel):
    company: str = ""
    title: str = ""
    amount: float = 0
    urgency: str = "Обычный"
    owner: str = ""
    stage: str = "inbox"
    next_step: str = ""
    number: str = ""
    due_date: str | None = None


class LegalCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    number: str
    company: str
    title: str
    amount: float
    urgency: str
    owner: str
    stage: str
    next_step: str
    due_date: str | None = None


class StageUpdate(BaseModel):
    stage: str
