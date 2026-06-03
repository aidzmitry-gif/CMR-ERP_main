"""ORM-модели модуля HR (схема ``hr.*``)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class Employee(Base):
    """Сотрудник: ФИО, должность, отдел, статус."""

    __tablename__ = "employee"
    __table_args__ = {"schema": "hr"}

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255))
    position: Mapped[str] = mapped_column(String(128), default="", server_default="")
    department: Mapped[str] = mapped_column(String(128), default="", server_default="")
    status: Mapped[str] = mapped_column(String(32), default="active", server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
