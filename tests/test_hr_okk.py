"""Тесты ОКК-оценок сотрудников: GET /hr/okk-scores, POST, GET с фильтром."""


async def _make_employee(api) -> int:
    r = await api.post("/hr/employees", json={"full_name": "Петров Пётр Петрович"})
    assert r.status_code == 201
    return r.json()["id"]


async def _make_score(api, employee_id: int, **kwargs) -> dict:
    payload = {
        "employee_id": employee_id,
        "period": "2026-06",
        "discipline": 20,
        "quality": 22,
        "service": 18,
        "teamwork": 25,
        **kwargs,
    }
    r = await api.post("/hr/okk-scores", json=payload)
    assert r.status_code == 201
    return r.json()


async def test_list_empty(api):
    """GET /hr/okk-scores → 200, пустой список."""
    r = await api.get("/hr/okk-scores")
    assert r.status_code == 200
    assert r.json() == []


async def test_create_and_total(api):
    """POST /hr/okk-scores → 201, total = sum четырёх категорий."""
    emp_id = await _make_employee(api)
    body = await _make_score(api, emp_id, discipline=20, quality=22, service=18, teamwork=25)

    assert body["employee_id"] == emp_id
    assert body["period"] == "2026-06"
    assert body["discipline"] == 20
    assert body["quality"] == 22
    assert body["service"] == 18
    assert body["teamwork"] == 25
    assert body["total"] == 85  # 20+22+18+25


async def test_total_zero_defaults(api):
    """total = 0 если все категории 0 (дефолт)."""
    emp_id = await _make_employee(api)
    r = await api.post(
        "/hr/okk-scores",
        json={"employee_id": emp_id, "period": "2026-06"},
    )
    assert r.status_code == 201
    assert r.json()["total"] == 0


async def test_get_by_id(api):
    """GET /hr/okk-scores/{id} → 200 с данными."""
    emp_id = await _make_employee(api)
    created = await _make_score(api, emp_id)

    r = await api.get(f"/hr/okk-scores/{created['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == created["id"]
    assert body["total"] == created["total"]


async def test_get_by_id_not_found(api):
    """GET /hr/okk-scores/999999 → 404."""
    r = await api.get("/hr/okk-scores/999999")
    assert r.status_code == 404


async def test_filter_by_employee_id(api):
    """GET /hr/okk-scores?employee_id= → только оценки этого сотрудника."""
    emp1 = await _make_employee(api)
    emp2 = await _make_employee(api)

    await _make_score(api, emp1)
    await _make_score(api, emp2)

    r = await api.get(f"/hr/okk-scores?employee_id={emp1}")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["employee_id"] == emp1


async def test_filter_by_period(api):
    """GET /hr/okk-scores?period= → только оценки за этот период."""
    emp_id = await _make_employee(api)

    await _make_score(api, emp_id, period="2026-05")
    await _make_score(api, emp_id, period="2026-06")

    r = await api.get("/hr/okk-scores?period=2026-05")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["period"] == "2026-05"


async def test_total_computed_correctly(api):
    """total = discipline + quality + service + teamwork для любых значений."""
    emp_id = await _make_employee(api)
    body = await _make_score(api, emp_id, discipline=10, quality=15, service=5, teamwork=20)
    assert body["total"] == 10 + 15 + 5 + 20


async def test_import_main():
    """import main не падает (smoke-тест зависимостей)."""
    import importlib
    import os

    os.environ.setdefault("AIOS_AUTH_MODE", "dev")
    os.environ.setdefault("AIOS_ENVIRONMENT", "dev")
    importlib.import_module("main")
