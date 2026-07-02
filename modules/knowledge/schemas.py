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


class CourseEnrollmentCreate(BaseModel):
    course_id: int
    employee_name: str
    status: str = "assigned"
    progress: int = 0
    assigned_at: str | None = None


class CourseEnrollmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    employee_name: str
    status: str
    progress: int
    assigned_at: str | None = None
    completed_at: str | None = None


class CourseEnrollmentPatch(BaseModel):
    status: str | None = None
    progress: int | None = None
    completed_at: str | None = None
