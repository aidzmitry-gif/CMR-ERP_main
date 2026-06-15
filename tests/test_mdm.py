"""MDM контрагентов: дедуп по УНП, merge (survivorship + архив + alias), unmerge, гарды."""
import pytest

from core.domain.models import Contact, Counterparty
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


async def test_counterparty_card(api, session):
    # эталон + контакт; затем слитый дубль (alias merge) и внешний alias 1С
    etalon = Counterparty(name="ООО Эталон", unp="190445566")
    session.add(etalon)
    await session.flush()
    session.add(Contact(counterparty_id=etalon.id, full_name="Иван Петров",
                        phone="+375291112233", is_primary=True))
    dup = Counterparty(name="ООО Эталон дубль", unp="190445566")
    session.add(dup)
    await session.flush()
    await mdm.add_source_alias(session, etalon.id, "1c", "0000-77")  # источник 1С
    await mdm.merge(session, etalon.id, dup.id)                       # даст merge-alias + слитый дубль
    await session.commit()

    card = (await api.get(f"/system/mdm/counterparty/{etalon.id}")).json()
    assert card["id"] == etalon.id
    assert card["unp"] == "190445566"
    assert {a["source"] for a in card["aliases"]} == {"1c", "merge"}
    assert [d["id"] for d in card["merged_duplicates"]] == [dup.id]
    assert [c["full_name"] for c in card["contacts"]] == ["Иван Петров"]
    assert card["audit"] == []  # доменных событий по контрагенту пока не пишется

    assert (await api.get("/system/mdm/counterparty/999999")).status_code == 404
