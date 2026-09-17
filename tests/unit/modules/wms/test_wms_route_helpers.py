from decimal import Decimal
from types import SimpleNamespace

from modules.wms import routes


def test_warehouse_operation_card_contains_stage_action_and_detail_panel():
    card = routes._to_card(
        SimpleNamespace(
            id=2,
            number="",
            counterparty="ООО Альфа",
            title="Приёмка АКБ",
            items_count=4,
            amount=Decimal("500"),
            zone="A-01",
            priority="Высокий",
            owner="Кладовщик",
            stage="receiving",
            op_date="2026-09-17",
        )
    )
    assert (card.code, card.title, card.subtitle, card.action) == (
        "ОП-2",
        "Приёмка АКБ",
        "ООО Альфа",
        "Завершить приёмку",
    )
    assert card.tags == ["4 поз.", "A-01"]
    assert card.details == [
        {"k": "План", "v": "4 поз."},
        {"k": "Принято", "v": "4 поз."},
        {"k": "Отклонения", "v": "нет"},
    ]


def test_warehouse_operation_card_falls_back_to_counterparty_and_unknown_action():
    card = routes._to_card(
        SimpleNamespace(
            id=3,
            number="W-3",
            counterparty="Поставщик",
            title="",
            items_count=0,
            amount=0,
            zone="",
            priority="Средний",
            owner="",
            stage="unknown",
            op_date=None,
        )
    )
    assert (card.code, card.title, card.subtitle, card.action, card.details, card.tags) == (
        "W-3",
        "Поставщик",
        "",
        "",
        [],
        [],
    )


def test_inventory_line_and_summary_preserve_uncounted_lines_and_money_signs():
    shortage = routes._line_out(
        SimpleNamespace(
            id=1,
            sku_code="A",
            sku_title="A",
            unit="шт",
            expected_qty=Decimal("10"),
            counted_qty=Decimal("8.5"),
            unit_cost=Decimal("2.00"),
            note="",
        )
    )
    surplus = routes._line_out(
        SimpleNamespace(
            id=2,
            sku_code="B",
            sku_title="B",
            unit="шт",
            expected_qty=Decimal("1"),
            counted_qty=Decimal("3"),
            unit_cost=Decimal("4.25"),
            note="лишнее",
        )
    )
    not_counted = routes._line_out(
        SimpleNamespace(
            id=3,
            sku_code="C",
            sku_title="C",
            unit="шт",
            expected_qty=Decimal("5"),
            counted_qty=None,
            unit_cost=None,
            note="ждём пересчёт",
        )
    )
    assert (shortage.variance, shortage.variance_value) == (-1.5, -3.0)
    assert (not_counted.counted_qty, not_counted.variance, not_counted.variance_value) == (None, None, None)

    summary = routes._summary([shortage, surplus, not_counted])
    assert (
        summary.lines,
        summary.counted,
        summary.shortages,
        summary.surpluses,
        summary.shortage_value,
        summary.surplus_value,
        summary.net_value,
    ) == (3, 2, 1, 1, -3.0, 8.5, 5.5)
