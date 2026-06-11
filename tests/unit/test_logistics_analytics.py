"""Юнит-тесты аналитики стоимости (cost-insights) — чистые функции без I/O."""
from modules.logistics import analytics


def test_zone_cost_insight_picks_cheapest_and_spread():
    quotes = [
        {"carrier_code": "dpd", "carrier": "DPD", "total": 100.0},
        {"carrier_code": "autolight", "carrier": "Автолайт Экспресс", "total": 80.0},
        {"carrier_code": "cdek", "carrier": "СДЭК", "total": 120.0},
    ]
    ins = analytics.zone_cost_insight("z2", "Зона 2", quotes)
    assert ins["cheapest_carrier"] == "autolight"
    assert ins["cheapest_carrier_name"] == "Автолайт Экспресс"
    assert ins["cheapest_total"] == 80.0
    assert ins["max_total"] == 120.0
    assert ins["avg_total"] == 100.0          # (100 + 80 + 120) / 3
    assert ins["spread_pct"] == 50.0          # (120 − 80) / 80 × 100
    assert ins["carriers"] == 3


def test_zone_cost_insight_empty_is_none():
    assert analytics.zone_cost_insight("z9", "Пусто", []) is None


def test_tender_saving_baseline_minus_awarded():
    ts = analytics.tender_saving("ТНД-1", "Минск → Гомель", "Свой транспорт", [740.0, 680.0, 600.0])
    assert ts["baseline"] == 740.0 and ts["awarded"] == 600.0
    assert ts["saved"] == 140.0
    assert ts["saved_pct"] == round(140 / 740 * 100, 2)   # ≈ 18.92


def test_tender_saving_empty_is_none():
    assert analytics.tender_saving("ТНД-2", "", "X", []) is None


def test_summarize_aggregates_potential_and_best_zone():
    zones = [
        analytics.zone_cost_insight("z1", "Z1", [
            {"carrier_code": "a", "carrier": "A", "total": 50.0},
            {"carrier_code": "b", "carrier": "B", "total": 70.0}]),    # avg 60, cheapest 50 → потенциал 10
        analytics.zone_cost_insight("z2", "Z2", [
            {"carrier_code": "c", "carrier": "C", "total": 100.0},
            {"carrier_code": "d", "carrier": "D", "total": 200.0}]),   # avg 150, cheapest 100 → потенциал 50
    ]
    tenders = [analytics.tender_saving("ТНД-1", "r", "C", [200.0, 150.0])]  # saved 50
    out = analytics.summarize(30.0, zones, tenders, audit_to_recover=33.3)
    assert out["best_savings_zone"] == "z2"        # потенциал 50 > 10
    assert out["potential_savings"] == 60.0        # 10 + 50
    assert out["tender_savings_total"] == 50.0
    assert out["audit_to_recover"] == 33.3
    assert out["reference_weight_kg"] == 30.0
    assert len(out["recommendations"]) >= 1


def test_summarize_empty_is_zeroed():
    out = analytics.summarize(30.0, [], [], audit_to_recover=0.0)
    assert out["zones"] == [] and out["tenders"] == []
    assert out["potential_savings"] == 0 and out["best_savings_zone"] == ""
    assert out["recommendations"] == []


def test_recommendations_mention_cheapest_and_audit():
    zones = [analytics.zone_cost_insight("z2", "Z2", [
        {"carrier_code": "c", "carrier": "СДЭК", "total": 100.0},
        {"carrier_code": "d", "carrier": "Автолайт", "total": 200.0}])]
    recs = analytics.build_recommendations(zones, [], audit_to_recover=10.0)
    assert any("СДЭК" in r for r in recs)             # самый дешёвый в зоне
    assert any("возврату" in r for r in recs)          # аудит
