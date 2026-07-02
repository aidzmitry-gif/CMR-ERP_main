"""ORM-модели модуля Knowledge (схема ``knowledge.*``)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class Course(Base):
    """Курс программы обучения в канбане базы знаний.

    Колонка (`stage`) — раздел программы (см. ``stages.py``): тестовая неделя,
    знакомство, испытательный срок, ИИ-обучение, развитие. ``kind`` — тип контента
    (видео/тест/документ/практика/обязательно), ``progress`` — % прохождения.
    """

    __tablename__ = "course"
    __table_args__ = {"schema": "knowledge"}

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(64), default="", server_default="")
    title: Mapped[str] = mapped_column(String(255), default="", server_default="")
    description: Mapped[str] = mapped_column(String(255), default="", server_default="")
    kind: Mapped[str] = mapped_column(String(32), default="Документ", server_default="Документ")
    duration: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # минут
    progress: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # %
    audience: Mapped[str] = mapped_column(String(64), default="", server_default="")
    stage: Mapped[str] = mapped_column(String(32), default="trial", server_default="trial")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CourseEnrollment(Base):
    """Назначение курса сотруднику + трекинг прохождения (учёт курсов)."""

    __tablename__ = "course_enrollment"
    __table_args__ = {"schema": "knowledge"}

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(Integer)
    employee_name: Mapped[str] = mapped_column(String(255), default="", server_default="")
    status: Mapped[str] = mapped_column(String(32), default="assigned", server_default="assigned")
    # assigned | in_progress | completed | overdue
    progress: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # %
    assigned_at: Mapped[str | None] = mapped_column(String(10), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
