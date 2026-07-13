"""Контракт PriceCostGateway (PC1): форма ``ItemPriceCost``, честная деградация (фасад ``None``),
провенанс источника. Реальный источник (1С через ``integrations``) тестируется не здесь — тут
только шов ядра: потребители зависят от этой формы, при подключении 1С меняется лишь реализация.
"""
from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from core.services import build_services
from core.services.price_cost import ItemPriceCost, PriceCostGateway

pytestmark = pytest.mark.unit


def test_services_price_cost_defaults_to_none():
    # Источник цены/себес не подключён по умолчанию → потребители деградируют честно (нет данных).
    assert build_services().price_cost is None


def test_item_price_cost_defaults_are_honest_empty():
    # Пустая запись: None по деньгам (НЕ 0 — пустое ≠ бесплатно), валюта BYN, источник неизвестен.
    item = ItemPriceCost()
    assert item.cost_byn is None
    assert item.price_byn is None
    assert item.currency == "BYN"
    assert item.price_type is None
    assert item.as_of is None
    assert item.source is None


def test_item_price_cost_carries_provenance():
    item = ItemPriceCost(
        cost_byn=120.0, price_byn=200.0, price_type="оптовая",
        as_of=date(2026, 7, 1), source="onec",
    )
    assert (item.cost_byn, item.price_byn, item.source) == (120.0, 200.0, "onec")
    assert item.price_type == "оптовая"
    assert item.as_of == date(2026, 7, 1)


def test_item_price_cost_is_frozen():
    # Иммутабельность: значение из учёта не правится «по месту» у потребителя.
    item = ItemPriceCost(price_byn=10.0)
    with pytest.raises(FrozenInstanceError):
        item.price_byn = 20.0  # type: ignore[misc]


class _FakeSource:
    """Тривиальная реализация протокола (структурная типизация) — проверка формы возврата."""

    async def get_item_price_cost(self, session, sku_codes):
        table = {"SKU-1": ItemPriceCost(cost_byn=50.0, price_byn=90.0, source="demo")}
        return {c: table[c] for c in sku_codes if c in table}


async def test_gateway_returns_only_found_codes():
    src: PriceCostGateway = _FakeSource()
    out = await src.get_item_price_cost(None, ["SKU-1", "SKU-404"])
    assert set(out) == {"SKU-1"}          # отсутствующий код НЕ в словаре (нет данных по нему)
    assert out["SKU-1"].price_byn == 90.0
    assert out["SKU-1"].source == "demo"


async def test_gateway_empty_input_empty_output():
    src: PriceCostGateway = _FakeSource()
    assert await src.get_item_price_cost(None, []) == {}
