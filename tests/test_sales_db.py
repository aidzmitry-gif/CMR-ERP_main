"""БД-зависимые тесты модуля Sales (SQLite в памяти)."""


async def test_create_and_list_deal(api):
    r = await api.post(
        "/sales/deals",
        json={
            "number": "CRM-T-1",
            "title": "Тест",
            "counterparty": "ООО Тест",
            "amount": 1000,
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["id"] is not None
    assert body["number"] == "CRM-T-1"
    assert body["stage"] == "Новая заявка"

    r2 = await api.get("/sales/deals")
    assert r2.status_code == 200
    numbers = [d["number"] for d in r2.json()]
    assert "CRM-T-1" in numbers


async def test_unique_number(api):
    payload = {"number": "CRM-DUP", "title": "A", "counterparty": "X"}
    r1 = await api.post("/sales/deals", json=payload)
    assert r1.status_code == 201
    # повторный тот же номер → нарушение уникальности → 409
    r2 = await api.post("/sales/deals", json=payload)
    assert r2.status_code == 409
