from decimal import Decimal
from types import SimpleNamespace

from modules.logistics import routes


def test_route_and_quantity_tags_keep_empty_values_out_of_ui_contract():
    assert routes._route("Минск", "Брест") == "Минск → Брест"
    assert routes._route("", "Брест") == "Брест"
    assert routes._route("", "", "не задан") == "не задан"
    assert routes._qty_tag(3) == ["3 шт"]
    assert routes._qty_tag(0) == []


def test_shipment_card_contains_route_tracking_and_nonempty_tags():
    card = routes._shipment_card(
        SimpleNamespace(
            id=7,
            number="LOG-7",
            customer="ООО Альфа",
            route_from="Минск",
            route_to="Брест",
            address="ул. Ленина",
            amount=Decimal("125.50"),
            priority="Высокий",
            carrier="DPD",
            owner="Оператор",
            eta="2026-09-20",
            tracking_status="В пути",
            tracking_no="TR-7",
            insight="Контроль ETA",
            cargo="Плата",
            weight_kg=Decimal("2.5"),
            carrier_order_no="C-7",
        )
    )
    assert (card.code, card.title, card.subtitle, card.amount) == (
        "LOG-7",
        "ООО Альфа",
        "Минск → Брест",
        125.5,
    )
    assert card.tags == ["Плата", "2.5 кг", "№ C-7"]
    assert card.score == "📍 TR-7"


def test_import_card_switches_customs_status_and_builds_po_tags():
    card = routes._import_card(
        SimpleNamespace(
            id=8,
            number="",
            supplier="Factory",
            flag="🇨🇳",
            container_no="CNT-8",
            route="Шэньчжэнь → Минск",
            incoterms="FOB",
            mode="море",
            cargo="АКБ",
            qty=12,
            amount=Decimal("300"),
            priority="Средний",
            owner="Импорт",
            stage=routes.CUSTOMS_STAGE,
            customs_status="Декларация",
            eta="2026-10-01",
            po_ref="PO-8",
            insight="Проверить документы",
        )
    )
    assert (card.code, card.title, card.status_tag, card.score) == (
        "ИМП-8",
        "АКБ",
        "Декларация",
        "PO PO-8",
    )
    assert card.tags == ["CNT-8", "FOB", "12 шт"]

    card = routes._import_card(
        SimpleNamespace(
            id=9,
            number="IMP-9",
            supplier="Factory",
            flag="🇨🇳",
            container_no="",
            route="",
            incoterms="",
            mode="авто",
            cargo="",
            qty=0,
            amount=0,
            priority="Средний",
            owner="",
            stage="factory",
            customs_status="",
            eta=None,
            po_ref="",
            insight="",
        )
    )
    assert (card.title, card.subtitle, card.status_tag, card.tags) == (
        "Factory",
        "Factory",
        "авто",
        [],
    )


def test_company_cost_aggregates_only_company_paid_shipments_and_sorts_descending():
    stats = routes._company_cost_by_carrier(
        [
            SimpleNamespace(payer="компания", carrier="DPD", amount=Decimal("20")),
            SimpleNamespace(payer="компания", carrier="DPD", amount=Decimal("5.50")),
            SimpleNamespace(payer="клиент", carrier="DPD", amount=Decimal("100")),
            SimpleNamespace(payer="компания", carrier="", amount=None),
            SimpleNamespace(payer="компания", carrier="CDEK", amount=Decimal("40")),
        ]
    )
    assert [(item.carrier, item.shipments, item.cost) for item in stats] == [
        ("CDEK", 1, 40.0),
        ("DPD", 2, 25.5),
        ("Без перевозчика", 1, 0.0),
    ]


def test_scorecard_recomputes_score_and_grade_from_quality_metrics():
    card = SimpleNamespace(
        otd_pct=95,
        damage_free_pct=98,
        billing_accuracy_pct=97,
        claims_ratio_pct=2,
        score=None,
        grade=None,
    )
    routes._apply_score(card)
    assert card.score == Decimal("96.6")
    assert card.grade == "A"


def _bid(identifier: int, carrier: str, price: str):
    return SimpleNamespace(
        id=identifier,
        rfq_id=1,
        carrier_code=carrier,
        price=Decimal(price),
        eta_days=4,
        vehicle_class="van",
        valid_until="2026-09-30",
        comment="",
        round=1,
    )


def test_bid_helpers_return_named_carrier_and_mark_lowest_price():
    one = routes._bid_out(_bid(1, "unknown-carrier", "100"), value_score=0.5)
    assert (one.id, one.carrier, one.price, one.value_score) == (1, "unknown-carrier", 100.0, 0.5)

    ordered = routes._bids_with_best([_bid(1, "dpd", "100"), _bid(2, "cdek", "80")])
    assert [item.id for item in ordered] == [2, 1]
    assert [item.is_best for item in ordered] == [True, False]
    assert routes._bids_with_best([]) == []


def test_rfq_card_uses_route_fallback_and_only_real_tags():
    card = routes._rfq_card(
        SimpleNamespace(
            id=3,
            number="",
            route_to="Брест",
            cargo="АКБ",
            route_from="Минск",
            weight_kg=Decimal("7"),
            category="опасный_ADR",
            awarded_price=Decimal("90"),
            created_by="Логист",
            deadline="2026-09-25",
            office_doc_ref="OFF-3",
        )
    )
    assert (card.code, card.title, card.subtitle, card.amount) == (
        "ТНД-3",
        "Брест",
        "Минск → Брест",
        90.0,
    )
    assert card.tags == ["АКБ", "7 кг", "опасный_ADR"]
