"""Структурный доступ AI — tool reference.query: точные значения с историчностью as_of."""
from datetime import date
from decimal import Decimal

from core.domain.models import Counterparty, CounterpartyBranch
from core.domain.reference import CurrencyRate, Unit, VatRate


async def test_query_versioned_as_of(api, session):
    session.add_all(
        [
            CurrencyRate(currency_code="USD", rate=Decimal("3.18"),
                         start_date=date(2026, 1, 1), end_date=date(2026, 5, 1)),
            CurrencyRate(currency_code="USD", rate=Decimal("3.25"),
                         start_date=date(2026, 5, 1), end_date=None),
            VatRate(code="НДС20", title="НДС 20%", rate=Decimal("20.00"),
                    start_date=date(2024, 1, 1), end_date=None),
        ]
    )
    await session.commit()

    # на дату внутри первого периода → старая ставка
    r = await api.post(
        "/system/references/query",
        json={"ref": "core.currency_rates", "key": "USD", "as_of": "2026-03-01"},
    )
    assert r.status_code == 200
    assert float(r.json()["result"]["rate"]) == 3.18

    # граница: start включительно → на 2026-05-01 уже новая
    r = await api.post(
        "/system/references/query",
        json={"ref": "core.currency_rates", "key": "USD", "as_of": "2026-05-01"},
    )
    assert float(r.json()["result"]["rate"]) == 3.25

    # без as_of → текущая (end_date пуст)
    r = await api.post(
        "/system/references/query", json={"ref": "core.currency_rates", "key": "USD"}
    )
    assert float(r.json()["result"]["rate"]) == 3.25
    assert r.json()["result"]["end_date"] is None

    # НДС на дату
    r = await api.post(
        "/system/references/query",
        json={"ref": "core.vat_rates", "key": "НДС20", "as_of": "2025-06-01"},
    )
    assert float(r.json()["result"]["rate"]) == 20.0


async def test_query_simple_key_and_list(api, session):
    session.add(Unit(code="шт", title="Штука"))
    await session.commit()

    r = await api.post("/system/references/query", json={"ref": "core.units", "key": "шт"})
    assert r.json()["result"]["title"] == "Штука"

    r = await api.post("/system/references/query", json={"ref": "core.units"})
    assert [u["code"] for u in r.json()["result"]] == ["шт"]


async def test_query_counterparties_excludes_merged(api, session):
    a = Counterparty(name="ООО X", unp="333")
    session.add(a)
    await session.flush()
    session.add(Counterparty(name="ООО X дубль", unp="333", is_active=False, merged_into_id=a.id))
    await session.commit()

    r = await api.post("/system/references/query", json={"ref": "core.counterparties", "key": "333"})
    assert [c["id"] for c in r.json()["result"]] == [a.id]  # слитый дубль исключён

    r = await api.post(
        "/system/references/query", json={"ref": "core.counterparties", "name": "ООО X"}
    )
    assert [c["id"] for c in r.json()["result"]] == [a.id]


async def test_query_errors(api):
    assert (await api.post("/system/references/query", json={})).status_code == 422

    assert (
        await api.post("/system/references/query", json={"ref": "core.unknown"})
    ).status_code == 422
    # версионный без key
    assert (
        await api.post("/system/references/query", json={"ref": "core.currency_rates"})
    ).status_code == 422
    # контрагенты без key/name
    assert (
        await api.post("/system/references/query", json={"ref": "core.counterparties"})
    ).status_code == 422


async def test_counterparty_search_matches_both_names_and_keeps_identity(api, session):
    cp = Counterparty(name="Legacy reference", display_name="Удобное имя", legal_name="Полное юридическое название", unp="600187521")
    session.add(cp)
    await session.commit()
    for value in ("Удобное", "юридическое", "Legacy reference"):
        response = await api.post("/system/references/query", json={"ref": "core.counterparties", "name": value})
        assert response.status_code == 200, response.text
        assert response.json()["result"] == [{"id": cp.id, "name": "Удобное имя", "legal_name": "Полное юридическое название", "unp": "600187521", "branches": []}]


async def test_branch_search_keeps_parent_and_distinct_branch_ids(api, session):
    parent = Counterparty(name="Головная", unp="600187521")
    other = Counterparty(name="Архивная", unp="600187522", is_active=False)
    session.add_all([parent, other])
    await session.flush()
    branches = [
        CounterpartyBranch(legal_entity_id=parent.id, name="Брест"),
        CounterpartyBranch(legal_entity_id=parent.id, name="Минск"),
        CounterpartyBranch(legal_entity_id=parent.id, name="Закрытый", is_active=False),
        CounterpartyBranch(legal_entity_id=other.id, name="Брест"),
    ]
    session.add_all(branches)
    await session.commit()
    for query in ({"key": parent.unp}, {"name": "Брест"}):
        response = await api.post("/system/references/query", json={"ref": "core.counterparties", **query})
        assert response.status_code == 200
        rows = response.json()["result"]
        assert [row["id"] for row in rows] == [parent.id]
        assert rows[0]["branches"] == [{"id": b.id, "name": b.name} for b in branches[:2]]
    card = await api.get(f"/system/mdm/counterparty/{parent.id}")
    assert card.status_code == 200
    assert {b["id"] for b in card.json()["branches"]} == {b.id for b in branches[:3]}
    assert all(b["legal_entity_id"] == parent.id for b in card.json()["branches"])


async def test_ai_catalog_advertises_query_tool(api):
    cat = (await api.get("/system/references/ai-catalog")).json()
    assert cat["tool"]["name"] == "reference.query"
    assert cat["tool"]["endpoint"] == "/system/references/query"
    assert any(r["key"] == "core.counterparties" for r in cat["references"])
