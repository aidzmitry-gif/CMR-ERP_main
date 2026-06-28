"""AI structural-query: агрегаты (count/group_by) + джойн-resolve мягких ссылок SKU."""
from datetime import date
from decimal import Decimal

from core.domain.models import Sku
from core.domain.reference import NomenclatureCategory, TnvedCode

Q = "/system/references/query"


async def test_aggregate_count(api, session):
    session.add_all([Sku(code="A", title="a", unit="шт"), Sku(code="B", title="b", unit="шт")])
    await session.commit()
    r = await api.post(Q, json={"ref": "core.skus", "aggregate": "count"})
    assert r.json()["result"] == 2


async def test_aggregate_group_by_category(api, session):
    g1 = NomenclatureCategory(code="G1", name="g1")
    g2 = NomenclatureCategory(code="G2", name="g2")
    session.add_all([g1, g2])
    await session.flush()
    session.add_all([
        Sku(code="A", title="a", unit="шт", category_id=g1.id),
        Sku(code="B", title="b", unit="шт", category_id=g1.id),
        Sku(code="C", title="c", unit="шт", category_id=g2.id),
    ])
    await session.commit()
    r = await api.post(Q, json={"ref": "core.skus", "aggregate": "group_by", "group_by": "category_id"})
    body = r.json()
    assert body["aggregate"] == "group_by"
    counts = {row["value"]: row["count"] for row in body["result"]}
    assert counts[g1.id] == 2
    assert counts[g2.id] == 1


async def test_aggregate_unknown_field_422(api):
    r = await api.post(Q, json={"ref": "core.skus", "aggregate": "group_by", "group_by": "title"})
    assert r.status_code == 422  # title не в whitelist


async def test_aggregate_unknown_op_422(api):
    assert (await api.post(Q, json={"ref": "core.skus", "aggregate": "sum"})).status_code == 422


async def test_resolve_sku_effective_fields(api, session):
    session.add(TnvedCode(code="8536", name="реле", duty_rate=Decimal("5"), vat_code=None,
                          unit="шт", start_date=date(2020, 1, 1)))
    root = NomenclatureCategory(code="GR", name="root", tnved_code="8536", country="CN")
    session.add(root)
    await session.flush()
    session.add(Sku(code="RS-1", title="реле", unit="шт", category_id=root.id))
    await session.commit()

    r = await api.post(Q, json={"ref": "core.skus", "key": "RS-1", "resolve": True})
    res = r.json()["result"]
    assert res["effective_tnved"]["code"] == "8536"
    assert res["effective_tnved"]["source"] == "group"  # унаследован от группы
    assert res["effective_tnved"]["rates"]["duty_rate"] == 5.0
    assert res["effective_country"]["value"] == "CN"
    assert res["effective_country"]["source"] == "group"


async def test_resolve_unknown_sku_null(api):
    r = await api.post(Q, json={"ref": "core.skus", "key": "NOPE", "resolve": True})
    assert r.json()["result"] is None


async def test_resolve_only_skus(api):
    r = await api.post(Q, json={"ref": "core.units", "key": "PCS", "resolve": True})
    assert r.status_code == 422  # resolve только для core.skus
