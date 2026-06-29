"""Тесты payroll-эндпоинтов HR: начисление + выплата + события outbox."""
from sqlalchemy import select

from core.domain.models import OutboxEvent

# --- helpers ---

async def _make_employee(api) -> int:
    r = await api.post("/hr/employees", json={"full_name": "Иванов Иван Иванович"})
    assert r.status_code == 201
    return r.json()["id"]


# --- тесты ---


async def test_accrue_creates_entry_and_event(api, session):
    """POST /hr/payroll/accrue создаёт PayrollEntry(pending) и outbox-событие accrued."""
    emp_id = await _make_employee(api)

    r = await api.post(
        "/hr/payroll/accrue",
        json={"employee_id": emp_id, "period": "2026-06", "amount_byn": "1500.00"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending"
    assert body["employee_id"] == emp_id
    assert body["period"] == "2026-06"
    assert body["amount_byn"] == "1500.00"
    assert isinstance(body["amount_byn"], str)  # не float

    events = (await session.execute(select(OutboxEvent))).scalars().all()
    types = [e.event_type for e in events]
    assert "hr.payroll.accrued" in types

    accrued = next(e for e in events if e.event_type == "hr.payroll.accrued")
    payload = accrued.payload
    assert payload["employee_id"] == emp_id
    assert payload["employee_name"] == "Иванов Иван Иванович"
    assert payload["period"] == "2026-06"
    assert payload["amount_byn"] == "1500.00"
    assert isinstance(payload["amount_byn"], str)  # контракт: str, не float
    assert payload["entity_ref"].startswith("payroll:")


async def test_pay_closes_entry_and_event(api, session):
    """POST /hr/payroll/pay переводит запись в paid и эмитит hr.payroll.paid."""
    emp_id = await _make_employee(api)

    await api.post(
        "/hr/payroll/accrue",
        json={"employee_id": emp_id, "period": "2026-05", "amount_byn": "2000.50"},
    )

    r = await api.post(
        "/hr/payroll/pay",
        json={"employee_id": emp_id, "period": "2026-05"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "paid"
    assert body["amount_byn"] == "2000.50"

    events = (await session.execute(select(OutboxEvent))).scalars().all()
    types = [e.event_type for e in events]
    assert "hr.payroll.paid" in types

    paid_evt = next(e for e in events if e.event_type == "hr.payroll.paid")
    p = paid_evt.payload
    assert p["employee_id"] == emp_id
    assert p["period"] == "2026-05"
    assert p["amount_byn"] == "2000.50"
    assert isinstance(p["amount_byn"], str)
    assert p["entity_ref"].startswith("payroll:")


async def test_pay_twice_idempotent(api):
    """Второй вызов pay для уже выплаченного периода → 404, не дубль."""
    emp_id = await _make_employee(api)

    await api.post(
        "/hr/payroll/accrue",
        json={"employee_id": emp_id, "period": "2026-04", "amount_byn": "800.00"},
    )
    r1 = await api.post("/hr/payroll/pay", json={"employee_id": emp_id, "period": "2026-04"})
    assert r1.status_code == 200

    # второй pay того же периода — нет pending записи
    r2 = await api.post("/hr/payroll/pay", json={"employee_id": emp_id, "period": "2026-04"})
    assert r2.status_code == 404


async def test_amount_byn_is_str_not_float(api, session):
    """amount_byn в payload события — всегда str, никогда float."""
    emp_id = await _make_employee(api)

    await api.post(
        "/hr/payroll/accrue",
        json={"employee_id": emp_id, "period": "2026-03", "amount_byn": "999.99"},
    )
    await api.post("/hr/payroll/pay", json={"employee_id": emp_id, "period": "2026-03"})

    events = (await session.execute(select(OutboxEvent))).scalars().all()
    for evt in events:
        if evt.event_type in ("hr.payroll.accrued", "hr.payroll.paid"):
            assert isinstance(evt.payload["amount_byn"], str), (
                f"{evt.event_type}: amount_byn должен быть str, получен {type(evt.payload['amount_byn'])}"
            )
            # убедимся что это не float-repr (без научной нотации)
            assert "e" not in evt.payload["amount_byn"].lower()


async def test_accrue_unknown_employee_404(api):
    """Начисление на несуществующего сотрудника → 404."""
    r = await api.post(
        "/hr/payroll/accrue",
        json={"employee_id": 999999, "period": "2026-06", "amount_byn": "100.00"},
    )
    assert r.status_code == 404
