"""Pydantic-схемы модуля Knowledge."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CourseCreate(BaseModel):
    title: str = ""
    description: str = ""
    kind: str = "Документ"
    duration: int = 0
    progress: int = 0
    audience: str = ""
    stage: str = "trial"
    number: str = ""


class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    number: str
    title: str
    description: str
    kind: str
    duration: int
    progress: int
    audience: str
    stage: str


class StageUpdate(BaseModel):
    stage: str
