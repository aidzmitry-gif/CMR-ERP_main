from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from modules.procurement import routes
from modules.procurement.schemas import PurchaseOrderLineIn


def test_supplier_score_is_honest_for_empty_and_partial_history():
    assert routes._score_components(0, 0, None) == {
        "components": {"quality": None, "timeliness": None, "price": None},
        "score": None,
    }
    quality_only = routes._score_components(4, 1, None)
    assert quality_only["components"] == {"quality": 0.75, "timeliness": None, "price": None}
    assert quality_only["score"] == 7.5

    combined = routes._score_components(10, 1, 0.8)
    assert combined["components"]["quality"] == 0.9
    assert combined["score"] == 8.6


def test_purchase_request_card_marks_deficit_origin_and_preserves_score():
    card = routes._to_card(
        SimpleNamespace(
            id=5,
            number="",
            item="Подшипник",
            supplier="ACME",
            flag="🇧🇾",
            amount=Decimal("120"),
            priority="Высокий",
            owner="Закупки",
            due_date="2026-09-25",
            insight="Низкий остаток",
            qty=3,
            origin="deficit",
        ),
        score=8.6,
    )
    assert (card.code, card.score, card.status_tag, card.tags) == (
        "ЗАК-5",
        "Score 8.6",
        "Авто: дефицит склада",
        ["3 шт"],
    )


def test_order_allocation_aggregates_skus_and_falls_back_to_value_basis_without_weights():
    lines = [
        SimpleNamespace(
            sku_code="A",
            qty=Decimal("2"),
            goods_value_byn=Decimal("100"),
            weight=Decimal("1"),
            volume=Decimal("0.1"),
        ),
        SimpleNamespace(
            sku_code="A",
            qty=Decimal("1"),
            goods_value_byn=Decimal("50"),
            weight=Decimal("2"),
            volume=Decimal("0.2"),
        ),
        SimpleNamespace(
            sku_code="B",
            qty=Decimal("1"),
            goods_value_byn=Decimal("200"),
            weight=Decimal("0"),
            volume=Decimal("0"),
        ),
        SimpleNamespace(
            sku_code="",
            qty=Decimal("1"),
            goods_value_byn=Decimal("999"),
            weight=Decimal("1"),
            volume=Decimal("1"),
        ),
    ]
    result, agg = routes._order_allocation(lines, Decimal("30"))
    assert agg == {
        "A": {"qty": Decimal("3"), "goods": Decimal("150"), "weight": Decimal("3"), "volume": Decimal("0.3")},
        "B": {"qty": Decimal("1"), "goods": Decimal("200"), "weight": Decimal("0"), "volume": Decimal("0")},
    }
    assert result["total_allocated"] == Decimal("30.00")
    assert [line["sku_code"] for line in result["lines"]] == ["A", "B"]
    assert [line["allocated"] for line in result["lines"]] == [Decimal("12.86"), Decimal("17.14")]


def test_validate_transition_allows_forward_idempotent_and_cancel_but_rejects_invalid_backwards():
    for current, new in [("draft", "draft"), ("draft", "received"), ("ordered", "cancelled")]:
        routes._validate_transition(current, new)

    with pytest.raises(HTTPException) as exc:
        routes._validate_transition("received", "cancelled")
    assert exc.value.status_code == 409

    with pytest.raises(HTTPException) as exc:
        routes._validate_transition("shipped", "ordered")
    assert exc.value.status_code == 422

    with pytest.raises(HTTPException) as exc:
        routes._validate_transition("unknown", "ordered")
    assert exc.value.status_code == 422


def test_new_line_converts_api_numbers_to_decimal_orm_values():
    line = routes._new_line(
        9,
        PurchaseOrderLineIn(
            sku_code="SKU-9",
            qty=2.5,
            goods_value_byn=100.25,
            weight=3.2,
            volume=0.4,
        ),
    )
    assert (line.order_id, line.sku_code) == (9, "SKU-9")
    assert (line.qty, line.goods_value_byn, line.weight, line.volume) == (
        Decimal("2.5"),
        Decimal("100.25"),
        Decimal("3.2"),
        Decimal("0.4"),
    )


def test_rfq_output_sorts_bids_and_marks_lowest_price():
    rfq = SimpleNamespace(
        id=4,
        item="АКБ",
        sku_code="BAT-1",
        qty=Decimal("5"),
        request_id=8,
        status="open",
        due_date=date(2026, 10, 1),
    )
    bids = [
        SimpleNamespace(id=2, rfq_id=4, supplier_id=22, price_byn=Decimal("110"), lead_time_days=5, incoterms="FOB", note="", is_winner=False),
        SimpleNamespace(id=1, rfq_id=4, supplier_id=11, price_byn=Decimal("90"), lead_time_days=7, incoterms="CIF", note="best", is_winner=True),
    ]
    out = routes._rfq_out(rfq, bids, created_order_id=12)
    assert (out.best_bid_id, out.created_order_id, [bid.id for bid in out.bids]) == (1, 12, [1, 2])
    assert out.bids[0].price_byn == 90.0


def test_order_plan_reports_deadline_slack_and_overdue_deal_risk():
    order = SimpleNamespace(
        id=10,
        transport_method_code="truck",
        target_arrival_date=date(2026, 9, 20),
    )
    milestones = [
        SimpleNamespace(stage="collection", seq=0, duration_days=2, planned_date=date(2026, 9, 18), actual_date=None),
        SimpleNamespace(stage="to_minsk", seq=1, duration_days=4, planned_date=date(2026, 9, 20), actual_date=None),
    ]
    requirements = [
        SimpleNamespace(
            deal_id=3,
            number="D-3",
            counterparty="ACME",
            sku_code="SKU-3",
            ship_deadline="25.09.2026",
            ship_deadline_date=date(2026, 9, 25),
            penalty_rate_pct=Decimal("0.5"),
            penalty_cap_pct=Decimal("10"),
            penalty_terms="за день",
        ),
        SimpleNamespace(
            deal_id=4,
            number="D-4",
            counterparty="Beta",
            sku_code="SKU-4",
            ship_deadline="30.09.2026",
            ship_deadline_date=date(2026, 9, 30),
            penalty_rate_pct=None,
            penalty_cap_pct=None,
            penalty_terms=None,
        ),
    ]
    out = routes._plan_out(order, milestones, requirements, date(2026, 9, 10))
    assert (out.required_by, out.required_arrival, out.slack_days, out.at_risk) == (
        date(2026, 9, 25),
        date(2026, 9, 22),
        2,
        False,
    )
    assert out.start_date == date(2026, 9, 16)
    assert out.total_days == 6
    assert out.at_risk_deals == []

    late = routes._plan_out(
        SimpleNamespace(id=11, transport_method_code="truck", target_arrival_date=date(2026, 9, 25)),
        milestones,
        requirements[:1],
        date(2026, 9, 10),
    )
    assert late.at_risk is True
    assert late.at_risk_deals[0].deal_id == 3
    assert late.at_risk_deals[0].slack_days == -3
