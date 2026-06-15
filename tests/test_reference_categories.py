"""Группы (категории) номенклатуры — иерархический справочник + связь Sku.category_id."""
from core.domain.models import Sku

BASE = "/system/refs/nomenclature-groups"


async def test_category_crud_and_hierarchy(api):
    # корень
    root = (await api.post(BASE, json={"code": "CAT-0100", "name": "Электронные компоненты"})).json()
    assert root["code"] == "CAT-0100"
    assert root["parent_id"] is None
    assert root["is_active"] is True

    # потомок ссылается на корень (adjacency list)
    child = (
        await api.post(BASE, json={"code": "CAT-0102", "name": "Микросхемы", "parent_id": root["id"]})
    ).json()
    assert child["parent_id"] == root["id"]

    # список — плоский, по коду; фронт собирает дерево из parent_id
    items = (await api.get(BASE)).json()
    assert [i["code"] for i in items] == ["CAT-0100", "CAT-0102"]

    # переименование
    await api.patch(f"{BASE}/CAT-0102", json={"name": "Микросхемы (ИС)"})
    assert (await api.get(BASE)).json()[1]["name"] == "Микросхемы (ИС)"

    # архив (мягкое удаление) — пропадает из активных, виден с ?archived=true
    assert (await api.delete(f"{BASE}/CAT-0102")).status_code == 200
    assert [i["code"] for i in (await api.get(BASE)).json()] == ["CAT-0100"]
    assert len((await api.get(f"{BASE}?archived=true")).json()) == 2


async def test_category_required_fields(api):
    assert (await api.post(BASE, json={"name": "без кода"})).status_code == 422


async def test_query_categories(api):
    await api.post(BASE, json={"code": "CAT-0200", "name": "Кабельная продукция"})

    # по коду → одна группа
    r = await api.post(
        "/system/references/query", json={"ref": "core.nomenclature_groups", "key": "CAT-0200"}
    )
    assert r.status_code == 200
    assert r.json()["result"]["name"] == "Кабельная продукция"

    # без key → список активных (для дерева)
    r = await api.post("/system/references/query", json={"ref": "core.nomenclature_groups"})
    assert any(g["code"] == "CAT-0200" for g in r.json()["result"])


async def test_sku_links_to_category(api, session):
    grp = (await api.post(BASE, json={"code": "CAT-0300", "name": "Аккумуляторы"})).json()
    session.add(Sku(code="AKB-60", title="Аккумулятор 60 А·ч", unit="шт", category_id=grp["id"]))
    await session.commit()

    r = await api.post("/system/references/query", json={"ref": "core.skus", "key": "AKB-60"})
    assert r.json()["result"][0]["category_id"] == grp["id"]


async def test_catalog_and_ai_expose_groups(api):
    cat = (await api.get("/system/references")).json()
    keys = [r["key"] for r in cat["departments"]["Общие"]]
    assert "core.nomenclature_groups" in keys

    ai = (await api.get("/system/references/ai-catalog")).json()
    assert any(r["key"] == "core.nomenclature_groups" for r in ai["references"])
