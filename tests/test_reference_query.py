"""Структурный доступ AI — tool reference.query: точные значения с историчностью as_of."""
from datetime import date
from decimal import Decimal

from core.domain.models import Counterparty
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


async def test_ai_catalog_advertises_query_tool(api):
    cat = (await api.get("/system/references/ai-catalog")).json()
    assert cat["tool"]["name"] == "reference.query"
    assert cat["tool"]["endpoint"] == "/system/references/query"
    assert any(r["key"] == "core.counterparties" for r in cat["references"])
