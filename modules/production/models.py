"""ORM-модели модуля Production (схема ``production.*``)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class ProductionOrder(Base):
    """Производственный заказ: продукт, количество, статус."""

    __tablename__ = "production_order"
    __table_args__ = {"schema": "production"}

    id: Mapped[int] = mapped_column(primary_key=True)
    product: Mapped[str] = mapped_column(String(255))
    qty: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(32), default="planned", server_default="planned")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
