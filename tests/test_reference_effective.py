"""Account/Region: датированный ввод/вывод из оборота (effective_from/effective_to)."""


async def test_account_effective_dating_crud_and_query(api):
    r = await api.post(
        "/system/refs/accounts",
        json={"code": "60", "title": "Расчёты с поставщиками", "effective_from": "2024-01-01"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["effective_from"] == "2024-01-01"  # ISO-строка скоэрсилась в date и вернулась
    assert body["effective_to"] is None

    # вывод из оборота через PATCH
    p = await api.patch("/system/refs/accounts/60", json={"effective_to": "2026-01-01"})
    assert p.json()["effective_to"] == "2026-01-01"

    # reference.query отдаёт даты периода
    q = await api.post("/system/references/query", json={"ref": "core.accounts", "key": "60"})
    res = q.json()["result"]
    assert res["effective_from"] == "2024-01-01"
    assert res["effective_to"] == "2026-01-01"


async def test_region_effective_bulk_upsert(api):
    r = await api.post(
        "/system/refs/regions/bulk",
        json={"rows": [{"code": "BY-MI", "title": "Минская обл.", "effective_from": "2020-01-01"}]},
    )
    assert r.status_code == 200
    assert r.json()["created"] == 1
    q = await api.post("/system/references/query", json={"ref": "core.regions", "key": "BY-MI"})
    assert q.json()["result"]["effective_from"] == "2020-01-01"


async def test_account_effective_columns_in_catalog(api):
    cat = (await api.get("/system/references")).json()
    acc = next(r for r in cat["departments"]["Финансы"] if r["key"] == "core.accounts")
    cols = {c["name"] for c in acc["columns"]}
    assert {"effective_from", "effective_to"} <= cols
