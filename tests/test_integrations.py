"""Тесты модуля Integrations (чтение из 1С)."""

from unittest.mock import AsyncMock

import pytest

from core.services.registry import RegistryError
from modules.integrations.module import IntegrationsModule
from modules.integrations.registry import RegistryClient


async def test_onec_wire_branch_import_keeps_two_branches_under_one_legal_entity(api, session, monkeypatch):
    from sqlalchemy import select

    from core.domain.models import Counterparty, CounterpartyBranch, CounterpartyBranchAlias
    from modules.integrations.client import OneCClient

    parent = '00000000-0000-0000-0000-000000000001'
    empty = '00000000-0000-0000-0000-000000000000'
    head = {'Ref_Key': parent, 'Description': 'Working head', 'НаименованиеПолное': 'Legal head',
            'ИНН': '600187521', 'ОбособленноеПодразделение': False, 'ГоловнойКонтрагент_Key': empty}
    branch = {'Description': 'First branch', 'ИНН': '600187521', 'ОбособленноеПодразделение': True,
              'ГоловнойКонтрагент_Key': parent, 'КодФилиала': '0002'}
    rows = [{**branch, 'Ref_Key': '00000000-0000-0000-0000-000000000002'}, head,
            {**branch, 'Ref_Key': '00000000-0000-0000-0000-000000000003', 'Description': 'Second branch'}]
    client = OneCClient('https://onec.test')
    monkeypatch.setattr(client, '_get_all', lambda *args, **kwargs: rows)
    gateway = api._transport.app.state.core.services.onec
    monkeypatch.setattr(gateway, 'fetch_counterparties', client.fetch_counterparties)
    for _ in range(2):
        response = await api.post('/integrations/1c/sync')
        assert response.status_code == 200, response.text
    parents = list(await session.scalars(select(Counterparty)))
    branches = list(await session.scalars(select(CounterpartyBranch)))
    aliases = list(await session.scalars(select(CounterpartyBranchAlias)))
    assert len(parents) == 1 and parents[0].legal_name == 'Legal head'
    assert len(branches) == len(aliases) == 2
    assert {b.name for b in branches} == {'First branch', 'Second branch'}
    assert all(b.legal_entity_id == parents[0].id and b.portal_branch_code is None for b in branches)
    assert all(b.provenance['raw_branch_code']['value'] == '0002' for b in branches)


@pytest.mark.parametrize('changes', [
    {'ОбособленноеПодразделение': 'false'},
    {'ОбособленноеПодразделение': None},
    {'ГоловнойКонтрагент_Key': 'not-a-guid'},
    {'ГоловнойКонтрагент_Key': '00000000-0000-0000-0000-000000000000'},
    {'ГоловнойКонтрагент_Key': '00000000-0000-0000-0000-000000000002'},
    {'ОбособленноеПодразделение': False},
    {'Description': ''},
    {'Ref_Key': ''},
])
async def test_onec_ambiguous_branch_wire_is_never_treated_as_legal_entity(api, session, monkeypatch, changes):
    from sqlalchemy import func, select

    from core.domain.models import Counterparty, CounterpartyBranch, OutboxEvent
    from modules.integrations.client import OneCClient

    row = {'Ref_Key': '00000000-0000-0000-0000-000000000002', 'Description': 'Branch',
           'ИНН': '600187521', 'ОбособленноеПодразделение': True,
           'ГоловнойКонтрагент_Key': '00000000-0000-0000-0000-000000000001', **changes}
    client = OneCClient('https://onec.test')
    monkeypatch.setattr(client, '_get_all', lambda *args, **kwargs: [row])
    gateway = api._transport.app.state.core.services.onec
    monkeypatch.setattr(gateway, 'fetch_counterparties', client.fetch_counterparties)
    response = await api.post('/integrations/1c/sync')
    assert response.status_code in (422, 502), response.text
    assert response.json()['detail']['code'] in ('invalid_onec_classification', 'invalid_onec_identity', 'branch_mapping_required')
    assert await session.scalar(select(func.count()).select_from(Counterparty)) == 0
    assert await session.scalar(select(func.count()).select_from(CounterpartyBranch)) == 0
    assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 0


async def test_1c_sync(session, api):
    from sqlalchemy import select

    from core.domain.models import Counterparty, CounterpartyAlias, OutboxEvent

    r = await api.post("/integrations/1c/sync")
    assert r.status_code == 200
    body = r.json()
    assert body["stock"] == 3
    assert body["counterparties"] == 3
    assert body["counterparty_aliases"] == 3  # на каждый контрагент 1С — alias-провенанс

    stock = (await api.get("/integrations/1c/stock")).json()
    assert len(stock) == 3
    assert any(s["sku_code"] == "AKB-60" for s in stock)

    counterparties = (await session.execute(select(Counterparty))).scalars().all()
    assert len(counterparties) >= 3

    # провенанс источника записан в golden record (Ref_Key 1С → counterparty_alias)
    onec_aliases = (
        await session.execute(select(CounterpartyAlias).where(CounterpartyAlias.source == "1c"))
    ).scalars().all()
    assert len(onec_aliases) == 3

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "integration.1c.synced" in types

    # повторный sync идемпотентен: ни новых контрагентов, ни дублей алиасов
    body2 = (await api.post("/integrations/1c/sync")).json()
    assert body2["new_counterparties"] == 0
    assert body2["counterparty_aliases"] == 0
    again = (
        await session.execute(select(CounterpartyAlias).where(CounterpartyAlias.source == "1c"))
    ).scalars().all()
    assert len(again) == 3


async def test_egr_lookup(api):
    # dev-фикстура явно выдаёт demo, не официальный реестр
    r = await api.get("/integrations/egr/191234567")
    assert r.status_code == 200
    body = r.json()
    assert body["unp"] == "191234567"
    assert "Аккумулятор" in body["name"]
    assert body["status"] == "Действующий"
    assert body["source"] == "demo" and body["source_url"] is None
    assert body["fetched_at"].endswith("Z")

    # неизвестный УНП → 404
    assert (await api.get("/integrations/egr/000000000")).status_code == 404


async def test_sync_conflict_rolls_back_the_whole_import(api, session, monkeypatch):
    from sqlalchemy import func, select

    from core.domain.models import Counterparty
    from core.services.mdm import CounterpartyWriteError
    from modules.integrations import routes

    async def conflicted_sync(session, *_):
        session.add(Counterparty(name="Uncommitted import"))
        await session.flush()
        raise CounterpartyWriteError("ambiguous_unp", "Несколько юридических лиц с одним УНП")

    monkeypatch.setattr(routes, "sync_1c", conflicted_sync)
    response = await api.post("/integrations/1c/sync")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ambiguous_unp"
    assert await session.scalar(select(func.count()).select_from(Counterparty)) == 0


async def test_onec_preserves_both_names_and_rejects_truncated_legal_name(api, monkeypatch):
    from modules.integrations.client import OneCClient

    client = OneCClient("https://onec.test")
    ref = '00000000-0000-0000-0000-000000000001'
    rows = [{"Ref_Key": ref, "Description": "Короткое имя", "НаименованиеПолное": "Полное юридическое имя", "ИНН": "600187521",
             "ОбособленноеПодразделение": False, "ГоловнойКонтрагент_Key": '00000000-0000-0000-0000-000000000000'}]
    monkeypatch.setattr(client, "_get_all", lambda *args, **kwargs: rows)
    mapped = client._fetch_counterparties_sync()
    assert mapped == [{"id": ref, "name": "Короткое имя", "legal_name": "Полное юридическое имя", "unp": "600187521"}]
    rows[0]["НаименованиеПолное"] = "Ю" * 256
    mapped = client._fetch_counterparties_sync()
    assert len(mapped[0]["legal_name"]) == 256
    gateway = api._transport.app.state.core.services.onec
    monkeypatch.setattr(gateway, "fetch_counterparties", AsyncMock(return_value=mapped))
    response = await api.post("/integrations/1c/sync")
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "invalid_legal_name"


@pytest.mark.parametrize(("code", "status"), [
    ("bad_input", 422), ("not_found", 404), ("unconfigured", 503), ("timeout", 503),
    ("unreachable", 503), ("rate_limited", 429), ("invalid_upstream", 502),
    ("upstream_error", 502), ("upstream_access_denied", 502),
])
async def test_registry_api_preserves_error_codes(api, monkeypatch, code, status):
    failure = RegistryError(code, "Безопасное сообщение", status, 60 if status == 429 else None)
    monkeypatch.setattr(RegistryClient, "lookup_strict", AsyncMock(side_effect=failure))
    response = await api.get("/integrations/egr/100582333")
    assert response.status_code == status
    assert response.json() == {"detail": {"code": code, "message": "Безопасное сообщение"}}
    assert response.headers.get("retry-after") == ("60" if status == 429 else None)


async def test_registry_permission_and_input_boundaries(api, monkeypatch):
    strict = AsyncMock()
    monkeypatch.setattr(RegistryClient, "lookup_strict", strict)
    response = await api.get("/integrations/egr/100582333", headers={"X-User-Roles": "guest"})
    assert response.status_code == 403
    strict.assert_not_awaited()


@pytest.mark.parametrize("environment", ["prod", "production", "staging", "dev-preview"])
async def test_module_does_not_enable_implicit_demo(api, monkeypatch, environment):
    core = api._transport.app.state.core
    monkeypatch.setattr(core.config, "environment", environment)
    monkeypatch.setattr(core.config, "egr_base_url", "")
    IntegrationsModule().register(core)
    response = await api.get("/integrations/egr/191234567")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "unconfigured"


async def test_registry_unconfigured_contract_keeps_manual_buyer(api):
    core = api._transport.app.state.core
    core.services.registry = RegistryClient()
    template = await api.post("/sales/contract-templates", json={
        "code": "registry-off", "name": "Без реестра", "body": "{{buyer.name}} {{buyer.unp}}",
    })
    assert template.status_code == 201
    deal = await api.post("/sales/deals", json={
        "number": "REGISTRY-OFF", "title": "Ручные реквизиты", "counterparty": "Ручная компания",
    })
    assert deal.status_code == 201
    response = await api.post(f"/sales/deals/{deal.json()['id']}/contract", json={
        "template_code": "registry-off", "unp": "191234567",
    })
    assert response.status_code == 201, response.text
    html = (await api.get(f"/sales/documents/{response.json()['id']}/render")).text
    assert "Ручная компания" in html and "191234567" in html


async def test_two_modules_loaded(api):
    data = (await api.get("/system/modules")).json()
    assert "sales" in data["loaded_modules"]
    assert "integrations" in data["loaded_modules"]
