"""API-тесты учёта прохождения курсов (knowledge.course_enrollment).

Покрывает: list, create, get by id/404, patch status/progress/completed_at
автопроставление, patch not found, filter by employee_name, filter by status.
"""
from __future__ import annotations

import main  # noqa: F401 — проверяем, что main импортируется без ошибок


async def test_list_enrollments_empty(api):
    r = await api.get("/knowledge/enrollments")
    assert r.status_code == 200
    assert r.json() == []


async def test_create_enrollment(api):
    r = await api.post(
        "/knowledge/enrollments",
        json={"course_id": 1, "employee_name": "Иванов Иван", "assigned_at": "2026-07-01"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["course_id"] == 1
    assert body["employee_name"] == "Иванов Иван"
    assert body["status"] == "assigned"
    assert body["progress"] == 0
    assert body["assigned_at"] == "2026-07-01"
    assert body["completed_at"] is None


async def test_get_enrollment_by_id(api):
    eid = (
        await api.post("/knowledge/enrollments", json={"course_id": 2, "employee_name": "Петров Пётр"})
    ).json()["id"]

    r = await api.get(f"/knowledge/enrollments/{eid}")
    assert r.status_code == 200
    assert r.json()["id"] == eid
    assert r.json()["employee_name"] == "Петров Пётр"


async def test_get_enrollment_not_found(api):
    r = await api.get("/knowledge/enrollments/999999")
    assert r.status_code == 404


async def test_patch_enrollment_status(api):
    eid = (
        await api.post("/knowledge/enrollments", json={"course_id": 3, "employee_name": "Сидоров"})
    ).json()["id"]

    r = await api.patch(f"/knowledge/enrollments/{eid}", json={"status": "in_progress"})
    assert r.status_code == 200
    assert r.json()["status"] == "in_progress"


async def test_patch_enrollment_progress(api):
    eid = (
        await api.post("/knowledge/enrollments", json={"course_id": 4, "employee_name": "Козлов"})
    ).json()["id"]

    r = await api.patch(f"/knowledge/enrollments/{eid}", json={"progress": 50})
    assert r.status_code == 200
    assert r.json()["progress"] == 50


async def test_patch_enrollment_completed_auto_date(api):
    """При status=completed без completed_at — дата и прогресс проставляются автоматически."""
    eid = (
        await api.post("/knowledge/enrollments", json={"course_id": 5, "employee_name": "Новиков"})
    ).json()["id"]

    r = await api.patch(f"/knowledge/enrollments/{eid}", json={"status": "completed"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["progress"] == 100
    assert body["completed_at"] is not None
    assert len(body["completed_at"]) == 10  # формат YYYY-MM-DD


async def test_patch_enrollment_completed_explicit_date(api):
    """При status=completed с явной completed_at — дата сохраняется как передана."""
    eid = (
        await api.post("/knowledge/enrollments", json={"course_id": 6, "employee_name": "Морозов"})
    ).json()["id"]

    r = await api.patch(
        f"/knowledge/enrollments/{eid}",
        json={"status": "completed", "completed_at": "2026-06-30"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["completed_at"] == "2026-06-30"
    assert body["progress"] == 100


async def test_patch_enrollment_not_found(api):
    r = await api.patch("/knowledge/enrollments/999999", json={"status": "completed"})
    assert r.status_code == 404


async def test_list_enrollments_filter_by_employee(api):
    await api.post("/knowledge/enrollments", json={"course_id": 1, "employee_name": "Алексеев"})
    await api.post("/knowledge/enrollments", json={"course_id": 2, "employee_name": "Борисов"})

    alexeev = (await api.get("/knowledge/enrollments?employee_name=Алексеев")).json()
    borisov = (await api.get("/knowledge/enrollments?employee_name=Борисов")).json()

    assert all(e["employee_name"] == "Алексеев" for e in alexeev)
    assert all(e["employee_name"] == "Борисов" for e in borisov)
    assert len(alexeev) == 1
    assert len(borisov) == 1


async def test_list_enrollments_filter_by_status(api):
    eid = (
        await api.post("/knowledge/enrollments", json={"course_id": 7, "employee_name": "Власов"})
    ).json()["id"]
    await api.post("/knowledge/enrollments", json={"course_id": 8, "employee_name": "Громов"})
    await api.patch(f"/knowledge/enrollments/{eid}", json={"status": "completed"})

    assigned = (await api.get("/knowledge/enrollments?status=assigned")).json()
    completed = (await api.get("/knowledge/enrollments?status=completed")).json()

    assert all(e["status"] == "assigned" for e in assigned)
    assert all(e["status"] == "completed" for e in completed)
    assert len(assigned) == 1
    assert len(completed) == 1


async def test_import_main_ok():
    """import main не падает — все модели и роутеры зарегистрированы корректно."""
    import importlib

    importlib.import_module("main")
