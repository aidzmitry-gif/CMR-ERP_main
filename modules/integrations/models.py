"""ORM-модели модуля Integrations (схема ``integrations.*``)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class StockItem(Base):
    """Остатки/цены по SKU из 1С (синхронизируется коннектором)."""

    __tablename__ = "stock_item"
    __table_args__ = {"schema": "integrations"}

    id: Mapped[int] = mapped_column(primary_key=True)
    sku_code: Mapped[str] = mapped_column(String(64))
    warehouse: Mapped[str] = mapped_column(String(128), default="Главный", server_default="Главный")
    qty_available: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), server_default="0")
    qty_reserved: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), server_default="0")
    qty_forecast: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), server_default="0")
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), server_default="0")
    # Себестоимость из 1С — для маржи позиции «в наличии» (None: 1С не дал себес).
    cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
