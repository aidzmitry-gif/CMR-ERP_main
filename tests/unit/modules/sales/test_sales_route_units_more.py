from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from core.services.price_cost import ItemPriceCost
from modules.sales import routes
from modules.sales.models import (
    Activity,
    CompanyBranding,
    Deal,
    DealDocument,
    DealItem,
    DealStageEvent,
    DealTask,
    KpiTarget,
    Message,
    PlanItem,
    PlanTarget,
    PriceQuote,
    Stage,
)
from modules.sales.schemas import (
    ActivityCreate,
    AiAssistRequest,
    CallCommentIn,
    CallLinkDealIn,
    CallResultIn,
    ContactCreate,
    ContractTemplateCreate,
    DealCreate,
    DealItemUpdate,
    DealUpdate,
    DocumentCreate,
    DocumentDecision,
    LoseRequest,
    MessageCreate,
    ObjectionReplyIn,
    PlanDecisionIn,
    PlanItemIn,
    PlanReopenIn,
    PlanTargetIn,
    PriceQuoteCreate,
    PlanTargetIn,
    TaskUpdate,
)


class Result:
    def __init__(self, rows=(), scalar=None, one=None):
        self.rows = list(rows)
        self.scalar_value = scalar
        self.one_value = one

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar(self):
        return self.scalar_value

    def scalar_one(self):
        return self.scalar_value

    def scalar_one_or_none(self):
        return self.scalar_value

    def one(self):
        return self.one_value if self.one_value is not None else self.rows[0]


class Session:
    def __init__(self, *results, objects=None):
        self.results = list(results)
        self.objects = objects or {}
        self.added = []
        self.added_many = []
        self.deleted = []
        self.commits = 0
        self.rollbacks = 0
        self.refreshed = []
        self._next_id = 1

    async def execute(self, _statement):
        result = self.results.pop(0) if self.results else Result()
        if isinstance(result, Exception):
            raise result
        return result

    async def get(self, model, identity):
        return self.objects.get((model, identity), self.objects.get(identity))

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = self._next_id
            self._next_id += 1
        if isinstance(value, PlanTarget) and value.status is None:
            value.status = "draft"
        if isinstance(value, DealDocument):
            if value.status is None:
                value.status = "draft"
            if value.reserve_status is None:
                value.reserve_status = "none"
        if isinstance(value, Message) and value.created_at is None:
            value.created_at = datetime(2026, 9, 17, 12, 0)
        self.added.append(value)

    def add_all(self, values):
        for value in values:
            self.add(value)
            self.added_many.append(value)

    async def flush(self):
        for value in [*self.added, *self.added_many]:
            if getattr(value, "id", None) is None:
                value.id = self._next_id
                self._next_id += 1

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def refresh(self, value):
        self.refreshed.append(value)

    async def delete(self, value):
        self.deleted.append(value)


class Bus:
    def __init__(self):
        self.events = []

    def emit(self, session, event_type, payload):
        self.events.append((session, event_type, payload))


def _deal(**overrides):
    values = {
        "id": 11,
        "number": "D-11",
        "title": "Battery supply",
        "counterparty": "ACME",
        "amount": Decimal("100"),
        "priority": "Средний",
        "stage": "new",
        "owner": "Manager",
        "next_step": None,
        "next_step_at": None,
        "deal_date": None,
        "closed_date": None,
        "focus": False,
        "starred": False,
        "probability": 40,
        "expected_close_date": None,
        "created_at": datetime(2026, 9, 10, 10, 0),
        "stage_changed_at": datetime(2026, 9, 16, 10, 0),
        "lost_reason_code": None,
        "lost_comment": None,
        "funnel": "new_clients",
        "ship_deadline": None,
        "penalty_rate_pct": None,
        "penalty_cap_pct": None,
        "penalty_terms": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _core(*, bus=None, **service_overrides):
    services = {
        "landed_cost": None,
        "price_cost": None,
        "onec": None,
        "stock": None,
        "registry": None,
        "llm": SimpleNamespace(enabled=False, model=""),
        "approvals": SimpleNamespace(request=AsyncMock(), decide=AsyncMock()),
    }
    services.update(service_overrides)
    return SimpleNamespace(
        services=SimpleNamespace(**services),
        event_bus=bus or Bus(),
        config=SimpleNamespace(
            seller_name="Seller",
            seller_unp="111",
            seller_address="Minsk",
            seller_director="Boss",
            seller_phone="+375",
            seller_email="seller@example.com",
            seller_account="BY00",
            seller_bank="Bank",
            seller_bik="BIC",
        ),
    )


def _stage_rows():
    return [
        SimpleNamespace(id=1, code="new", title="Новая", color="#1", probability=20, kind="normal", is_active=True, funnel="new_clients", sort_order=1),
        SimpleNamespace(id=2, code="won", title="Успех", color="#2", probability=100, kind="won", is_active=True, funnel="new_clients", sort_order=2),
    ]


@pytest.mark.asyncio
async def test_pipeline_analytics_and_stage_metrics_cover_history_and_honest_empty():
    now = datetime.now().replace(microsecond=0)
    first = _deal(id=1, amount=Decimal("100"), probability=None, stage="new", created_at=now - timedelta(days=5), stage_changed_at=now - timedelta(days=2))
    won = _deal(id=2, amount=Decimal("200"), stage="won", probability=80, created_at=now - timedelta(days=10), stage_changed_at=now - timedelta(days=1))
    event = SimpleNamespace(deal_id=2, from_stage="new", to_stage="won", changed_at=now - timedelta(days=1))
    analytics = await routes.pipeline_analytics(
        session=Session(Result(_stage_rows()), Result([first, won]), Result([event]))
    )
    assert analytics.won_count == 1
    assert analytics.forecast_weighted == 20.0
    assert analytics.stages[0].next_conv_pct == 100

    metrics = await routes.pipeline_stage_metrics(
        date_from=(now - timedelta(days=8)).date(),
        date_to=now.date(),
        session=Session(Result(_stage_rows()), Result([first, won]), Result([event])),
    )
    assert metrics.stages[0].entered_count == 1
    assert metrics.stages[0].completed_count == 1
    assert metrics.stages[0].conv_next_pct == 100


@pytest.mark.asyncio
async def test_kpis_month_merges_operational_facts_and_activity_and_creates_activity():
    targets = [
        SimpleNamespace(key="calls_all", title="Звонки", target=10, unit="count", icon="phone", tone="blue", sort_order=1),
        SimpleNamespace(key="gross_profit", title="Прибыль", target=100, unit="money", icon="ruble", tone="green", sort_order=2),
    ]
    monkey = AsyncMock(return_value={"calls_all": 4.0, "gross_profit": 0.0, "won_count": 2.0})
    original = routes.compute_operational_kpi_facts
    routes.compute_operational_kpi_facts = monkey
    try:
        out = await routes.kpis(
            period="2026-09",
            session=Session(Result(targets), Result([("calls_all", Decimal("99"))])),
        )
    finally:
        routes.compute_operational_kpi_facts = original
    calls = next(row for row in out if row.key == "calls_all")
    assert (calls.actual, calls.target, calls.percent) == (4.0, 220.0, 2)
    assert any(row.key == "new_deals_count" for row in out)

    session = Session(Result(scalar=date(2026, 9, 17)))
    result = await routes.create_activity(
        ActivityCreate(kpi_key="calls", value=2.5, owner="Manager"), session
    )
    assert result == {"ok": True, "date": "2026-09-17"}
    assert session.added[0].value == Decimal("2.5")


@pytest.mark.asyncio
async def test_get_deal_builds_items_prices_documents_and_missing_counterparty_ref():
    deal = _deal()
    item = SimpleNamespace(id=4, deal_id=11, sku_id=5, qty=Decimal("2"))
    sku = SimpleNamespace(id=5, code="BAT", title="Battery", unit="шт")
    quote = SimpleNamespace(sku_code="BAT", price=Decimal("19"))
    doc = SimpleNamespace(id=8, kind="invoice", number="INV-8", status="posted", onec_ref="1C-8", amount=Decimal("38"), valid_until=None, reserve_status="none")
    session = Session(Result([item]), Result([sku]), Result([quote]), Result([doc]), objects={(routes.Deal, 11): deal})
    result = await routes.get_deal(11, session)
    assert result.items[0].model_dump() == {
        "id": 4,
        "sku_id": 5,
        "code": "BAT",
        "title": "Battery",
        "unit": "шт",
        "qty": 2.0,
        "last_price": 19.0,
        "min_price": 19.0,
    }
    assert result.documents[0].number == "INV-8"
    assert result.counterparty_ref is None


@pytest.mark.asyncio
async def test_update_deal_validates_stage_and_emits_ship_deadline(monkeypatch):
    deal = _deal(closed_date="01.09.2026", stage="new", ship_deadline=None)
    bus = Bus()
    items = [SimpleNamespace(sku_id=5, qty=Decimal("2"))]
    sku = SimpleNamespace(id=5, code="BAT", title="Battery")
    session = Session(
        Result([("new", "normal"), ("qual", "normal")]),
        Result(items),
        Result([sku]),
        objects={(routes.Deal, 11): deal},
    )
    user = SimpleNamespace(username="manager")
    await routes.update_deal(
        11,
        DealUpdate(stage="qual", ship_deadline="25.09.2026", penalty_rate_pct=1.5),
        _core(bus=bus),
        session,
        user,
    )
    assert deal.stage == "qual"
    assert deal.closed_date is None
    assert any(event[1] == "sales.deal.ship_deadline.set" for event in bus.events)
    assert any(isinstance(value, DealStageEvent) for value in session.added)

    with pytest.raises(HTTPException) as invalid:
        await routes.update_deal(
            11,
            DealUpdate(stage="missing"),
            _core(),
            Session(Result([("new", "normal"), ("won", "won")]), objects={(routes.Deal, 11): deal}),
            user,
        )
    assert invalid.value.status_code == 422


@pytest.mark.asyncio
async def test_margin_uses_quote_price_and_price_cost_before_landed(monkeypatch):
    deal = _deal()
    item = SimpleNamespace(sku_id=5, qty=Decimal("2"))
    sku = SimpleNamespace(id=5, code="BAT", title="Battery")
    quote = SimpleNamespace(sku_code="BAT", price=Decimal("100"))
    pc = SimpleNamespace(
        get_item_price_cost=AsyncMock(
            return_value={"BAT": ItemPriceCost(cost_byn=30, price_byn=60, source="demo")}
        )
    )
    landed = SimpleNamespace(last_landed_cost_batch=AsyncMock(return_value={"BAT": {"unit_landed_cost_byn": "35", "shipment_id": "PO-1", "fixed_at": None, "fx_rate": "3"}}))
    core = _core(landed_cost=landed, price_cost=pc)
    session = Session(Result([item]), Result([sku]), Result([quote]))
    lines, missing = await routes._deal_margin(session, core, deal)
    assert missing is False
    assert lines[0].status == "priced"
    assert (lines[0].unit_price, lines[0].unit_landed_cost, lines[0].price_source, lines[0].cost_source) == (100.0, 30, "quote", "demo")

    empty = await routes.deal_margin(11, _core(), Session(Result([]), objects={(routes.Deal, 11): deal}))
    assert (empty.total_count, empty.reason) == (0, "Позиций нет — маржа не рассчитывается")


@pytest.mark.asyncio
async def test_margin_forecast_and_reconcile_report_honest_missing_fact(monkeypatch):
    active = _deal(id=1, amount=Decimal("100"), stage="new", probability=50)
    priced = routes.MarginLine(
        sku_code="BAT", title="Battery", qty=2, unit_price=100, revenue=200,
        unit_landed_cost=30, cogs=60, margin_pct=70, status="priced",
    )
    monkeypatch.setattr(routes, "_deal_margin", AsyncMock(return_value=([priced], False)))
    forecast = await routes.pipeline_margin_forecast(
        session=Session(Result(_stage_rows()), Result([active])),
        core=_core(landed_cost=SimpleNamespace()),
    )
    assert (forecast.revenue_weighted, forecast.gross_weighted, forecast.deals_priced) == (100.0, 70.0, 1)

    monkeypatch.setattr(routes, "_audit_landed_unit_by_sku", AsyncMock(return_value={}))
    reconcile = await routes.deal_margin_reconcile(
        1,
        _core(landed_cost=SimpleNamespace()),
        Session(objects={(routes.Deal, 1): active}),
    )
    assert reconcile.status == "no_finance"


@pytest.mark.asyncio
async def test_journal_and_handoff_resolve_payment_shipping_and_latest_event(monkeypatch):
    d = _deal(id=3, stage="won", closed_date="17.09.2026", funnel="new_clients")
    invoice = SimpleNamespace(deal_id=3, kind="invoice", status="paid", number="INV-3")
    shipment = SimpleNamespace(payload={"deal_id": 3})
    line = routes.MarginLine(sku_code="BAT", title="Battery", qty=1, unit_price=100, revenue=100, unit_landed_cost=40, cogs=40, status="priced")
    monkeypatch.setattr(routes, "_won_pairs", AsyncMock(return_value={("new_clients", "won")}))
    monkeypatch.setattr(routes, "_deal_margin", AsyncMock(return_value=([line], False)))
    journal = await routes.sales_journal(
        core=_core(landed_cost=SimpleNamespace()),
        session=Session(Result([d]), Result([invoice]), Result([shipment])),
    )
    assert journal[0].payment == "paid" and journal[0].shipment == "delivered"

    event = SimpleNamespace(
        payload={"deal_id": 3, "number": "D-3", "counterparty": "ACME", "amount": 100, "owner": "M", "funnel": "new_clients", "items": [{"sku_code": "BAT", "title": "Battery", "qty": 1}], "gross_profit": 60},
        created_at=datetime(2026, 9, 17, 12, 0),
    )
    handoff = await routes.deal_handoff(3, Session(Result([event])))
    assert handoff.number == "D-3" and handoff.items[0].sku_code == "BAT"
    assert await routes.deal_handoff(404, Session(Result([]))) is None


@pytest.mark.asyncio
async def test_plan_items_and_plan_workflow_cover_replace_upsert_and_approval_events():
    item_payload = PlanItemIn(
        source="committed", ref="deal:11", title="Battery", when_label="закрытие",
        revenue=100, gross=30, probability=70,
    )
    item_session = Session(Result())
    items = await routes.put_plan_items(7, "2026-09", [item_payload], item_session)
    assert items[0].owner_id == 7 and items[0].revenue == 100.0
    assert item_session.commits == 1 and item_session.refreshed == item_session.added

    plan = PlanTarget(
        id=5,
        owner_id=7,
        metric="gross_profit",
        period_type="month",
        period_key="2026-09",
        target=Decimal("1000"),
        status="draft",
        approved_by=None,
        approved_at=None,
        rop_comment=None,
    )
    created = await routes.upsert_plan(
        PlanTargetIn(owner_id=7, metric="calls", period_type="month", period_key="2026-09", target=10),
        Session(Result()),
    )
    assert created.status == "draft"

    rejected = SimpleNamespace(
        id=6, owner_id=7, metric="calls", period_type="month", period_key="2026-09",
        target=Decimal("5"), status="rejected", approved_by="rop", approved_at=datetime.now(), rop_comment="old",
    )
    updated = await routes.upsert_plan(
        PlanTargetIn(owner_id=7, metric="calls", period_type="month", period_key="2026-09", target=12),
        Session(Result([rejected])),
    )
    assert (updated.target, updated.status, updated.approved_by) == (12.0, "draft", None)

    approved = SimpleNamespace(
        id=8, owner_id=7, metric="calls", period_type="month", period_key="2026-09",
        target=Decimal("12"), status="approved",
    )
    with pytest.raises(HTTPException) as locked:
        await routes.upsert_plan(
            PlanTargetIn(owner_id=7, metric="calls", period_type="month", period_key="2026-09", target=13),
            Session(Result([approved])),
        )
    assert locked.value.status_code == 409

    approvals = SimpleNamespace(request=AsyncMock(), decide=AsyncMock())
    core = _core(approvals=approvals)
    user = SimpleNamespace(username="rop")
    pending = SimpleNamespace(
        id=5, owner_id=7, metric="gross_profit", period_type="month", period_key="2026-09",
        target=Decimal("1000"), status="draft", approved_by=None, approved_at=None, rop_comment=None,
    )
    submitted = await routes.submit_plan(5, core, Session(objects={(PlanTarget, 5): pending}), user)
    assert submitted.status == "pending_approval"
    approvals.request.assert_awaited_once()

    bus = Bus()
    pending.status = "pending_approval"
    decided = await routes.decide_plan(
        5,
        PlanDecisionIn(approved=True, comment="OK"),
        _core(bus=bus, approvals=approvals),
        Session(objects={(PlanTarget, 5): pending}),
        user,
    )
    assert decided.status == "approved" and bus.events[0][1] == "sales.plan.approved"

    reopened = await routes.reopen_plan(
        5,
        PlanReopenIn(reason="Нужен пересмотр"),
        _core(bus=bus, approvals=approvals),
        Session(objects={(PlanTarget, 5): pending}),
        user,
    )
    assert reopened.status == "draft" and bus.events[-1][1] == "sales.plan.reopened"


@pytest.mark.asyncio
async def test_plan_sources_combine_committed_regulars_history_and_saved_snapshot(monkeypatch):
    open_deal = _deal(
        id=1,
        title="Open battery",
        stage="new",
        owner="Manager",
        expected_close_date="20.09.2026",
        probability=None,
    )
    won_one = _deal(
        id=2,
        stage="won",
        owner="Manager",
        counterparty="ACME",
        closed_date="01.09.2026",
    )
    won_two = _deal(
        id=3,
        stage="won",
        owner="Manager",
        counterparty="ACME",
        closed_date="10.09.2026",
    )
    line = routes.MarginLine(
        sku_code="BAT", title="Battery", qty=1, unit_price=100, revenue=100,
        unit_landed_cost=50, cogs=50, margin_pct=50, status="priced",
    )
    saved = PlanItem(
        id=20, owner_id=7, period_key="2026-09", source="committed", ref="deal:1",
        title="Saved", when_label="", revenue=100, gross=50, probability=50, enabled=True,
    )
    plan = SimpleNamespace(target=Decimal("200"))
    monkeypatch.setattr(routes, "_won_pairs", AsyncMock(return_value={("new_clients", "won")}))
    monkeypatch.setattr(routes, "_stage_kind_map", AsyncMock(return_value={"new": "normal", "won": "won"}))
    monkeypatch.setattr(routes, "_deal_margin", AsyncMock(return_value=([line], False)))
    monkeypatch.setattr(
        routes,
        "_board_stages",
        AsyncMock(return_value=[{"id": "new", "title": "Новая", "color": "#1", "probability": 30}]),
    )
    result = await routes.plan_sources(
        month="2026-09",
        owner="Manager",
        owner_id=7,
        core=_core(landed_cost=SimpleNamespace()),
        session=Session(
            Result([open_deal, won_one, won_two]),
            Result([1]),
            Result([plan]),
            Result([saved]),
        ),
    )
    assert result.committed[0].when_label.startswith("🔒 резерв")
    assert result.regulars[0].cycle_days == 9
    assert result.regulars[0].in_month is True
    assert result.defaults.margin_pct_source == "history"
    assert result.base_gross == 200.0 and result.saved_items[0].id == 20


@pytest.mark.asyncio
async def test_win_lose_create_and_approval_routes_publish_domain_events():
    bus = Bus()
    deal = _deal(stage="new")
    user = SimpleNamespace(username="manager")
    lost_session = Session(
        Result([("new", "normal"), ("lost", "lost")]),
        Result(["price"]),
        objects={(routes.Deal, 11): deal},
    )
    lost = await routes.lose_deal(
        11,
        LoseRequest(reason_code="price", comment="дорого"),
        _core(bus=bus),
        lost_session,
        user,
    )
    assert lost.stage == "lost" and lost.lost_reason_code == "price"
    assert bus.events[-1][1] == "sales.deal.lost"

    won = _deal(stage="new")
    won_session = Session(Result([("new", "normal"), ("won", "won")]), objects={(routes.Deal, 11): won})
    await routes.win_deal(11, _core(bus=bus), won_session, user)
    assert won.stage == "won" and bus.events[-1][1] == "sales.deal.won"

    with pytest.raises(HTTPException) as no_reason:
        await routes.lose_deal(
            11,
            LoseRequest(reason_code=""),
            _core(),
            Session(Result([("new", "normal"), ("lost", "lost")]), objects={(routes.Deal, 11): _deal()}),
            user,
        )
    assert no_reason.value.status_code == 422

    approval = SimpleNamespace(id=4, status="pending")
    approval_service = SimpleNamespace(request=AsyncMock(return_value=SimpleNamespace(id=9, status="pending")))
    requested = await routes.request_approval(
        11,
        routes.ApprovalRequest(kind="deal.contract", requested_by="manager"),
        _core(approvals=approval_service),
        Session(objects={(routes.Deal, 11): deal}),
    )
    assert requested.id == 9


@pytest.mark.asyncio
async def test_deal_items_contacts_chats_and_repeated_order_paths():
    deal = _deal()
    item = SimpleNamespace(id=9, deal_id=4, sku_id=5, qty=Decimal("3"))
    sku = SimpleNamespace(id=5, code="BAT", title="Battery", unit="шт")
    updated = await routes.update_deal_item(
        9,
        routes.DealItemUpdate(qty=4),
        Session(objects={(routes.DealItem, 9): item, (routes.Deal, 4): deal}),
    )
    assert updated.qty == 4.0 and item.qty == Decimal("4")
    delete_session = Session(objects={(routes.DealItem, 9): item})
    await routes.delete_deal_item(9, delete_session)
    assert delete_session.deleted == [item]

    repeat = await routes.repeat_last_order(
        11,
        Session(
            Result(scalar=4),
            Result([item]),
            Result(["12"]),
            objects={(routes.Deal, 11): deal, (routes.Sku, 5): sku},
        ),
    )
    assert repeat[0].code == "BAT"
    contacts = [SimpleNamespace(id=1, full_name="Иван", phone="+375", email=None, is_primary=True)]
    cp = SimpleNamespace(id=7, name="ACME", unp="", is_active=True, merged_into_id=None)
    contact_result = await routes.list_contacts(
        11,
        Session(Result([cp]), Result(contacts), objects={(routes.Deal, 11): deal}),
    )
    assert contact_result[0].full_name == "Иван"

    old = SimpleNamespace(id=3, deal_id=11, text="старое", channel="telegram", direction="in", created_at=datetime(2026, 9, 16), read_at=None)
    latest = SimpleNamespace(id=4, deal_id=11, text="новое", channel="telegram", direction="out", created_at=datetime(2026, 9, 17), read_at=None)
    chat = await routes.list_chats(
        Session(
            Result([latest, old]),
            Result([deal]),
            Result([(11, 1, datetime(2026, 9, 16))]),
        )
    )
    assert chat[0].last_text == "новое" and chat[0].unread == 1


@pytest.mark.asyncio
async def test_document_paths_reserve_stock_and_decide_contract(monkeypatch):
    deal = _deal()
    onec = SimpleNamespace(post_document=AsyncMock(return_value={"ref": "1C-11"}))
    stock = SimpleNamespace(reserve=AsyncMock(return_value=[{"sku_code": "BAT", "qty": 2}]))
    bus = Bus()
    items = [SimpleNamespace(sku_id=5, qty=Decimal("2"))]
    sku = SimpleNamespace(id=5, code="BAT")
    session = Session(Result(items), Result([sku]), objects={(routes.Deal, 11): deal})
    doc = await routes.create_document(
        11,
        DocumentCreate(kind="invoice"),
        _core(bus=bus, onec=onec, stock=stock),
        session,
    )
    assert doc.status == "posted" and doc.reserve_status == "reserved"
    assert any(event[1] == "sales.stock.reserved" for event in bus.events)

    template = SimpleNamespace(id=4, code="basic", name="Basic", body="{{buyer.name}}")
    contract_deal = _deal()
    approvals = SimpleNamespace(request=AsyncMock())
    contract_session = Session(Result([template]), Result([]), objects={(routes.Deal, 11): contract_deal})
    prepared = await routes.prepare_contract(
        11,
        routes.ContractPrepareIn(template_code="basic", unp="123", requested_by="manager"),
        _core(approvals=approvals, registry=None),
        contract_session,
    )
    assert prepared.status == "pending_approval"

    pending_doc = DealDocument(
        id=12, deal_id=11, kind="contract", number="ДГ-D-11", amount=Decimal("100"), status="pending_approval"
    )
    approval = SimpleNamespace(id=3, status="pending")
    decide_session = Session(Result([approval]), objects={(DealDocument, 12): pending_doc, (routes.Deal, 11): deal})
    rejected = await routes.decide_document(
        12,
        DocumentDecision(approved=False, by="rop"),
        _core(bus=bus, onec=onec, approvals=SimpleNamespace(decide=AsyncMock())),
        decide_session,
    )
    assert rejected.status == "rejected"


@pytest.mark.asyncio
async def test_ai_and_call_actions_fail_closed_or_emit_when_enabled(monkeypatch):
    deal = _deal()
    with pytest.raises(HTTPException) as disabled:
        await routes.ai_draft_reply(11, _core(), Session(objects={(routes.Deal, 11): deal}))
    assert disabled.value.status_code == 503

    llm = SimpleNamespace(enabled=True, model="mock", draft_reply=AsyncMock())
    monkeypatch.setattr(routes, "draft_reply", AsyncMock(return_value="Готовый ответ"))
    bus = Bus()
    ai = await routes.ai_draft_reply(
        11,
        _core(bus=bus, llm=llm),
        Session(Result([]), objects={(routes.Deal, 11): deal}),
    )
    assert ai.text == "Готовый ответ" and bus.events[0][1] == "ai.draft.generated"

    call = SimpleNamespace(id=8, deal_id=11, comment=None, result=None, owner="Manager")
    from modules.sales.models import CallLog

    comment = await routes.call_comment(8, CallCommentIn(comment="важно"), Session(objects={(CallLog, 8): call}))
    result = await routes.call_result(8, CallResultIn(result="перезвонить"), Session(objects={(CallLog, 8): call}))
    assert (comment.comment, result.result) == ("важно", "перезвонить")


@pytest.mark.asyncio
async def test_ai_assist_and_call_copilot_emit_auditable_hints(monkeypatch):
    from modules.sales.models import CallLog

    deal = _deal()
    monkeypatch.setattr(routes, "summarize", AsyncMock(return_value="summary"))
    monkeypatch.setattr(routes, "next_step", AsyncMock(return_value="next"))
    bus = Bus()
    llm = SimpleNamespace(enabled=True, model="copilot")
    assist = await routes.ai_assist(
        11,
        AiAssistRequest(kind="next_step"),
        _core(bus=bus, llm=llm),
        Session(Result(scalar=2), Result(scalar=1), Result(scalar=3), objects={(routes.Deal, 11): deal}),
    )
    assert (assist.kind, assist.text, bus.events[0][1]) == ("next_step", "next", "ai.next_step.generated")

    call = SimpleNamespace(id=4, deal_id=11)
    monkeypatch.setattr(routes, "call_script_hint", AsyncMock(return_value="hint"))
    script = await routes.call_ai_script(
        4,
        _core(bus=bus, llm=llm),
        Session(objects={(CallLog, 4): call, (routes.Deal, 11): deal}),
    )
    assert (script.stage, script.ai_hint, script.model) == ("new", "hint", "copilot")

    monkeypatch.setattr(routes, "objection_hint", AsyncMock(return_value="respond this way"))
    objection = await routes.call_ai_objection(
        4,
        ObjectionReplyIn(objection="Слишком дорого"),
        _core(bus=bus, llm=llm),
        Session(objects={(CallLog, 4): call, (routes.Deal, 11): deal}),
    )
    assert objection.category == "price" and objection.ai_hint == "respond this way"


@pytest.mark.asyncio
async def test_calls_stream_list_get_and_create_link_paths():
    from modules.sales.models import CallLog

    call = SimpleNamespace(
        id=8, call_id="c-8", direction="in", phone_e164="+375291234567", did=None,
        agent_ext=None, owner="Manager", counterparty_id=None, contact_id=None, deal_id=None,
        status="ringing", result=None, comment=None, recording_url=None,
        started_at=datetime(2026, 9, 17, 12, 0), answered_at=None, ended_at=None,
        duration_sec=None, hold_sec=None,
    )
    listed = await routes.list_calls(session=Session(Result([call])))
    assert listed == [call]
    assert await routes.get_call(8, Session(objects={(CallLog, 8): call})) is call

    created = await routes.call_link_deal(
        8,
        CallLinkDealIn(create=True),
        Session(objects={(CallLog, 8): call}),
        _core(),
    )
    assert created.deal_id is not None

    with pytest.raises(HTTPException) as invalid:
        await routes.call_link_deal(8, CallLinkDealIn(), Session(objects={(CallLog, 8): call}), _core())
    assert invalid.value.status_code == 400

    response = await routes.calls_stream(user=SimpleNamespace(username="Manager"))
    assert response.media_type == "text/event-stream"


@pytest.mark.asyncio
async def test_stage_seed_delete_skus_messages_and_prices_cover_crud_boundaries():
    seeded = await routes.list_stages(
        funnel="new_clients",
        session=Session(Result([]), Result([SimpleNamespace(code="new", funnel="new_clients")])),
    )
    assert seeded[0].code == "new"

    stage = SimpleNamespace(code="qual")
    delete_session = Session(Result([stage]), Result(scalar=0))
    assert await routes.delete_stage("qual", delete_session) is None
    assert delete_session.deleted == [stage] and delete_session.commits == 1

    skus = [SimpleNamespace(id=1, code="A", title="А", unit="шт")]
    assert await routes.list_skus(for_picker=True, session=Session(Result(skus))) == skus
    reason = SimpleNamespace(code="price", title="Цена")
    assert await routes.loss_reasons(Session(Result([reason]))) == [reason]

    incoming = SimpleNamespace(id=1, deal_id=11, channel="telegram", direction="in", author="Client", text="Hi", created_at=datetime(2026, 9, 17, 10, 0), read_at=None)
    listed = await routes.list_messages(11, Session(Result([incoming])))
    assert listed == [incoming]
    marked = await routes.mark_messages_read(11, Session(Result([incoming]), objects={(routes.Deal, 11): _deal()}))
    assert marked["read"] == 1 and incoming.read_at is not None

    bus = Bus()
    quote = await routes.create_price_quote(
        PriceQuoteCreate(sku_code="A", counterparty="ACME", price=12.5),
        _core(bus=bus),
        Session(),
    )
    assert quote == {"ok": True} and bus.events[0][1] == "sales.price.quoted"


@pytest.mark.asyncio
async def test_render_package_send_and_branding_use_same_document_selection(monkeypatch):
    invoice = SimpleNamespace(id=2, deal_id=11, kind="invoice", number="INV-11", status="posted", amount=Decimal("100"), valid_until=None, reserve_status="none")
    contract = SimpleNamespace(id=3, deal_id=11, kind="contract", number="ДГ-11", status="paid", amount=Decimal("100"), valid_until=None, reserve_status="none")
    deal = _deal()
    assert await routes._package_docs(Session(Result([contract, invoice])), 11) == (invoice, contract)

    monkeypatch.setattr(routes, "_invoice_html", AsyncMock(return_value="INVOICE"))
    monkeypatch.setattr(routes, "_contract_html", AsyncMock(return_value="CONTRACT"))
    branding = CompanyBranding(id=1, logo_data_url=None, stamp_data_url=None, signature_data_url=None)
    core = _core()
    rendered = await routes.render_package(
        11,
        core,
        Session(Result([contract, invoice]), objects={(routes.Deal, 11): deal, (CompanyBranding, 1): branding}),
    )
    assert "INVOICE" in rendered.body.decode() and "CONTRACT" in rendered.body.decode()

    sent_bus = Bus()
    sent_session = Session(Result([contract, invoice]), objects={(routes.Deal, 11): deal})
    sent = await routes.send_package(11, _core(bus=sent_bus), sent_session)
    assert sent.invoice_number == "INV-11" and sent_session.commits == 1
    assert sent_bus.events[0][1] == "sales.package.sent"

    invoice_doc = SimpleNamespace(id=4, deal_id=11, kind="invoice", number="INV-4", amount=Decimal("10"), status="posted")
    monkeypatch.setattr(routes, "_invoice_html", AsyncMock(return_value="ONLY-INVOICE"))
    rendered_one = await routes.render_document(
        4,
        core,
        Session(objects={(routes.DealDocument, 4): invoice_doc, (CompanyBranding, 1): branding}),
    )
    assert rendered_one.body == b"ONLY-INVOICE"

    with pytest.raises(HTTPException) as wrong_kind:
        await routes.render_document(
            5,
            core,
            Session(objects={(routes.DealDocument, 5): SimpleNamespace(kind="order")}),
        )
    assert wrong_kind.value.status_code == 400


@pytest.mark.asyncio
async def test_rop_plan_fact_and_telephony_incoming_keep_contracts_explicit(monkeypatch):
    target = SimpleNamespace(target=Decimal("500"))
    result = await routes.rop_plan_fact(
        period="2026-09",
        session=Session(Result([("Manager", 2, Decimal("1000"))]), Result([target])),
    )
    assert result["period"] == "2026-09" and result["managers"][0]["fact_deals"] == 2

    from modules.sales import calls as calls_mod

    handler = AsyncMock()
    monkeypatch.setitem(calls_mod.EVENT_HANDLERS, "telephony.call.incoming", handler)
    incoming = routes.TelephonyEventIn(
        event_type="telephony.call.incoming", call_id="c-1", phone_e164="+375291234567"
    )
    telephony = await routes.telephony_incoming(incoming, Session(), _core())
    assert telephony == {"ok": True, "event_type": "telephony.call.incoming", "call_id": "c-1"}
    handler.assert_awaited_once()



@pytest.mark.asyncio
async def test_calls_link_deal_and_invalid_filters_are_explicit():
    from modules.sales.models import CallLog

    call = SimpleNamespace(id=8, call_id="c-8", deal_id=None, phone_e164="+375", owner="Manager", counterparty_id=None)
    target = _deal(id=15)
    linked = await routes.call_link_deal(
        8,
        CallLinkDealIn(deal_id=15),
        Session(objects={(CallLog, 8): call, (routes.Deal, 15): target}),
        _core(),
    )
    assert linked.deal_id == 15
    with pytest.raises(HTTPException) as bad:
        await routes.list_calls(date="not-a-date", session=Session())
    assert bad.value.status_code == 400
