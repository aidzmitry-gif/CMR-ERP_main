"""Pydantic-схемы модуля HR."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class EmployeeCreate(BaseModel):
    full_name: str
    position: str = ""
    department: str = ""
    status: str = "active"


class EmployeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    position: str
    department: str
    status: str
