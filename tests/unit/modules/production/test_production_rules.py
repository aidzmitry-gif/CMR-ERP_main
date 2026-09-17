from datetime import datetime

import pytest

from modules.production import routes
from modules.production.models import (
    ProductionBom,
    ProductionBomItem,
    ProductionOrder,
    ProductionWorker,
)


@pytest.mark.parametrize("value,expected", [(10, "10"), (7.5, "7,5"), (7.56, "7,6"), (0, "0")])
def test_norm_hours_format_is_russian_and_stable(value, expected):
    assert routes._nh_fmt(value) == expected


def test_production_card_maps_quantity_and_norm_hours():
    card = routes._to_card(
        ProductionOrder(id=4, product="Стеллаж", qty=3, nh_per_unit=2.5, number="", priority="Высокий", owner="Мастер", progress=40, insight="Проверить комплект")
    )
    assert card.code == "ПЗ-4"
    assert card.tags == ["3 шт", "7,5 н.ч"]
    assert card.progress == 40
    assert card.insight == "Проверить комплект"
    assert (
        routes._to_card(
            ProductionOrder(
                id=5,
                product="Товар",
                qty=0,
                nh_per_unit=0,
                priority="",
                owner="",
                insight="",
            )
        ).tags
        == []
    )


def test_norm_status_and_payroll_rounding():
    assert routes._norm_status(0) == "none"
    assert routes._norm_status(0.01) == "pending"
    row = routes._payroll_row(ProductionWorker(id=1, name="Иван", salary=1000, days_worked=11, nh_output=10))
    assert row.base == 500.0
    assert row.premium == 62.5
    assert row.total == 562.5
    assert row.contribution == 250.0
    assert routes._round2(1.236) == 1.24


def test_bom_status_and_coverage_boundaries():
    ok = ProductionBomItem(id=1, bom_id=2, component="A", norm_qty=5, stock=7, reserved=2)
    short = ProductionBomItem(id=2, bom_id=2, component="B", norm_qty=5, stock=6, reserved=2)
    assert routes._item_status(ok) == "ok"
    assert routes._item_status(short) == "short"
    assert routes._coverage([]) == 100
    assert routes._coverage([ok, short]) == 50


def test_bom_output_contains_computed_item_count_and_coverage():
    bom = ProductionBom(id=2, product="Стеллаж", version="v1", status="draft", note="")
    item = ProductionBomItem(id=1, bom_id=2, component="A", norm_qty=1, unit="шт", stock=1, reserved=0)
    out = routes._bom_out(bom, [item])
    item_out = routes._item_out(item)
    assert (out.item_count, out.coverage) == (1, 100)
    assert item_out.status == "ok"


def test_ytd_month_handles_past_current_and_future_years(monkeypatch):
    monkeypatch.setattr(routes, "_utcnow", lambda: datetime(2026, 9, 17, 12, 0))
    assert routes._ytd_month(2025) == 12
    assert routes._ytd_month(2026) == 9
    assert routes._ytd_month(2027) == 0
