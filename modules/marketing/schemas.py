"""Pydantic-схемы модуля Marketing."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CampaignCreate(BaseModel):
    name: str
    channel: str = ""
    budget: float = 0
    leads: int = 0


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    channel: str
    budget: float
    leads: int
