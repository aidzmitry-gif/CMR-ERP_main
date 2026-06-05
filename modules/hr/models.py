"""ORM-модели модуля HR (схема ``hr.*``)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, func
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


class Candidate(Base):
    """Кандидат в воронке подбора: от новой вакансии до найма.

    Стадия (`stage`) ведёт кандидата по этапам подбора (см. ``stages.py``):
    вакансия → приглашение → тех. интервью → оффер → нанят.
    """

    __tablename__ = "candidate"
    __table_args__ = {"schema": "hr"}

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(64), default="", server_default="")
    name: Mapped[str] = mapped_column(String(255), default="", server_default="")
    position: Mapped[str] = mapped_column(String(128), default="", server_default="")
    salary: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), server_default="0")
    recruiter: Mapped[str] = mapped_column(String(128), default="", server_default="")
    priority: Mapped[str] = mapped_column(String(32), default="Средний", server_default="Средний")
    stage: Mapped[str] = mapped_column(String(32), default="new", server_default="new")
    next_step: Mapped[str] = mapped_column(String(255), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
