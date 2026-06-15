"""MDM контрагентов: дедуп по УНП, merge (survivorship + архив + alias), unmerge, гарды."""
import pytest

from core.domain.models import Counterparty
from core.services import mdm


async def test_duplicate_clusters_and_merge(session):
    a = Counterparty(name="ООО Старт", unp="191234567")
    b = Counterparty(name="", unp="191234567")  # дубль с пустым именем
    session.add_all([a, b])
    await session.flush()

    clusters = await mdm.duplicate_clusters(session)
    assert len(clusters) == 1
    assert clusters[0]["unp"] == "191234567"
    assert {m["id"] for m in clusters[0]["members"]} == {a.id, b.id}

    survivor = await mdm.merge(session, a.id, b.id)
    assert survivor.id == a.id
    assert b.is_active is False
    assert b.merged_into_id == a.id

    al = await mdm.aliases(session, a.id)
    assert any(x.source == "merge" and x.external_ref == str(b.id) for x in al)

    # дубль больше не активен → кластеров нет
    assert await mdm.duplicate_clusters(session) == []


async def test_survivorship_fills_empty_survivor_field(session):
    a = Counterparty(name="", unp="100000001")  # эталон с пустым именем
    b = Counterparty(name="ОАО Имя", unp="100000001")
    session.add_all([a, b])
    await session.flush()

    await mdm.merge(session, a.id, b.id)
    assert a.name == "ОАО Имя"  # непустое из дубля заполнило пустое эталона


async def test_unmerge_reverses(session):
    a = Counterparty(name="A", unp="100000002")
    b = Counterparty(name="B", unp="100000002")
    session.add_all([a, b])
    await session.flush()

    await mdm.merge(session, a.id, b.id)
    await mdm.unmerge(session, b.id)

    assert b.is_active is True
    assert b.merged_into_id is None
    assert await mdm.aliases(session, a.id) == []  # merge-alias убран


async def test_match_candidates_by_unp(session):
    a = Counterparty(name="A", unp="555")
    b = Counterparty(name="B", unp="555")
    c = Counterparty(name="C", unp="777")
    session.add_all([a, b, c])
    await session.flush()

    found = await mdm.match_candidates(session, unp="555", exclude_id=a.id)
    assert [x.id for x in found] == [b.id]
    assert await mdm.match_candidates(session, unp=None) == []


async def test_merge_guards(session):
    a = Counterparty(name="A", unp="x")
    session.add(a)
    await session.flush()
    with pytest.raises(ValueError):
        await mdm.merge(session, a.id, a.id)  # сам с собой
    with pytest.raises(ValueError):
        await mdm.merge(session, a.id, 999999)  # несуществующий


async def test_mdm_endpoints(api, session):
    session.add_all([Counterparty(name="ООО X", unp="222"), Counterparty(name="", unp="222")])
    await session.commit()

    clusters = (await api.get("/system/mdm/duplicates")).json()["clusters"]
    assert len(clusters) == 1
    ids = [m["id"] for m in clusters[0]["members"]]

    r = await api.post(
        "/system/mdm/merge", json={"survivor_id": ids[0], "duplicate_id": ids[1]}
    )
    assert r.status_code == 200
    assert (await api.get("/system/mdm/duplicates")).json()["clusters"] == []

    r = await api.post("/system/mdm/unmerge", json={"duplicate_id": ids[1]})
    assert r.status_code == 200
    assert len((await api.get("/system/mdm/duplicates")).json()["clusters"]) == 1
