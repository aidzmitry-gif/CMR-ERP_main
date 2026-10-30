"""Stage instructions share the existing stage CRUD, permissions and funnel scope."""

import pytest


async def test_stage_description_defaults_and_persisted_board_roundtrip(api):
    initial = (await api.get("/sales/board")).json()
    assert all(row["description"] == "" for row in initial["stages"])
    rows = (await api.get("/sales/stages")).json()
    assert all(row["description"] == "" for row in rows)
    text = "Комментарий для команды.\nПроверить документы перед переходом."
    response = await api.patch("/sales/stages/qual", json={"description": text})
    assert response.status_code == 200, response.text
    assert response.json()["description"] == text
    board = (await api.get("/sales/board?funnel=new_clients")).json()
    assert next(row for row in board["stages"] if row["id"] == "qual")["description"] == text
    changed = await api.patch("/sales/stages/qual", json={"title": "Квалификация клиента"})
    assert changed.json()["description"] == text
    cleared = await api.patch("/sales/stages/qual", json={"description": ""})
    assert cleared.status_code == 200 and cleared.json()["description"] == ""
    assert next(row for row in (await api.get("/sales/stages")).json() if row["code"] == "qual")["description"] == ""


async def test_created_stage_description_stays_in_its_funnel(api):
    await api.get("/sales/stages")
    text = "Синтетическое пояснение повторной продажи."
    created = await api.post("/sales/stages", json={
        "code": "qa_instructions", "title": "Проверка", "funnel": "repeat_clients", "description": text,
    })
    assert created.status_code == 201, created.text
    assert created.json()["description"] == text
    own = (await api.get("/sales/board?funnel=repeat_clients")).json()["stages"]
    assert next(row for row in own if row["id"] == "qa_instructions")["description"] == text
    other = (await api.get("/sales/board?funnel=new_clients")).json()["stages"]
    assert all(row["id"] != "qa_instructions" for row in other)


@pytest.mark.parametrize("value", [None, "x" * 2001])
async def test_invalid_description_cannot_replace_saved_instructions(api, value):
    await api.get("/sales/stages")
    saved = await api.patch("/sales/stages/qual", json={"description": "Сохранённый текст"})
    assert saved.status_code == 200
    denied = await api.patch("/sales/stages/qual", json={"description": value})
    assert denied.status_code == 422, denied.text
    denied_create = await api.post("/sales/stages", json={"code": "qa_invalid", "title": "Invalid", "description": value})
    assert denied_create.status_code == 422
    rows = (await api.get("/sales/stages")).json()
    assert next(row for row in rows if row["code"] == "qual")["description"] == "Сохранённый текст"
    assert all(row["code"] != "qa_invalid" for row in rows)


async def test_description_retains_existing_stage_write_permission(api):
    await api.get("/sales/stages")
    denied = await api.patch("/sales/stages/qual", json={"description": "Запрещённая правка"},
                             headers={"X-User": "stage-readonly", "X-User-Roles": "hr"})
    assert denied.status_code == 403, denied.text
    assert denied.json()["detail"] == "Нет доступа к модулю: crm"
    rows = (await api.get("/sales/stages")).json()
    assert next(row for row in rows if row["code"] == "qual")["description"] == ""


async def test_description_accepts_exact_limit_and_literal_markup(api):
    await api.get("/sales/stages")
    text = "<b>Только текст</b>\n" + "я" * (2000 - len("<b>Только текст</b>\n"))
    response = await api.patch("/sales/stages/qual", json={"description": text})
    assert response.status_code == 200, response.text
    assert response.json()["description"] == text
