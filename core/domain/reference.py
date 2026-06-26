"""Shared-kernel reference data — системные справочники-стандарты (схема ``public``).

Мелкие, общие для всех модулей справочники, которыми владеет ядро: единицы, валюты
(+ историчный курс), страны, банки, ставки НДС (+ история). Данные физически лежат
здесь; вкладка «Справочники» лишь регистрирует их как реестр-витрину (см.
``core.runtime.reference_registry``).

Историчность (курс валюты, ставка НДС) — ручной **SCD Type 2**: датированные версии
с полуоткрытым интервалом ``[start_date, end_date)``; текущая версия — ``end_date IS NULL``.
Нативные temporal-таблицы Postgres — это PG18/19, стек на PG16 → ведём вручную.

Типы намеренно generic (``JSON``/``Numeric``/``Date``) — чтобы dev на SQLite поднимался
через ``create_all``; JSONB/GIN включаются только в Postgres-миграции (источник истины схемы).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class Unit(Base):
    """Единица измерения (шт, кг, м)."""

    __tablename__ = "ref_unit"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    title: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")


class Country(Base):
    """Страна (ISO-код)."""

    __tablename__ = "ref_country"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(8), unique=True)  # ISO "BY", "RU"
    title: Mapped[str] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")


class Bank(Base):
    """Банк (БИК/SWIFT)."""

    __tablename__ = "ref_bank"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)  # БИК
    title: Mapped[str] = mapped_column(String(255))
    swift: Mapped[str | None] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")


class Currency(Base):
    """Валюта (ISO-код)."""

    __tablename__ = "ref_currency"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(8), unique=True)  # ISO "BYN", "USD"
    title: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")


class CurrencyRate(Base):
    """Курс валюты к BYN — историчный (SCD Type 2)."""

    __tablename__ = "ref_currency_rate"

    id: Mapped[int] = mapped_column(primary_key=True)  # surrogate key
    currency_code: Mapped[str] = mapped_column(String(8))  # natural key
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    start_date: Mapped[date] = mapped_column(Date)  # действует с (вкл.)
    end_date: Mapped[date | None] = mapped_column(Date)  # по (искл.); NULL = текущая

    __table_args__ = (
        Index("ix_ref_currency_rate_lookup", "currency_code", "start_date"),
    )


class VatRate(Base):
    """Ставка НДС — историчная (SCD Type 2)."""

    __tablename__ = "ref_vat_rate"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16))  # natural key: "НДС20"
    title: Mapped[str] = mapped_column(String(64))
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))  # 20.00
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)  # NULL = текущая

    __table_args__ = (
        Index("ix_ref_vat_rate_lookup", "code", "start_date"),
    )


class TnvedCode(Base):
    """Код ТН ВЭД ЕАЭС с таможенными ставками — историчный (SCD Type 2).

    Единый таможенный тариф ЕАЭС (ЕТТ, общий для РБ/РФ/КЗ): ставка ввозной пошлины +
    акциз по коду, НДС — мягкой ссылкой ``vat_code`` на ``ref_vat_rate`` (не дублируем
    ставку НДС). Ставки меняются решениями Совета ЕЭК → версионность как у курсов/НДС:
    расчёт landed cost берёт ставку, действовавшую на дату оформления.

    ``duty_rate`` — базовая адвалорная ставка ЕТТ в % (преференции/антидемпинг по стране
    происхождения — отдельным слоем позже, не здесь). ``unit`` — единица для таможни.
    """

    __tablename__ = "ref_tnved"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16))  # natural key: 10-значный код ЕТТ "8507100000"
    name: Mapped[str] = mapped_column(String(512))  # описание позиции
    duty_rate: Mapped[Decimal] = mapped_column(Numeric(6, 3))  # ввозная пошлина %, базовая ЕТТ
    vat_code: Mapped[str | None] = mapped_column(String(16))  # → ref_vat_rate.code (мягкая ссылка)
    excise: Mapped[str | None] = mapped_column(String(128))  # акциз (если применим), текстом
    unit: Mapped[str | None] = mapped_column(String(32))  # доп. единица измерения для таможни
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)  # NULL = текущая

    __table_args__ = (
        Index("ix_ref_tnved_lookup", "code", "start_date"),
    )


class Account(Base):
    """Счёт плана счетов (РБ, постановление Минфина №50) — иерархия (синтетика → субсчёт).

    Belarusian chart of accounts: 2-значные синтетические счета («60», «62») и их субсчета
    («60.1», «62.2») через ``parent_id`` (adjacency list, как группы номенклатуры).
    ``kind`` — тип (актив/пассив/активно-пассивный) для отчётности; ``code`` — номер счёта.
    """

    __tablename__ = "ref_account"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)  # "60", "60.1"
    title: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str | None] = mapped_column(String(16))  # актив | пассив | активно-пассивный
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("ref_account.id"))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")

    __table_args__ = (
        Index("ix_ref_account_parent", "parent_id"),
    )


class Region(Base):
    """Регион/город (РБ) — иерархия (область → район/город) через ``parent_id``.

    Гео-справочник для адресов контрагентов и территориальной аналитики продаж
    (territory из регламента воронки). ``kind`` — уровень (область/район/город).
    """

    __tablename__ = "ref_region"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)  # "BY-MI", "BY-MI-MINSK"
    title: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str | None] = mapped_column(String(16))  # область | район | город
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("ref_region.id"))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")

    __table_args__ = (
        Index("ix_ref_region_parent", "parent_id"),
    )


class NomenclatureCategory(Base):
    """Группа (категория) номенклатуры — иерархия (adjacency list: ``parent_id`` = истина).

    Дерево хранится через ``parent_id`` (переносимо в SQLite-dev, обход рекурсивным CTE);
    ``Sku.category_id`` ссылается сюда. # ponytail: O(глубина)-обход по parent_id —
    производный ltree-путь + GiST на Postgres, если деревья станут глубокими/горячими
    для поддеревьев и структурного доступа AI.
    """

    __tablename__ = "ref_nomenclature_category"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)  # стабильный код: "CAT-0102"
    name: Mapped[str] = mapped_column(String(255))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("ref_nomenclature_category.id"))
    # код ТН ВЭД по умолчанию для группы (→ ref_tnved): товар без своего наследует его вверх
    # по parent_id. Мягкая ссылка (не FK), как Sku.tnved_code — резолв в reference_query.
    tnved_code: Mapped[str | None] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")

    __table_args__ = (
        Index("ix_ref_nom_category_parent", "parent_id"),
    )
