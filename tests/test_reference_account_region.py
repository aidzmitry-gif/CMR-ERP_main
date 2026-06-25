"""Справочники план счетов (РБ) и регионы/города — иерархические (parent_id), как группы.

CRUD через `api`-фикстуру (SQLite, create_all), иерархия через parent_id, регистрация
в каталоге-витрине. Эти книги раньше были только HTML-макетами — теперь у них бэкенд.
"""


async def test_accounts_hierarchy_crud(api):
    # пусто на старте
    assert (await api.get("/system/refs/accounts")).json() == []

    # синтетический счёт (корень)
    r = await api.post(
        "/system/refs/accounts",
        json={"code": "60", "title": "Расчёты с поставщиками", "kind": "пассив"},
    )
    assert r.status_code == 200
    synthetic_id = r.json()["id"]
    assert r.json()["kind"] == "пассив"
    assert r.json()["parent_id"] is None

    # субсчёт под синтетическим
    r = await api.post(
        "/system/refs/accounts",
        json={"code": "60.1", "title": "Поставщики (BYN)", "parent_id": synthetic_id},
    )
    assert r.status_code == 200
    assert r.json()["parent_id"] == synthetic_id

    # required: без title → 422
    assert (await api.post("/system/refs/accounts", json={"code": "62"})).status_code == 422

    # плоский список (дерево собирает фронт)
    codes = sorted(a["code"] for a in (await api.get("/system/refs/accounts")).json())
    assert codes == ["60", "60.1"]

    # archive субсчёта (soft-delete)
    assert (await api.delete("/system/refs/accounts/60.1")).status_code == 200
    assert [a["code"] for a in (await api.get("/system/refs/accounts")).json()] == ["60"]


async def test_regions_hierarchy_crud(api):
    # область
    r = await api.post(
        "/system/refs/regions",
        json={"code": "BY-MI", "title": "Минская область", "kind": "область"},
    )
    assert r.status_code == 200
    oblast_id = r.json()["id"]

    # город внутри области
    r = await api.post(
        "/system/refs/regions",
        json={"code": "BY-MI-MINSK", "title": "Минск", "kind": "город", "parent_id": oblast_id},
    )
    assert r.status_code == 200
    assert r.json()["parent_id"] == oblast_id
    assert r.json()["kind"] == "город"

    # уникальность кода: дубль → ошибка (не 200)
    dup = await api.post("/system/refs/regions", json={"code": "BY-MI", "title": "Дубль"})
    assert dup.status_code != 200


async def test_account_region_in_catalog(api):
    departments = (await api.get("/system/references")).json()["departments"]
    by_key = {ref["key"]: ref for refs in departments.values() for ref in refs}
    assert "core.accounts" in by_key
    assert "core.regions" in by_key
    # план счетов сгруппирован под отделом «Финансы» (department — ключ группировки)
    fin_keys = {ref["key"] for ref in departments.get("Финансы", [])}
    assert "core.accounts" in fin_keys
    # данные у владельца public, endpoint указывает на CRUD-роут
    assert by_key["core.accounts"]["owner_schema"] == "public"
    assert by_key["core.accounts"]["endpoint"] == "/system/refs/accounts"
