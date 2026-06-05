"""ORM-модели модуля Office (схема ``office.*``)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class OfficeDoc(Base):
    """Документ по сделке в воронке офис-менеджера: отгрузка → документы → оплата.

    Стадия (`stage`) ведёт сделку по документообороту после продажи (см. ``stages.py``).
    """

    __tablename__ = "office_doc"
    __table_args__ = {"schema": "office"}

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(64), default="", server_default="")
    company: Mapped[str] = mapped_column(String(255), default="", server_default="")
    title: Mapped[str] = mapped_column(String(255), default="", server_default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), server_default="0")
    delivery: Mapped[str] = mapped_column(String(64), default="", server_default="")  # тип доставки
    docs_status: Mapped[str] = mapped_column(String(64), default="", server_default="")  # статус док-тов
    priority: Mapped[str] = mapped_column(String(32), default="Средний", server_default="Средний")
    owner: Mapped[str] = mapped_column(String(128), default="", server_default="")
    stage: Mapped[str] = mapped_column(String(32), default="ready", server_default="ready")
    next_step: Mapped[str] = mapped_column(String(255), default="", server_default="")
    op_date: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
