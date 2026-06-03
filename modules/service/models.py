"""ORM-модели модуля Service (схема ``service.*``)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class Ticket(Base):
    """Обращение в поддержку: клиент, тема, статус."""

    __tablename__ = "ticket"
    __table_args__ = {"schema": "service"}

    id: Mapped[int] = mapped_column(primary_key=True)
    customer: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(String(32), default="open", server_default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
