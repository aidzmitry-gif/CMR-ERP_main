"""ORM-модели модуля Integrations (схема ``integrations.*``)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class CatalogPriceSnapshot(Base):
    """Sealed reference prices; independent of stock and agreed customer prices."""

    __tablename__ = "catalog_price_snapshot"
    __table_args__ = (
        CheckConstraint("row_count >= 0 AND row_count <= 10000", name="catalog_price_count"),
        CheckConstraint("response_complete AND NOT full_coverage AND NOT activity_verified",
                        name="catalog_price_reference_proof"),
        Index("uq_catalog_price_current", "is_current", unique=True,
              postgresql_where=text("is_current"), sqlite_where=text("is_current = 1")),
        {"schema": "integrations"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    namespace: Mapped[str] = mapped_column(String(64))
    content_sha: Mapped[str] = mapped_column(String(64))
    selected_kind: Mapped[str] = mapped_column(String(36))
    kind_name: Mapped[str] = mapped_column(String(255))
    price_includes_vat: Mapped[bool] = mapped_column(Boolean)
    source_as_of: Mapped[datetime] = mapped_column(DateTime)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    prices_sha: Mapped[str] = mapped_column(String(64))
    kinds_sha: Mapped[str] = mapped_column(String(64))
    currencies_sha: Mapped[str] = mapped_column(String(64))
    prices_text: Mapped[str] = mapped_column(Text)
    kinds_text: Mapped[str] = mapped_column(Text)
    currencies_text: Mapped[str] = mapped_column(Text)
    row_count: Mapped[int] = mapped_column(Integer)
    response_complete: Mapped[bool] = mapped_column(Boolean)
    full_coverage: Mapped[bool] = mapped_column(Boolean, default=False)
    activity_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)


class CatalogPriceObservation(Base):
    """Every source row is retained, including zero, held and unmapped rows."""

    __tablename__ = "catalog_price_observation"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "product_guid", "characteristic_guid", "kind_guid",
                         "package_guid", "currency_guid", name="uq_catalog_price_dimensions"),
        CheckConstraint("price >= 0 AND price < 1000000000000000000",
                        name="catalog_price_amount"),
        CheckConstraint("mapping_status IN ('mapped','held','unmapped')",
                        name="catalog_price_mapping_status"),
        CheckConstraint("mapping_status <> 'mapped' OR (sku_id IS NOT NULL AND "
                        "identity_id IS NOT NULL AND identity_revision IS NOT NULL AND "
                        "identity_revision > 0 AND "
                        "identity_target_sha IS NOT NULL)", name="catalog_price_mapped_target"),
        {"schema": "integrations"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("integrations.catalog_price_snapshot.id", ondelete="RESTRICT"), index=True,
    )
    product_guid: Mapped[str] = mapped_column(String(36))
    characteristic_guid: Mapped[str] = mapped_column(String(36))
    kind_guid: Mapped[str] = mapped_column(String(36))
    package_guid: Mapped[str] = mapped_column(String(36))
    currency_guid: Mapped[str] = mapped_column(String(36))
    currency_code: Mapped[str | None] = mapped_column(String(32))
    effective_at: Mapped[datetime] = mapped_column(DateTime)
    price: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    price_text: Mapped[str] = mapped_column(String(80))
    sku_id: Mapped[int | None] = mapped_column(ForeignKey("sku.id", ondelete="RESTRICT"))
    identity_id: Mapped[int | None] = mapped_column(
        ForeignKey("catalog_source_identity.id", ondelete="RESTRICT"),
    )
    identity_revision: Mapped[int | None] = mapped_column(Integer)
    identity_target_sha: Mapped[str | None] = mapped_column(String(64))
    mapping_status: Mapped[str] = mapped_column(String(16))
    mapping_reason: Mapped[str | None] = mapped_column(String(64))


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
