"""Pydantic-схемы модуля Service."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TicketCreate(BaseModel):
    customer: str
    subject: str
    body: str = ""
    status: str = "open"


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer: str
    subject: str
    status: str
