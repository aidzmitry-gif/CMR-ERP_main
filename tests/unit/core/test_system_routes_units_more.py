from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from core.runtime import system_routes
from core.services import sku_history


class Result:
    def __init__(self, rows=(), scalar=None):
        self.rows = list(rows)
        self.scalar_value = scalar

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar(self):
        return self.scalar_value


class Session:
    def __init__(self, *results, gets=None):
        self.results = list(results)
        self.gets = gets or {}
        self.commits = 0

    async def execute(self, _statement):
        return self.results.pop(0) if self.results else Result()

    async def get(self, model, identity):
        return self.gets.get((model, identity), self.gets.get(identity))

    async def commit(self):
        self.commits += 1


class Bus:
    def __init__(self):
        self.events = []

    def emit(self, session, event_type, payload):
        self.events.append((event_type, payload))


def request(core):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(core=core)))


def core(*, services=None, references=()):
    default = SimpleNamespace(
        onec=None,
        touch_history=None,
        landed_cost=None,
        stock=None,
        llm=SimpleNamespace(enabled=False, model=None),
    )
    if services:
        for key, value in services.__dict__.items():
            setattr(default, key, value)
    return SimpleNamespace(
        services=default,
        loaded_modules=["sales"],
        routers=[],
        events=[],
        workflows=[],
        permissions=[],
        roles=[],
        telegram_commands=[],
        widgets=[],
        references=list(references),
        event_bus=Bus(),
    )


@pytest.mark.asyncio
async def test_system_users_are_dev_only(monkeypatch):
    monkeypatch.setattr(system_routes, "get_settings", lambda: SimpleNamespace(environment="dev"))
    monkeypatch.setattr(system_routes, "users_with_titles", lambda: [{"username": "demo"}])
    assert await system_routes.system_users() == {"users": [{"username": "demo"}]}

    monkeypatch.setattr(system_routes, "get_settings", lambda: SimpleNamespace(environment="prod"))
    with pytest.raises(HTTPException) as error:
        await system_routes.system_users()
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_system_modules_and_reference_catalog_project_registered_metadata():
    column = SimpleNamespace(name="code", type="string", semantic="key", __dict__={})
    reference = SimpleNamespace(
        key="core.skus",
        title="SKU",
        endpoint="/skus",
        owner_schema="core",
        department="Продажи",
        columns=[column],
        permissions=["refs.view"],
        archivable=True,
        versioned=False,
        ai_exposed=True,
        description="каталог",
    )
    registration = SimpleNamespace(module="core", reference=reference)
    app_core = core(references=[registration])
    app_core.routers = [SimpleNamespace(module="sales", prefix="/sales")]
    app_core.events = [SimpleNamespace(module="sales", event_type="sales.deal.won")]
    app_core.workflows = [SimpleNamespace(module="sales", name="quote")]
    app_core.permissions = [SimpleNamespace(code="sales.deal.read")]
    app_core.roles = [SimpleNamespace(name="director", permissions=("sales.deal.read",))]
    app_core.telegram_commands = [SimpleNamespace(command="status")]
    app_core.widgets = [SimpleNamespace(key="sales.kpi", title="Продажи")]
    req = request(app_core)

    modules = await system_routes.system_modules(req)
    assert modules["loaded_modules"] == ["sales"]
    assert modules["routers"] == [{"module": "sales", "prefix": "/sales"}]
    assert modules["permissions"] == ["sales.deal.read"]

    refs = await system_routes.system_references(req)
    assert refs["departments"]["Продажи"][0]["key"] == "core.skus"
    catalog = await system_routes.system_references_ai_catalog(req)
    assert catalog["references"][0]["columns"] == [
        {"name": "code", "type": "string", "semantic": "key"}
    ]


@pytest.mark.asyncio
async def test_references_query_validates_payload_clamps_limit_and_maps_service_error(monkeypatch):
    calls = []

    async def query(*args, **kwargs):
        calls.append((args, kwargs))
        return {"rows": []}

    monkeypatch.setattr(system_routes.reference_query, "query", query)
    result = await system_routes.references_query(
        {"ref": "core.skus", "as_of": "2026-09-17", "category_id": "7", "limit": 999, "resolve": True},
        Session(),
        None,
    )
    assert result == {"rows": []}
    assert calls[0][1]["as_of"] == date(2026, 9, 17)
    assert calls[0][1]["category_id"] == 7 and calls[0][1]["limit"] == 250

    for payload, fragment in [({}, "ref"), ({"ref": "x", "as_of": "bad"}, "as_of"), ({"ref": "x", "limit": "bad"}, "числа")]:
        with pytest.raises(HTTPException, match=fragment):
            await system_routes.references_query(payload, Session(), None)

    async def invalid(*args, **kwargs):
        raise system_routes.reference_query.ReferenceQueryError("неизвестный справочник")

    monkeypatch.setattr(system_routes.reference_query, "query", invalid)
    with pytest.raises(HTTPException, match="неизвестный"):
        await system_routes.references_query({"ref": "bad"}, Session(), None)


@pytest.mark.asyncio
async def test_quality_mdm_and_tnved_wrappers_preserve_service_contracts(monkeypatch):
    monkeypatch.setattr(system_routes.reference_quality, "audit_reference", AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as missing:
        await system_routes.reference_quality_detail("missing", Session(), None)
    assert missing.value.status_code == 404

    expected = {"ref": "core.skus", "issues": []}
    monkeypatch.setattr(system_routes.reference_quality, "audit_reference", AsyncMock(return_value=expected))
    assert await system_routes.reference_quality_detail("core.skus", Session(), None) == expected

    monkeypatch.setattr(system_routes.mdm, "duplicate_clusters", AsyncMock(return_value=[[1, 2]]))
    assert await system_routes.mdm_duplicates(Session(), None) == {"clusters": [[1, 2]]}
    monkeypatch.setattr(system_routes.mdm, "survivorship_rules", AsyncMock(return_value=[{"field": "name"}]))
    assert await system_routes.mdm_rules("counterparty", Session()) == {"rules": [{"field": "name"}]}
    monkeypatch.setattr(system_routes.mdm, "fuzzy_candidates", AsyncMock(return_value=[{"id": 1}]))
    assert await system_routes.mdm_fuzzy("Альфа", 2, Session(), None) == {"candidates": [{"id": 1}]}

    monkeypatch.setattr(system_routes.tnved, "resolve", AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as absent:
        await system_routes.tnved_lookup("8507", date(2026, 9, 17), Session())
    assert absent.value.status_code == 404
    monkeypatch.setattr(system_routes.tnved, "resolve", AsyncMock(return_value={"duty_rate": 5}))
    assert await system_routes.tnved_lookup("8507", date(2026, 9, 17), Session()) == {"duty_rate": 5}


@pytest.mark.asyncio
async def test_mdm_merge_and_unmerge_commit_and_translate_bad_payload(monkeypatch):
    survivor = SimpleNamespace(id=1, name="Альфа", unp="123")
    duplicate = SimpleNamespace(id=2, is_active=True)
    monkeypatch.setattr(system_routes.mdm, "merge", AsyncMock(return_value=survivor))
    app_core = core()
    session = Session()
    user = SimpleNamespace(username="admin")
    assert await system_routes.mdm_merge(request(app_core), {"survivor_id": "1", "duplicate_id": "2"}, session, user) == {
        "id": 1, "name": "Альфа", "unp": "123"
    }
    assert session.commits == 1

    monkeypatch.setattr(system_routes.mdm, "unmerge", AsyncMock(return_value=duplicate))
    assert await system_routes.mdm_unmerge(request(app_core), {"duplicate_id": 2}, session, user) == {
        "id": 2, "is_active": True
    }

    async def bad(*args, **kwargs):
        raise ValueError("сломано")

    monkeypatch.setattr(system_routes.mdm, "merge", bad)
    with pytest.raises(HTTPException) as error:
        await system_routes.mdm_merge(request(app_core), {"survivor_id": "x", "duplicate_id": 2}, session, user)
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_system_event_and_audit_projections_are_stable():
    events = [SimpleNamespace(id=2, event_type="x", version=3, created_at="now", processed_at=None)]
    audit = [SimpleNamespace(id=1, ts="today", actor="admin", action="edit", entity_ref="sku:A")]
    session = Session(Result(events), Result(audit))
    assert await system_routes.system_events(session, None) == [
        {"id": 2, "event_type": "x", "version": 3, "created_at": "now", "processed": False}
    ]
    assert await system_routes.system_audit(session, None) == [
        {"id": 1, "ts": "today", "actor": "admin", "action": "edit", "entity_ref": "sku:A"}
    ]


@pytest.mark.asyncio
async def test_sku_helpers_build_breadcrumb_and_sync_link():
    root = SimpleNamespace(code="ROOT", name="Корень", parent_id=None)
    leaf = SimpleNamespace(code="LEAF", name="Лист", parent_id=1)
    session = Session(Result([SimpleNamespace(origin="1c", state="synced", external_ref="SKU-1", last_synced_at=None)]), gets={1: root, 2: leaf})
    assert await system_routes._group_breadcrumb(session, None) == []
    assert await system_routes._group_breadcrumb(Session(gets={2: leaf, 1: root}), 2) == [
        {"code": "ROOT", "name": "Корень"}, {"code": "LEAF", "name": "Лист"}
    ]
    assert await system_routes._sku_sync_link(session, 7) == {
        "origin": "1c", "state": "synced", "external_ref": "SKU-1", "last_synced_at": None
    }


@pytest.mark.asyncio
async def test_sku_card_gracefully_collects_landed_stock_and_history(monkeypatch):
    sku = SimpleNamespace(
        code="SKU-1", title="АКБ", unit="шт", category_id=None, weight_kg=1.2, volume_m3=0.1,
        vat_code=None, tnved_code="8507", shelf_life_days=365, is_active=True,
        attributes={}, provenance={}, id=7,
    )
    version_data = {field: getattr(sku, field, None) for field in sku_history.SNAPSHOT_FIELDS}
    version = SimpleNamespace(start_date=date(2026, 1, 1), end_date=None, **version_data)

    landed = SimpleNamespace(last_landed_cost=AsyncMock(return_value={"unit": 10}))
    stock = SimpleNamespace(
        stock_by_sku=AsyncMock(return_value={"total_available": 4}),
        batches_by_sku=AsyncMock(side_effect=RuntimeError("нет партий")),
    )
    app_core = core(services=SimpleNamespace(landed_cost=landed, stock=stock))
    session = Session(Result([sku]), Result([]), Result([version]))
    monkeypatch.setattr(system_routes.tnved, "effective_code_for_sku", AsyncMock(return_value={"code": "8507", "source": "own"}))
    monkeypatch.setattr(system_routes.tnved, "resolve", AsyncMock(return_value={"duty_rate": 5}))
    monkeypatch.setattr(system_routes.tnved, "effective_group_field", AsyncMock(side_effect=[
        {"value": "шт", "source": "own"}, {"value": "BY", "source": "own"}, {"value": None, "source": None}
    ]))
    monkeypatch.setattr(system_routes.tnved, "effective_group_attr", AsyncMock(return_value={"value": None}))

    result = await system_routes.sku_card("SKU-1", request(app_core), session, None)

    assert result["code"] == "SKU-1"
    assert result["landed_cost"] == {"unit": 10}
    assert result["stock"] == {"total_available": 4}
    assert result["batches"] is None
    assert result["history"][0]["start_date"] == date(2026, 1, 1)


@pytest.mark.asyncio
async def test_update_sku_emits_only_for_changed_master_fields(monkeypatch):
    sku = SimpleNamespace(code="SKU-1", weight_kg=1, title="АКБ")
    session = Session(Result([sku]))
    bus = Bus()
    app_core = core()
    app_core.event_bus = bus
    record = AsyncMock()
    monkeypatch.setattr(system_routes.sku_history, "record_sku_version", record)
    user = SimpleNamespace(username="admin")

    result = await system_routes.update_sku(
        "SKU-1", request(app_core), {"weight_kg": 2, "title": "АКБ"}, session, user
    )
    assert result == {"code": "SKU-1", "changed": ["weight_kg"]}
    assert sku.weight_kg == 2 and session.commits == 1
    assert bus.events[0][0] == "reference.sku.changed"

    session = Session(Result([]))
    with pytest.raises(HTTPException) as error:
        await system_routes.update_sku("missing", request(app_core), {}, session, user)
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_system_access_import_preview_and_unmerge_error_contracts(monkeypatch):
    monkeypatch.setattr(system_routes, "roles_from_request", lambda _request: ["sales"])
    access = await system_routes.system_access(SimpleNamespace())
    assert access["current_roles"] == ["sales"]
    assert len(access["roles"]) == len(system_routes.ROLE_ORDER)

    onec = object()
    app_core = core(services=SimpleNamespace(onec=onec))
    preview = {"created": 2, "matched": 3, "without_unp": 1}
    import_preview = AsyncMock(return_value=preview)
    monkeypatch.setattr(system_routes.mdm, "import_preview", import_preview)
    assert await system_routes.mdm_import_preview(request(app_core), Session(), None) == preview
    import_preview.assert_awaited_once()

    async def bad_unmerge(*args, **kwargs):
        raise TypeError("duplicate_id is required")

    monkeypatch.setattr(system_routes.mdm, "unmerge", bad_unmerge)
    with pytest.raises(HTTPException) as error:
        await system_routes.mdm_unmerge(
            request(app_core), {"duplicate_id": "bad"}, Session(), SimpleNamespace(username="admin")
        )
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_counterparty_card_and_sku_card_cover_optional_service_boundaries(monkeypatch):
    monkeypatch.setattr(system_routes.mdm, "counterparty_card", AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as missing:
        await system_routes.mdm_counterparty_card(9, request(core()), Session(), None)
    assert missing.value.status_code == 404

    card = {"id": 9, "name": "Альфа"}
    monkeypatch.setattr(system_routes.mdm, "counterparty_card", AsyncMock(return_value=card))
    result = await system_routes.mdm_counterparty_card(9, request(core()), Session(), None)
    assert result["touches"] == [] and result["touch_summary"] is None

    touch_history = SimpleNamespace(
        touches=AsyncMock(return_value=[{"kind": "call"}]),
        summary=AsyncMock(return_value={"count": 1}),
    )
    app_core = core(services=SimpleNamespace(touch_history=touch_history))
    result = await system_routes.mdm_counterparty_card(9, request(app_core), Session(), None)
    assert result["touches"] == [{"kind": "call"}]
    assert result["touch_summary"] == {"count": 1}

    failing_history = SimpleNamespace(
        touches=AsyncMock(side_effect=RuntimeError("sales unavailable")),
        summary=AsyncMock(return_value={"count": 0}),
    )
    result = await system_routes.mdm_counterparty_card(
        9, request(core(services=SimpleNamespace(touch_history=failing_history))), Session(), None
    )
    assert result["touches"] == [] and result["touch_summary"] is None

    sku = SimpleNamespace(
        code="SKU-BOUNDARY", title="АКБ", unit="шт", category_id=None, weight_kg=1.2,
        volume_m3=0.1, vat_code=None, tnved_code=None, shelf_life_days=365, is_active=True,
        attributes={}, provenance={}, id=7,
    )
    sync_link = SimpleNamespace(origin="erp", state="local", external_ref="SKU-7", last_synced_at=None)
    monkeypatch.setattr(system_routes.tnved, "effective_code_for_sku", AsyncMock(return_value={"code": None}))
    monkeypatch.setattr(
        system_routes.tnved,
        "effective_group_field",
        AsyncMock(side_effect=[
            {"value": "шт", "source": "own"},
            {"value": None, "source": None},
            {"value": "VAT20", "source": "group"},
        ]),
    )

    async def effective_attr(_session, _sku, key):
        if key == "Страна происхождения":
            return {"value": "BY", "source": "group"}
        if key == "Производитель":
            return {"value": "Acme", "source": "group"}
        return {"value": None, "source": None}

    monkeypatch.setattr(system_routes.tnved, "effective_group_attr", effective_attr)
    monkeypatch.setattr(system_routes.scd2, "version_as_of", AsyncMock(return_value=SimpleNamespace(rate=20)))
    landed = SimpleNamespace(last_landed_cost=AsyncMock(side_effect=RuntimeError("procurement unavailable")))
    stock = SimpleNamespace(
        stock_by_sku=AsyncMock(side_effect=RuntimeError("integrations unavailable")),
        batches_by_sku=AsyncMock(return_value={"rows": []}),
    )
    app_core = core(services=SimpleNamespace(landed_cost=landed, stock=stock))
    session = Session(Result([sku]), Result([sync_link]), Result([]))
    result = await system_routes.sku_card("SKU-BOUNDARY", request(app_core), session, None)
    assert result["landed_cost"] is None and result["stock"] is None
    assert result["batches"] == {"rows": []}
    assert result["effective_country"]["value"] == "BY"
    assert result["group_vat"]["rate"] == 20.0
    assert result["effective_attrs"]["Производитель"]["value"] == "Acme"

    with pytest.raises(HTTPException) as missing_sku:
        await system_routes.sku_card("MISSING", request(core()), Session(Result([])), None)
    assert missing_sku.value.status_code == 404


@pytest.mark.asyncio
async def test_sku_inputs_update_retry_and_breadcrumb_missing_node(monkeypatch):
    monkeypatch.setattr(system_routes.sku_master, "landed_inputs", AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as missing:
        await system_routes.sku_landed_inputs("MISSING", None, Session(), None)
    assert missing.value.status_code == 404

    expected = {"code": "SKU-1", "weight_kg": 1.0}
    monkeypatch.setattr(system_routes.sku_master, "landed_inputs", AsyncMock(return_value=expected))
    assert await system_routes.sku_landed_inputs("SKU-1", date(2026, 9, 17), Session(), None) == expected

    values = {field: None for field in sku_history.SNAPSHOT_FIELDS}
    values.update(code="SKU-RETRY", weight_kg=2.0)
    sku = SimpleNamespace(**values)
    current = SimpleNamespace(**{field: None for field in sku_history.SNAPSHOT_FIELDS})
    record = AsyncMock(side_effect=ValueError("same day"))
    monkeypatch.setattr(system_routes.sku_history, "record_sku_version", record)
    monkeypatch.setattr(system_routes.scd2, "current_version", AsyncMock(return_value=current))
    app_core = core()
    result = await system_routes.update_sku(
        "SKU-RETRY", request(app_core), {"weight_kg": 3.0}, Session(Result([sku])), SimpleNamespace(username="admin")
    )
    assert result == {"code": "SKU-RETRY", "changed": ["weight_kg"]}
    assert current.weight_kg == 3.0
    assert app_core.event_bus.events[0][0] == "reference.sku.changed"

    assert await system_routes._group_breadcrumb(Session(), 999) == []


@pytest.mark.asyncio
async def test_owner_dashboard_and_insight_use_counts_and_emit_audit_event(monkeypatch):
    app_core = core()
    app_core.loaded_modules = ["sales", "finance"]
    app_core.widgets = [SimpleNamespace(key="kpi", title="KPI")]
    session = Session(*(Result(scalar=value) for value in [2, 5, 7, 9, 3, 4]))
    owner = await system_routes.system_owner(request(app_core), session, None)
    assert owner["approvals_pending"] == 2
    assert owner["approvals_total"] == 5
    assert owner["modules"] == ["sales", "finance"]
    assert owner["widgets"] == [{"key": "kpi", "title": "KPI"}]

    disabled = core()
    with pytest.raises(HTTPException) as error:
        await system_routes.system_owner_insight(request(disabled), Session())
    assert error.value.status_code == 503

    llm = SimpleNamespace(enabled=True, model=None, complete=AsyncMock(return_value="Стабильный рост"))
    app_core = core(services=SimpleNamespace(llm=llm))
    session = Session(Result(scalar=1), Result(scalar=2), Result(scalar=3))
    insight = await system_routes.system_owner_insight(request(app_core), session)
    assert insight == {"text": "Стабильный рост", "model": "mock"}
    assert app_core.event_bus.events == [
        ("ai.insight.generated", {"actor": "AI", "entity_ref": "owner", "model": "mock"})
    ]
    assert session.commits == 1
