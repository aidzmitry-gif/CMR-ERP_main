"""API-тесты реестра юридических претензий (office.legal_claim).

Покрывает: list, create (автономер + кастомный номер), get by id, patch status,
patch description, patch not found, filter by status, filter by type.
"""
from __future__ import annotations

import main  # noqa: F401 — проверяем, что main импортируется без ошибок


async def test_list_claims_empty(api):
    r = await api.get("/office/claims")
    assert r.status_code == 200
    assert r.json() == []


async def test_create_claim_autonumber(api):
    r = await api.post(
        "/office/claims",
        json={"counterparty_name": "ООО Поставщик", "claim_type": "overdue_payment"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["number"].startswith("ПРЕТ-")
    assert body["counterparty_name"] == "ООО Поставщик"
    assert body["claim_type"] == "overdue_payment"
    assert body["status"] == "open"


async def test_create_claim_custom_number(api):
    r = await api.post(
        "/office/claims",
        json={
            "counterparty_name": "ИП Иванов",
            "claim_type": "defect",
            "number": "ПРЕТ-МОЙ-001",
            "amount_byn": "5000.00",
            "filed_at": "2026-06-01",
            "description": "Брак партии",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["number"] == "ПРЕТ-МОЙ-001"
    assert body["claim_type"] == "defect"
    assert body["amount_byn"] == "5000.00"
    assert body["filed_at"] == "2026-06-01"
    assert body["description"] == "Брак партии"


async def test_get_claim_by_id(api):
    claim_id = (
        await api.post("/office/claims", json={"counterparty_name": "Арендатор", "claim_type": "shortage"})
    ).json()["id"]

    r = await api.get(f"/office/claims/{claim_id}")
    assert r.status_code == 200
    assert r.json()["id"] == claim_id
    assert r.json()["claim_type"] == "shortage"


async def test_get_claim_not_found(api):
    r = await api.get("/office/claims/999999")
    assert r.status_code == 404


async def test_patch_claim_status(api):
    claim_id = (
        await api.post("/office/claims", json={"counterparty_name": "ООО Бета"})
    ).json()["id"]

    r = await api.patch(f"/office/claims/{claim_id}", json={"status": "sent"})
    assert r.status_code == 200
    assert r.json()["status"] == "sent"


async def test_patch_claim_description(api):
    claim_id = (
        await api.post("/office/claims", json={"counterparty_name": "ООО Гамма"})
    ).json()["id"]

    r = await api.patch(
        f"/office/claims/{claim_id}",
        json={"description": "Претензия по просрочке платежа"},
    )
    assert r.status_code == 200
    assert r.json()["description"] == "Претензия по просрочке платежа"


async def test_patch_claim_not_found(api):
    r = await api.patch("/office/claims/999999", json={"status": "resolved"})
    assert r.status_code == 404


async def test_list_claims_filter_by_status(api):
    await api.post("/office/claims", json={"counterparty_name": "А", "claim_type": "overdue_payment"})
    cid = (
        await api.post("/office/claims", json={"counterparty_name": "Б", "claim_type": "defect"})
    ).json()["id"]
    await api.patch(f"/office/claims/{cid}", json={"status": "resolved"})

    open_claims = (await api.get("/office/claims?status=open")).json()
    resolved_claims = (await api.get("/office/claims?status=resolved")).json()

    assert all(c["status"] == "open" for c in open_claims)
    assert all(c["status"] == "resolved" for c in resolved_claims)
    assert len(open_claims) == 1
    assert len(resolved_claims) == 1


async def test_list_claims_filter_by_type(api):
    await api.post("/office/claims", json={"counterparty_name": "X", "claim_type": "overdue_payment"})
    await api.post("/office/claims", json={"counterparty_name": "Y", "claim_type": "shortage"})

    overdue = (await api.get("/office/claims?claim_type=overdue_payment")).json()
    shortage = (await api.get("/office/claims?claim_type=shortage")).json()

    assert all(c["claim_type"] == "overdue_payment" for c in overdue)
    assert all(c["claim_type"] == "shortage" for c in shortage)


async def test_import_main_ok():
    """import main не падает — все модели и роутеры зарегистрированы корректно."""
    import importlib

    importlib.import_module("main")
