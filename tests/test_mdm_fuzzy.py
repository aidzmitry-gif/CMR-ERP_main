"""M1: fuzzy-дедуп контрагентов по имени (опечатки/орг-форма, без совпадения УНП)."""
from core.domain.models import Counterparty
from core.services import mdm


async def test_normalize_strips_org_form_and_quotes():
    assert mdm._normalize_name('ООО «БелАвтоТех»') == "белавтотех"
    assert mdm._normalize_name('ОАО "Бел-Авто Тех"') == "бел авто тех"


async def test_fuzzy_finds_typo_without_unp_match(session):
    a = Counterparty(name="ООО «БелАвтоТех»", unp="100000001")
    b = Counterparty(name="ООО БелАвтоТех", unp=None)  # тот же по сути, УНП пуст
    c = Counterparty(name="ООО МеталлПром", unp="100000009")
    session.add_all([a, b, c])
    await session.flush()

    got = await mdm.fuzzy_candidates(session, name="БелАвтоТех", threshold=0.6)
    names = {g["name"] for g in got}
    assert "ООО «БелАвтоТех»" in names
    assert "ООО БелАвтоТех" in names
    assert "ООО МеталлПром" not in names  # непохоже — отсечено
    assert all(g["score"] >= 0.6 for g in got)
    # отсортировано по убыванию похожести
    assert got == sorted(got, key=lambda g: g["score"], reverse=True)


async def test_fuzzy_excludes_self(session):
    a = Counterparty(name="ООО Ромашка", unp="100000002")
    session.add(a)
    await session.flush()
    got = await mdm.fuzzy_candidates(session, name="Ромашка", exclude_id=a.id)
    assert all(g["id"] != a.id for g in got)


async def test_fuzzy_ignores_archived(session):
    a = Counterparty(name="ООО Архивный", unp="100000003", is_active=False)
    session.add(a)
    await session.flush()
    got = await mdm.fuzzy_candidates(session, name="Архивный")
    assert all(g["id"] != a.id for g in got)


async def test_fuzzy_empty_name_returns_nothing(session):
    got = await mdm.fuzzy_candidates(session, name="   ")
    assert got == []


async def test_fuzzy_endpoint(api, session):
    session.add_all([
        Counterparty(name="ООО «СтройКомплект»", unp="100000004"),
        Counterparty(name="ООО СтройКомплект Плюс", unp="100000005"),
    ])
    await session.commit()
    r = await api.get("/system/mdm/fuzzy", params={"name": "СтройКомплект"})
    assert r.status_code == 200
    cands = r.json()["candidates"]
    assert any("СтройКомплект" in c["name"] for c in cands)
