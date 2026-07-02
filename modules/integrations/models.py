"""ORM-модели модуля Integrations (схема ``integrations.*``)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Numeric, String, func
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


class Batch(Base):
    """Партия закупки по SKU (lot/batch) — приход товара из 1С/закупок (M4.2).

    Транзакционные данные (откуда приехало, годен до, landed cost партии), отдельно от
    мастер-данных ``Sku``: на карточке номенклатуры читаются через фасад, не смешиваясь с
    эталоном. ``expiry_date`` → FEFO-алерт <1 года. ``unit_landed_cost`` — себес единицы
    партии (инвойс+фрахт+пошлина+брокер), вход маржи; ``None`` пока расчёт не сделан.
    """

    __tablename__ = "batch"
    __table_args__ = {"schema": "integrations"}

    id: Mapped[int] = mapped_column(primary_key=True)
    sku_code: Mapped[str] = mapped_column(String(64))
    lot_no: Mapped[str] = mapped_column(String(64))  # номер партии поставщика
    supplier: Mapped[str | None] = mapped_column(String(256), nullable=True)
    warehouse: Mapped[str | None] = mapped_column(String(128), nullable=True)
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), server_default="0")
    mfg_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # дата производства
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # годен до (FEFO)
    unit_landed_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)  # ГТД/машина/Ref 1С
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
