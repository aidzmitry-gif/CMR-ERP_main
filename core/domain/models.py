"""Общее ядро (shared kernel): сущности, нужные всем модулям.

Контрагент, контакт, SKU/номенклатура и пользователь живут здесь, и все модули
читают их через ядро, а не дублируют у себя — это единственная общая точка,
которую важно не размазать по модулям (§2.4).

На этапе каркаса — лёгкие Pydantic-модели; в части 2 становятся SQLAlchemy-
моделями со своими миграциями.
"""
from __future__ import annotations

from pydantic import BaseModel


class Counterparty(BaseModel):
    """Контрагент (клиент или поставщик)."""

    id: int | None = None
    name: str
    unp: str | None = None  # УНП — учётный номер плательщика (РБ)


class Contact(BaseModel):
    """Контактное лицо контрагента."""

    id: int | None = None
    counterparty_id: int | None = None
    full_name: str
    phone: str | None = None
    email: str | None = None


class Sku(BaseModel):
    """Единица номенклатуры (товарная позиция)."""

    id: int | None = None
    code: str
    title: str
    unit: str = "шт"


class User(BaseModel):
    """Пользователь системы (сотрудник)."""

    id: int | None = None
    username: str
    full_name: str
    roles: list[str] = []
