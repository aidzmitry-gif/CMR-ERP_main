"""Тесты GET /hr/payroll (список + фильтры) + accrue + pay."""


async def _make_employee(api) -> int:
    r = await api.post("/hr/employees", json={"full_name": "Петров Пётр Петрович"})
    assert r.status_code == 201
    return r.json()["id"]


async def test_list_payroll_empty(api):
    """GET /hr/payroll → 200 + пустой список при отсутствии записей."""
    r = await api.get("/hr/payroll")
    assert r.status_code == 200
    assert r.json() == []


async def test_list_payroll_returns_entries(api):
    """GET /hr/payroll → 200 + список начислений."""
    emp_id = await _make_employee(api)
    await api.post(
        "/hr/payroll/accrue",
        json={"employee_id": emp_id, "period": "2026-06", "amount_byn": "1200.00"},
    )
    r = await api.get("/hr/payroll")
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    assert data[0]["employee_id"] == emp_id
    assert data[0]["period"] == "2026-06"
    assert data[0]["status"] == "pending"


async def test_list_payroll_filter_status_pending(api):
    """GET /hr/payroll?status=pending → только pending."""
    emp_id = await _make_employee(api)

    # Начисляем два периода, один выплачиваем
    await api.post(
        "/hr/payroll/accrue",
        json={"employee_id": emp_id, "period": "2026-04", "amount_byn": "900.00"},
    )
    await api.post(
        "/hr/payroll/accrue",
        json={"employee_id": emp_id, "period": "2026-05", "amount_byn": "950.00"},
    )
    await api.post("/hr/payroll/pay", json={"employee_id": emp_id, "period": "2026-04"})

    r = await api.get("/hr/payroll?status=pending")
    assert r.status_code == 200
    data = r.json()
    assert all(e["status"] == "pending" for e in data)
    periods = [e["period"] for e in data]
    assert "2026-05" in periods
    assert "2026-04" not in periods


async def test_list_payroll_filter_status_paid(api):
    """GET /hr/payroll?status=paid → только paid."""
    emp_id = await _make_employee(api)

    await api.post(
        "/hr/payroll/accrue",
        json={"employee_id": emp_id, "period": "2026-03", "amount_byn": "800.00"},
    )
    await api.post("/hr/payroll/pay", json={"employee_id": emp_id, "period": "2026-03"})

    r = await api.get("/hr/payroll?status=paid")
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    assert all(e["status"] == "paid" for e in data)


async def test_get_single_entry(api):
    """GET /hr/payroll/{id} → 200 с нужной записью."""
    emp_id = await _make_employee(api)
    acc = await api.post(
        "/hr/payroll/accrue",
        json={"employee_id": emp_id, "period": "2026-07", "amount_byn": "2000.00"},
    )
    entry_id = acc.json()["id"]

    r = await api.get(f"/hr/payroll/{entry_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == entry_id
    assert body["amount_byn"] == "2000.00"


async def test_accrue_returns_201(api):
    """POST /hr/payroll/accrue → 201."""
    emp_id = await _make_employee(api)
    r = await api.post(
        "/hr/payroll/accrue",
        json={"employee_id": emp_id, "period": "2026-08", "amount_byn": "500.00"},
    )
    assert r.status_code == 201
    assert r.json()["status"] == "pending"


async def test_pay_changes_status_to_paid(api):
    """POST /hr/payroll/pay → 200 → статус paid."""
    emp_id = await _make_employee(api)
    await api.post(
        "/hr/payroll/accrue",
        json={"employee_id": emp_id, "period": "2026-09", "amount_byn": "1100.00"},
    )
    r = await api.post("/hr/payroll/pay", json={"employee_id": emp_id, "period": "2026-09"})
    assert r.status_code == 200
    assert r.json()["status"] == "paid"
