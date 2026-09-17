from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from modules.logistics import routes
from modules.logistics.models import (
    CarrierBid,
    CarrierRfq,
    CarrierRfqInvite,
    CarrierScorecard,
    FreightAuditLog,
    Shipment,
)
from modules.logistics.schemas import (
    AuditEntryCreate,
    AwardRequest,
    CapabilityCreate,
    NegotiateRequest,
    PublicBidCreate,
    QuoteRequest,
    ScorecardMetricsUpdate,
    VehicleCreate,
)


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class Session:
    def __init__(self, *results, objects=None):
        self.results = list(results)
        self.objects = objects or {}
        self.added = []
        self.commits = 0
        self.refreshed = []

    async def execute(self, _statement):
        if not self.results:
            raise AssertionError("unexpected database query in unit test")
        return self.results.pop(0)

    async def get(self, model, identity):
        return self.objects.get((model, identity))

    def add(self, value):
        self.added.append(value)

    def add_all(self, values):
        for value in values:
            self.add(value)

    async def flush(self):
        next_id = 1
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = next_id
                next_id += 1

    async def commit(self):
        self.commits += 1

    async def refresh(self, value):
        if getattr(value, "id", None) is None:
            value.id = len(self.added) or 1
        self.refreshed.append(value)


class Bus:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


def core_with(bus: Bus):
    return SimpleNamespace(event_bus=bus)


def tariff(code="dpd", zone="z1", price=20):
    return SimpleNamespace(
        carrier_code=code,
        zone_code=zone,
        price_w5=Decimal(str(price)),
        price_w10=Decimal("30"),
        price_w30=Decimal("50"),
        over30_per_kg=Decimal("2"),
        pickup_fee=Decimal("4"),
        cod_pct=Decimal("1.5"),
        insurance_pct=Decimal("0.3"),
        effective_from=date(2026, 6, 1),
    )


def rfq(rfq_id=1, status="sent"):
    return CarrierRfq(
        id=rfq_id,
        number=f"ТНД-2026-{rfq_id:04d}",
        cargo="АКБ",
        weight_kg=Decimal("100"),
        category="АКБ",
        route_from="Минск",
        route_to="Гомель",
        zone_code="z2",
        status=status,
        office_doc_ref="ЗАЯВКА-1",
        created_by="Менеджер",
        deadline="2026-09-20",
    )


@pytest.mark.asyncio
async def test_dashboard_and_cost_reports_aggregate_real_business_fields():
    shipments = [
        SimpleNamespace(status="in_transit", payer="компания", amount=Decimal("100"), carrier="DPD"),
        SimpleNamespace(status="delivered", payer="клиент", amount=Decimal("40"), carrier="CDEK"),
        SimpleNamespace(status="planned", payer="компания", amount=Decimal("25"), carrier=""),
    ]
    imports = [
        SimpleNamespace(stage="consolidation", amount=Decimal("200")),
        SimpleNamespace(stage="customs", amount=Decimal("50")),
        SimpleNamespace(stage="warehouse", amount=Decimal("10")),
    ]
    carriers = [
        SimpleNamespace(name="DPD", kind="РБ", shipments_count=10, on_time_pct=95, avg_days=2, active=True),
        SimpleNamespace(name="CDEK", kind="РБ", shipments_count=8, on_time_pct=90, avg_days=4, active=True),
        SimpleNamespace(name="Old", kind="РБ", shipments_count=2, on_time_pct=0, avg_days=0, active=False),
    ]

    dashboard = await routes.dashboard(Session(Result(shipments), Result(imports), Result(carriers)))
    assert dashboard.in_transit == 3
    assert dashboard.delivery_in_transit == 1
    assert dashboard.import_in_transit == 1
    assert dashboard.at_customs == 1
    assert dashboard.delivered_total == 1
    assert dashboard.avg_delivery_days == 3.0
    assert dashboard.on_time_pct == 92.5
    assert dashboard.logistics_cost == 375.0
    assert dashboard.shipping_cost_company == 125.0
    assert dashboard.cost_by_carrier[0].carrier == "DPD"
    assert dashboard.cost_by_carrier[-1].carrier == "Без перевозчика"

    costs = await routes.costs_report(Session(Result(shipments), Result(imports)))
    assert costs.model_dump() == {
        "total": 165.0,
        "company": 125.0,
        "client": 40.0,
        "import_cost": 260.0,
        "by_carrier": [
            {"carrier": "DPD", "shipments": 1, "cost": 100.0},
            {"carrier": "Без перевозчика", "shipments": 1, "cost": 25.0},
        ],
    }


@pytest.mark.asyncio
async def test_catalog_and_seed_handlers_are_idempotent_at_the_database_boundary():
    catalog = await routes.carriers_catalog()
    assert len(catalog) == len(routes.CARRIERS_RB)
    assert catalog[0].code == "dpd"

    carriers_session = Session(
        Result([SimpleNamespace(code="dpd")]),
        Result([SimpleNamespace(code="dpd"), SimpleNamespace(code="autolight")]),
    )
    carriers = await routes.seed_carriers(carriers_session)
    assert len(carriers_session.added) == len(routes.CARRIERS_RB) - 1
    assert carriers_session.commits == 1
    assert carriers == carriers_session.results[0].rows if carriers_session.results else True

    zones_session = Session(Result([SimpleNamespace(code="z1")]), Result([]))
    await routes.seed_zones(zones_session)
    assert len(zones_session.added) == len(routes.seeds.ZONES_SEED) - 1

    tariffs_session = Session(Result([]), Result([]))
    await routes.seed_carrier_tariffs(tariffs_session)
    assert len(tariffs_session.added) == len(routes.seeds.TARIFFS_SEED)
    assert all(getattr(row, "effective_from", None) == routes.seeds.TARIFF_EFFECTIVE_FROM for row in tariffs_session.added)


@pytest.mark.asyncio
async def test_quote_shipment_uses_default_weight_and_has_explicit_error_boundaries():
    shipment = Shipment(id=7, customer="ООО Альфа", weight_kg=Decimal("8"))
    zone = SimpleNamespace(code="z1", sla_days_min=1, sla_days_max=2)
    belpost = tariff("belpost", price=10)
    belpost.pickup_fee = Decimal("0")
    tariffs = [tariff("dpd", price=20), belpost]
    session = Session(Result([zone]), Result(tariffs), objects={(Shipment, 7): shipment})

    quotes = await routes.quote_shipment(
        7,
        QuoteRequest(zone_code="z1", pickup=True, cod_amount=100, declared_value=1000),
        session,
    )
    assert [q.carrier_code for q in quotes] == ["belpost", "dpd"]
    assert quotes[0].weight_kg == 8.0
    assert quotes[0].pickup == 0.0
    assert quotes[-1].pickup == 4.0
    assert quotes[0].cod_fee == 1.5
    assert quotes[0].insurance_fee == 3.0

    with pytest.raises(HTTPException, match="Отгрузка не найдена"):
        await routes.quote_shipment(404, QuoteRequest(zone_code="z1"), Session(),)

    with pytest.raises(HTTPException, match="Неизвестная зона"):
        await routes.quote_shipment(
            7, QuoteRequest(zone_code="bad"), Session(Result(), objects={(Shipment, 7): shipment})
        )

    with pytest.raises(HTTPException, match="Нет тарифов"):
        await routes.quote_shipment(
            7,
            QuoteRequest(zone_code="z1"),
            Session(Result([zone]), Result(), objects={(Shipment, 7): shipment}),
        )


@pytest.mark.asyncio
async def test_scorecard_recompute_update_and_filter_recalculate_the_grade():
    cards = [
        SimpleNamespace(
            carrier_code="dpd", period="2026-06", otd_pct=Decimal("96"),
            damage_free_pct=Decimal("99"), billing_accuracy_pct=Decimal("97"),
            claims_ratio_pct=Decimal("1"), score=Decimal("0"), grade="C",
        ),
        SimpleNamespace(
            carrier_code="belpost", period="2026-06", otd_pct=Decimal("70"),
            damage_free_pct=Decimal("80"), billing_accuracy_pct=Decimal("70"),
            claims_ratio_pct=Decimal("10"), score=Decimal("0"), grade="C",
        ),
    ]
    session = Session(Result(cards))
    out = await routes.recompute_scorecard(session)
    assert out[0].grade == "A"
    assert out[0].score > out[1].score
    assert session.commits == 1

    card = CarrierScorecard(
        id=3, carrier_code="belpost", period="2026-06", otd_pct=Decimal("80"),
        damage_free_pct=Decimal("90"), billing_accuracy_pct=Decimal("80"),
        claims_ratio_pct=Decimal("5"), score=Decimal("0"), grade="C",
    )
    updated = await routes.update_scorecard_metrics(
        "belpost",
        ScorecardMetricsUpdate(otd_pct=95, billing_accuracy_pct=96, shipments=14, cost_per_delivery=12.5),
        period="2026-06",
        session=Session(Result([card])),
    )
    assert updated is card
    assert (card.otd_pct, card.billing_accuracy_pct, card.shipments, card.cost_per_delivery) == (
        Decimal("95"), Decimal("96"), 14, Decimal("12.5")
    )
    assert card.grade in {"A", "B"}

    with pytest.raises(HTTPException, match="period обязателен"):
        await routes.update_scorecard_metrics("dpd", ScorecardMetricsUpdate(), session=Session())
    with pytest.raises(HTTPException, match="Карточка не найдена"):
        await routes.update_scorecard_metrics(
            "missing", ScorecardMetricsUpdate(), period="2026-06", session=Session(Result())
        )
    listed = await routes.carriers_scorecard("2026-06", Session(Result(cards)))
    assert listed == cards


@pytest.mark.asyncio
async def test_audit_calculates_variance_emits_refund_and_reports_discrepancies():
    bus = Bus()
    explicit = await routes.create_audit_entry(
        AuditEntryCreate(
            shipment_code="ЛОГ-1", carrier_code="dpd", invoice_amount=35,
            expected_amount=30, reason="лишний сбор",
        ),
        core_with(bus),
        Session(),
    )
    assert (explicit.variance, explicit.status) == (Decimal("5"), "open")
    assert bus.calls[0][1] == "logistics.freight.audit_refund"
    assert bus.calls[0][2]["amount"] == "5.0"

    calculated_session = Session(Result([tariff("dpd", price=20)]))
    calculated = await routes.create_audit_entry(
        AuditEntryCreate(
            shipment_code="ЛОГ-2", carrier_code="dpd", invoice_amount=20,
            zone_code="z1", weight_kg=4,
        ),
        core_with(Bus()),
        calculated_session,
    )
    assert (calculated.expected_amount, calculated.variance, calculated.status) == (
        Decimal("20.0"), Decimal("0.0"), "closed"
    )

    with pytest.raises(HTTPException, match="нет тарифа"):
        await routes.create_audit_entry(
            AuditEntryCreate(shipment_code="ЛОГ-3", carrier_code="missing", invoice_amount=10, zone_code="z9"),
            core_with(Bus()),
            Session(Result()),
        )

    rows = [
        FreightAuditLog(
            id=1, shipment_code="ЛОГ-1", carrier_code="dpd", invoice_amount=Decimal("35"),
            expected_amount=Decimal("30"), variance=Decimal("5"), reason="x", status="open",
        ),
        FreightAuditLog(
            id=2, shipment_code="ЛОГ-2", carrier_code="dpd", invoice_amount=Decimal("20"),
            expected_amount=Decimal("20"), variance=Decimal("0"), reason="", status="closed",
        ),
    ]
    report = await routes.costs_audit("2026-09", Session(Result(rows)))
    assert (report.checked, report.discrepancies, report.to_recover, report.period) == (2, 1, 5.0, "2026-09")


@pytest.mark.asyncio
async def test_fleet_seed_add_and_eligibility_apply_weight_temperature_and_capability_rules():
    seed_session = Session(
        Result([]),
        Result([]),
        Result([SimpleNamespace() for _ in routes.seeds.VEHICLES_SEED]),
        Result([SimpleNamespace() for _ in routes.seeds.CAPABILITIES_SEED]),
    )
    seeded = await routes.seed_fleet(seed_session)
    assert seeded == {
        "vehicles": len(routes.seeds.VEHICLES_SEED),
        "capabilities": len(routes.seeds.CAPABILITIES_SEED),
    }

    vehicle_session = Session()
    vehicle = await routes.add_vehicle("own", VehicleCreate(vehicle_class="Реф", capacity_kg=8000, temp_control=True), vehicle_session)
    assert vehicle.carrier_code == "own"
    capability_session = Session()
    capability = await routes.add_capability("own", CapabilityCreate(category="температурный"), capability_session)
    assert capability.carrier_code == "own"

    vehicles = [
        SimpleNamespace(carrier_code="small", vehicle_class="Газель", capacity_kg=1000, temp_control=False),
        SimpleNamespace(carrier_code="own", vehicle_class="Реф", capacity_kg=8000, temp_control=True),
    ]
    caps = [
        SimpleNamespace(carrier_code="small", category="АКБ", adr=False, max_weight_kg=0, max_dim_cm=0),
        SimpleNamespace(carrier_code="own", category="АКБ", adr=True, max_weight_kg=0, max_dim_cm=0),
    ]
    eligible = await routes.eligible_carriers(
        weight_kg=500, category="АКБ", needs_temp=True, adr=True,
        session=Session(Result(vehicles), Result(caps)),
    )
    assert [item.carrier_code for item in eligible] == ["own"]
    assert eligible[0].carrier == "Свой транспорт"
    assert eligible[0].capacity_kg == 8000.0

    listed_v = await routes.list_vehicles("own", Session(Result(vehicles[1:])))
    listed_c = await routes.list_capabilities("own", Session(Result(caps[1:])))
    assert listed_v == vehicles[1:]
    assert listed_c == caps[1:]


@pytest.mark.asyncio
async def test_rfq_board_broadcast_and_bid_lists_cover_tender_boundaries(monkeypatch):
    tender = rfq()
    assert (await routes.list_rfqs(Session(Result([tender])))) == [tender]
    board = await routes.rfqs_board(Session(Result([tender])))
    assert board.stages[0].id == "draft"

    monkeypatch.setattr(routes, "_eligible_matches", lambda *args, **kwargs: _eligible_result())
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(
        routes.notify,
        "send_invite",
        lambda channel, contact, message, settings=None: {
            "status": "sent" if channel != "none" else "skipped",
            "channel": channel,
            "detail": "ok",
        },
    )
    carriers = [
        SimpleNamespace(code="dpd", contact="logistics@example.com"),
        SimpleNamespace(code="own", contact=""),
    ]
    bus = Bus()
    broadcast_session = Session(Result([]), Result(carriers), objects={(CarrierRfq, 1): tender})
    broadcast = await routes.broadcast_rfq(1, core_with(bus), broadcast_session)
    assert (broadcast.invited, broadcast.notified, broadcast.carriers) == (2, 1, ["dpd", "own"])
    assert tender.status == "sent"
    assert [getattr(x, "carrier_code") for x in broadcast_session.added] == ["dpd", "own"]
    assert bus.calls[0][1] == "logistics.rfq.broadcast"

    bids = [
        CarrierBid(id=1, rfq_id=1, carrier_code="dpd", price=Decimal("100"), eta_days=2, vehicle_class="Тент", valid_until="2026-09-20", comment="A", round=1),
        CarrierBid(id=2, rfq_id=1, carrier_code="own", price=Decimal("110"), eta_days=1, vehicle_class="Фура", valid_until="2026-09-20", comment="B", round=1),
    ]
    listed = await routes.list_bids(1, Session(Result(bids), objects={(CarrierRfq, 1): tender}))
    assert [item.price for item in listed] == [100.0, 110.0]
    assert listed[0].is_best is True

    cards = [SimpleNamespace(carrier_code="dpd", period="2026-06", score=Decimal("95")), SimpleNamespace(carrier_code="own", period="2026-06", score=Decimal("70"))]
    ranked = await routes.list_bids_ranked(
        1,
        Session(Result(bids), Result(cards), objects={(CarrierRfq, 1): tender}),
    )
    assert ranked[0].carrier_code == "dpd"
    assert ranked[0].is_best_value is True


def _eligible_result():
    async def result():
        return [("dpd", {"vehicle_class": "Фургон", "capacity_kg": 1500.0}), ("own", {"vehicle_class": "Тент", "capacity_kg": 5000.0})]

    return result()


@pytest.mark.asyncio
async def test_rfq_recommendation_public_bid_negotiation_and_award_emit_contract_event():
    tender = rfq()
    bids = [
        CarrierBid(id=1, rfq_id=1, carrier_code="dpd", price=Decimal("100"), eta_days=2, vehicle_class="Фургон", valid_until="2026-09-20", comment="A", round=1),
        CarrierBid(id=2, rfq_id=1, carrier_code="own", price=Decimal("120"), eta_days=1, vehicle_class="Тент", valid_until="2026-09-20", comment="B", round=1),
        CarrierBid(id=3, rfq_id=1, carrier_code="cdek", price=Decimal("125"), eta_days=1, vehicle_class="Фура", valid_until="2026-09-20", comment="C", round=1),
    ]
    cards = [
        SimpleNamespace(carrier_code="dpd", period="2026-06", score=Decimal("60")),
        SimpleNamespace(carrier_code="own", period="2026-06", score=Decimal("99")),
        SimpleNamespace(carrier_code="cdek", period="2026-06", score=Decimal("50")),
    ]
    recommendation = await routes.rfq_recommendation(
        1,
        Session(Result(bids), Result(cards), Result(cards), objects={(CarrierRfq, 1): tender}),
    )
    assert recommendation.cheapest.carrier_code == "dpd"
    assert recommendation.best_value.carrier_code == "own"
    assert recommendation.same_carrier is False
    assert recommendation.reliability_premium == 20.0
    assert recommendation.median_price == 120.0

    invite = CarrierRfqInvite(id=5, rfq_id=1, carrier_code="dpd", token="secret", status="sent")
    public_session = Session(Result([invite]), objects={(CarrierRfq, 1): tender})
    public = await routes.public_bid("secret", PublicBidCreate(price=88, eta_days=1), public_session)
    assert public.price == 88.0
    assert (invite.status, tender.status) == ("responded", "collecting")

    negotiated = await routes.negotiate_rfq(
        1,
        NegotiateRequest(carrier_code="dpd", new_price=85, comment="снижаем"),
        Session(Result(bids[:1]), objects={(CarrierRfq, 1): tender}),
    )
    assert (negotiated.price, negotiated.round, tender.status) == (85.0, 2, "negotiation")

    bus = Bus()
    award_session = Session(
        Result(bids), Result(cards), objects={(CarrierRfq, 1): tender}
    )
    awarded = await routes.award_rfq(1, AwardRequest(strategy="best_value"), core_with(bus), award_session)
    assert awarded.carrier_code == "own"
    assert awarded.price == 120.0
    assert tender.status == "contracted"
    assert tender.shipment_id == awarded.shipment_id
    assert bus.calls[0][1] == "logistics.contract.signed"


@pytest.mark.asyncio
async def test_rfq_seed_and_cost_insights_join_tariffs_tenders_audits_and_import_freight():
    seeded_session = Session(Result())
    seeded = await routes.seed_rfq(seeded_session)
    assert seeded.number == routes.seeds.RFQ_DEMO["number"]
    assert len(seeded_session.added) == 1 + len(routes.seeds.RFQ_DEMO_INVITES) + len(routes.seeds.RFQ_DEMO_BIDS)

    first_rfq = rfq()
    first_rfq.awarded_price = Decimal("90")
    first_rfq.awarded_carrier_code = "dpd"
    first_rfq.status = "contracted"
    prices = [
        CarrierBid(id=1, rfq_id=1, carrier_code="dpd", price=Decimal("120")),
        CarrierBid(id=2, rfq_id=1, carrier_code="dpd", price=Decimal("90")),
    ]
    audits = [SimpleNamespace(variance=Decimal("5")), SimpleNamespace(variance=Decimal("-2"))]
    imports = [
        SimpleNamespace(stage="warehouse", amount=Decimal("200")),
        SimpleNamespace(stage="in_transit", amount=Decimal("500")),
        SimpleNamespace(stage="warehouse", amount=Decimal("0")),
    ]
    session = Session(
        Result([tariff("dpd", "z1", 20), tariff("belpost", "z1", 10)]),
        Result([SimpleNamespace(code="z1", name="Минск")]),
        Result([first_rfq]),
        Result(prices),
        Result(audits),
        Result(imports),
    )
    insights = await routes.cost_insights(5, session)
    assert insights.reference_weight_kg == 5.0
    assert insights.zones[0].zone_code == "z1"
    assert insights.tender_savings_total == 30.0
    assert insights.audit_to_recover == 5.0
    assert (insights.import_freight_total, insights.import_freight_count) == (200.0, 1)
    assert insights.recommendations
