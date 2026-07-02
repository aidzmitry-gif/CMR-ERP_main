"""API-тесты реестра юридических договоров (office.legal_contract).

Покрывает: list, create (автономер), get by id, patch status.
"""
from __future__ import annotations

import main  # noqa: F401 — проверяем, что main импортируется без ошибок


async def test_list_contracts_empty(api):
    r = await api.get("/office/contracts")
    assert r.status_code == 200
    assert r.json() == []


async def test_create_contract_autonumber(api):
    r = await api.post(
        "/office/contracts",
        json={"counterparty_name": "ООО Поставщик", "contract_type": "supply"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["number"].startswith("ДОГ-")
    assert body["counterparty_name"] == "ООО Поставщик"
    assert body["contract_type"] == "supply"
    assert body["status"] == "active"


async def test_create_contract_custom_number(api):
    r = await api.post(
        "/office/contracts",
        json={
            "counterparty_name": "ИП Иванов",
            "contract_type": "service",
            "number": "МОЙ-НОМЕР-001",
            "signed_at": "2026-01-15",
            "expires_at": "2027-01-15",
            "amount_byn": "12500.00",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["number"] == "МОЙ-НОМЕР-001"
    assert body["signed_at"] == "2026-01-15"
    assert body["expires_at"] == "2027-01-15"
    assert body["amount_byn"] == "12500.00"


async def test_get_contract_by_id(api):
    contract_id = (
        await api.post("/office/contracts", json={"counterparty_name": "Арендатор", "contract_type": "lease"})
    ).json()["id"]

    r = await api.get(f"/office/contracts/{contract_id}")
    assert r.status_code == 200
    assert r.json()["id"] == contract_id
    assert r.json()["contract_type"] == "lease"


async def test_get_contract_not_found(api):
    r = await api.get("/office/contracts/999999")
    assert r.status_code == 404


async def test_patch_contract_status(api):
    contract_id = (
        await api.post("/office/contracts", json={"counterparty_name": "ООО Бета"})
    ).json()["id"]

    r = await api.patch(f"/office/contracts/{contract_id}", json={"status": "terminated"})
    assert r.status_code == 200
    assert r.json()["status"] == "terminated"


async def test_patch_contract_description(api):
    contract_id = (
        await api.post("/office/contracts", json={"counterparty_name": "ООО Гамма"})
    ).json()["id"]

    r = await api.patch(
        f"/office/contracts/{contract_id}",
        json={"description": "Договор на поставку компонентов"},
    )
    assert r.status_code == 200
    assert r.json()["description"] == "Договор на поставку компонентов"


async def test_patch_contract_not_found(api):
    r = await api.patch("/office/contracts/999999", json={"status": "expired"})
    assert r.status_code == 404


async def test_list_contracts_filter_by_status(api):
    await api.post("/office/contracts", json={"counterparty_name": "А", "contract_type": "supply"})
    cid = (
        await api.post("/office/contracts", json={"counterparty_name": "Б", "contract_type": "nda"})
    ).json()["id"]
    await api.patch(f"/office/contracts/{cid}", json={"status": "expired"})

    active = (await api.get("/office/contracts?status=active")).json()
    expired = (await api.get("/office/contracts?status=expired")).json()

    assert all(c["status"] == "active" for c in active)
    assert all(c["status"] == "expired" for c in expired)
    assert len(active) == 1
    assert len(expired) == 1


async def test_list_contracts_filter_by_type(api):
    await api.post("/office/contracts", json={"counterparty_name": "X", "contract_type": "supply"})
    await api.post("/office/contracts", json={"counterparty_name": "Y", "contract_type": "nda"})

    supply = (await api.get("/office/contracts?contract_type=supply")).json()
    nda = (await api.get("/office/contracts?contract_type=nda")).json()

    assert all(c["contract_type"] == "supply" for c in supply)
    assert all(c["contract_type"] == "nda" for c in nda)


async def test_import_main_ok():
    """import main не падает — все модели и роутеры зарегистрированы корректно."""
    import importlib

    importlib.import_module("main")
