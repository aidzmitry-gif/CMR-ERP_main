"""Тесты payroll-эндпоинтов HR: начисление + выплата + события outbox."""
from decimal import localcontext

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from core.domain.models import OutboxEvent
from core.runtime.deps import get_core, get_session
from modules.hr.models import PayrollEntry
from modules.hr.payroll_preview import calculate_payroll_preview
from modules.hr.routes import router
from modules.hr.schemas import PayrollPreviewIn


def _policy_month(period: str, **updates):
    data = {
        "period": period, "monthly_norm_hours": "168", "worked_hours": "168",
        "worked_days": 21, "source_ref": "Табель 2026-10 и документы отгрузки",
        "advance_byn": "100", "tax_deduction_byn": "0", "other_withholding_byn": "0",
        "opening_carry_byn": "0",
        "shipment_revenue_byn": "0", "shipment_cost_byn": "0",
        "return_revenue_byn": "0", "return_cost_byn": "0",
        "confirmed_penalties_byn": "0", "norm_hours": "0",
    }
    return {**data, **updates}


def _policy_employee(employee_id: int, role: str, months, **updates):
    return {
        "employee_id": employee_id, "employee_name": f"Сотрудник {employee_id}",
        "role": role, "months": months, **updates,
    }


async def test_policy_preview_two_month_carry_and_role_oracle(preview_api):
    seller = _policy_employee(1, "seller", [
        _policy_month("2026-10", return_revenue_byn="1000", return_cost_byn="600",
                      confirmed_penalties_byn="100"),
        _policy_month("2026-11", monthly_norm_hours="160", worked_hours="160",
                      worked_days=20, shipment_revenue_byn="10000", shipment_cost_byn="6000",
                      opening_carry_byn="500"),
    ])
    assembler = _policy_employee(2, "assembler", [
        _policy_month("2026-10", worked_hours="84", worked_days=11, norm_hours="50"),
    ])
    senior = _policy_employee(3, "assemblerSenior", [
        _policy_month("2026-10", norm_hours="100"),
    ])
    salary = _policy_employee(4, "salary", [
        _policy_month("2026-10", worked_hours="84", worked_days=11),
    ], contractual_salary_byn="1300")
    response = await preview_api.post(
        "/hr/payroll/policy-preview", json={"employees": [seller, assembler, senior, salary]},
        headers={"X-User-Roles": "accountant"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "draft" and body["can_manual_adjust"] is False
    rows = body["rows"]
    assert all(row["status"] == "ready" for row in rows)
    assert rows[0]["seller_gross_profit_byn"] == "-500.00"
    assert rows[0]["bonus_byn"] == "0.00"
    assert rows[0]["seller_closing_carry_byn"] == "500.00"
    assert rows[1]["seller_opening_carry_byn"] == "500.00"
    assert rows[1]["bonus_byn"] == "175.00"
    assert rows[2]["salary_byn"] == "500.00"
    assert rows[2]["bonus_byn"] == "340.00"
    assert rows[2]["worked_days"] == 11
    assert rows[2]["gross_byn"] == "840.00"
    assert rows[2]["income_tax_byn"] == "109.20"
    assert rows[2]["employee_fszn_byn"] == "8.40"
    assert rows[2]["net_byn"] == "722.40"
    assert rows[2]["payout_byn"] == "622.40"
    assert rows[2]["employer_fszn_byn"] == "285.60"
    assert rows[2]["belgos_byn"] == "4.37"
    assert rows[3]["salary_byn"] == "1200.00" and rows[3]["bonus_byn"] == "700.00"
    assert rows[4]["salary_byn"] == "650.00" and rows[4]["bonus_byn"] == "0.00"
    assert "id" not in body


async def test_policy_preview_unknowns_and_no_db(preview_api):
    response = await preview_api.post("/hr/payroll/policy-preview", json={"employees": [
        _policy_employee(1, "seller", [
            _policy_month("2026-10", shipment_cost_byn=None),
            _policy_month("2026-11", monthly_norm_hours="160", worked_hours="160", worked_days=20),
        ]),
        _policy_employee(2, "assembler", [_policy_month("2026-10", norm_hours=None)]),
        _policy_employee(3, "salary", [_policy_month("2026-10", worked_days=None)],
                         contractual_salary_byn="1300"),
    ]}, headers={"X-User-Roles": "accountant"})
    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    assert all(row["status"] == "unknown" and row["net_byn"] is None for row in rows)
    assert "себестоимость" in rows[0]["error"]
    assert "перенос неизвестен" in rows[1]["error"]
    assert "нормо-часы" in rows[2]["error"]
    assert "дни неизвестны" in rows[3]["error"]


@pytest.mark.parametrize("role", [None, "accountant", "admin", "commercial"])
async def test_policy_manual_rejects_every_non_director(preview_api, role):
    headers = {"X-User-Roles": role} if role else {}
    response = await preview_api.post("/hr/payroll/policy-preview", json={"employees": [
        _policy_employee(1, "assembler", [_policy_month(
            "2026-10", worked_hours="84", worked_days=11, norm_hours="50",
            mode="manual", target_net_byn="800", manual_reason="Отдельное соглашение",
            manual_document_ref="Приказ № 18",
        )]),
    ]}, headers=headers)
    assert response.status_code == 403


async def test_policy_manual_director_uses_server_role_and_requires_document(preview_api):
    employee = _policy_employee(1, "assembler", [_policy_month(
        "2026-10", worked_hours="84", worked_days=11, norm_hours="50",
        mode="manual", target_net_byn="800", manual_reason="Отдельное соглашение",
        manual_document_ref="Приказ № 18",
    )])
    response = await preview_api.post("/hr/payroll/policy-preview", json={"employees": [employee]},
                                      headers={"X-User-Roles": "director"})
    assert response.status_code == 200, response.text
    row = response.json()["rows"][0]
    assert response.json()["can_manual_adjust"] is True
    assert row["status"] == "ready" and row["manual"] is True
    assert row["policy_net_byn"] == "722.40" and row["net_byn"] == "800.00"
    assert row["payout_byn"] == "700.00"
    assert row["gross_byn"] == "930.23" and row["bonus_byn"] == "430.23"
    employee["months"][0]["manual_document_ref"] = ""
    invalid = await preview_api.post("/hr/payroll/policy-preview", json={"employees": [employee]},
                                     headers={"X-User-Roles": "director"})
    assert invalid.status_code == 200
    assert invalid.json()["rows"][0]["status"] == "unknown"


async def test_policy_manual_can_preview_without_unverified_bonus_but_not_invent_carry(preview_api):
    employee = _policy_employee(1, "seller", [
        _policy_month("2026-10", shipment_cost_byn=None, mode="manual",
                      target_net_byn="1300", manual_reason="Отдельное соглашение",
                      manual_document_ref="Приказ № 19"),
        _policy_month("2026-11", monthly_norm_hours="160", worked_hours="160",
                      worked_days=20, shipment_revenue_byn="4000", shipment_cost_byn="0"),
    ])
    response = await preview_api.post("/hr/payroll/policy-preview", json={"employees": [employee]},
                                      headers={"X-User-Roles": "director"})
    assert response.status_code == 200, response.text
    first, second = response.json()["rows"]
    assert first["status"] == "ready" and first["manual"] is True
    assert first["net_byn"] == "1300.00" and first["policy_net_byn"] is None
    assert first["seller_closing_carry_byn"] is None
    assert second["status"] == "unknown" and "перенос неизвестен" in second["error"]


async def test_policy_manual_rejects_invalid_combined_rates_before_inverse_search(preview_api):
    employee = _policy_employee(1, "assembler", [_policy_month(
        "2026-10", norm_hours=None, mode="manual", target_net_byn="0.01",
        income_tax_rate_pct="50", employee_fszn_rate_pct="50",
        manual_reason="Отдельное соглашение", manual_document_ref="Приказ № 20",
    )])
    response = await preview_api.post("/hr/payroll/policy-preview", json={"employees": [employee]},
                                      headers={"X-User-Roles": "director"})
    assert response.status_code == 422 or (
        response.status_code == 200 and response.json()["rows"][0]["status"] == "unknown"
    )


async def test_policy_rejects_duplicate_employee_objects_even_across_months(preview_api):
    october = _policy_employee(1, "seller", [_policy_month("2026-10", return_revenue_byn="1000",
                                                          return_cost_byn="600", confirmed_penalties_byn="100")])
    november = _policy_employee(1, "seller", [_policy_month("2026-11", shipment_revenue_byn="4000",
                                                           opening_carry_byn="0")])
    response = await preview_api.post("/hr/payroll/policy-preview", json={"employees": [october, november]},
                                      headers={"X-User-Roles": "accountant"})
    assert response.status_code == 422
    assert "одной записью" in response.json()["detail"]


async def test_policy_manual_advance_checked_against_selected_net_not_policy_net(preview_api):
    employee = _policy_employee(1, "assembler", [_policy_month(
        "2026-10", worked_hours="84", worked_days=11, norm_hours="50",
        mode="manual", target_net_byn="800", advance_byn="750",
        manual_reason="Отдельное соглашение", manual_document_ref="Приказ № 21",
    )])
    response = await preview_api.post("/hr/payroll/policy-preview", json={"employees": [employee]},
                                      headers={"X-User-Roles": "director"})
    assert response.status_code == 200, response.text
    row = response.json()["rows"][0]
    assert row["status"] == "ready"
    assert row["policy_net_byn"] == "722.40" and row["net_byn"] == "800.00"
    assert row["payout_byn"] == "50.00"

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


async def test_pay_requires_exact_entry_when_employee_has_two_accruals(api, session):
    emp_id = await _make_employee(api)
    first = await api.post(
        "/hr/payroll/accrue",
        json={"employee_id": emp_id, "period": "2026-04", "amount_byn": "100.00"},
    )
    second = await api.post(
        "/hr/payroll/accrue",
        json={"employee_id": emp_id, "period": "2026-04", "amount_byn": "200.00"},
    )
    assert first.status_code == second.status_code == 201

    ambiguous = await api.post(
        "/hr/payroll/pay", json={"employee_id": emp_id, "period": "2026-04"},
    )
    assert ambiguous.status_code == 409
    assert {row["status"] for row in (await api.get("/hr/payroll")).json()} == {"pending"}

    selected_id = second.json()["id"]
    paid = await api.post(
        "/hr/payroll/pay",
        json={"employee_id": emp_id, "period": "2026-04", "entry_id": selected_id},
    )
    assert paid.status_code == 200
    assert paid.json()["id"] == selected_id
    assert (await api.get(f"/hr/payroll/{first.json()['id']}")).json()["status"] == "pending"
    events = (await session.execute(select(OutboxEvent))).scalars().all()
    paid_events = [event for event in events if event.event_type == "hr.payroll.paid"]
    assert len(paid_events) == 1
    assert paid_events[0].payload["entity_ref"] == f"payroll:{selected_id}"


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


@pytest.mark.parametrize(
    ("period", "amount"),
    [
        ("2026-13", "100.00"),
        ("2026-06", "NaN"),
        ("2026-06", "-1.00"),
        ("2026-06", "0"),
        ("2026-06", "1.001"),
    ],
)
async def test_invalid_accrual_does_not_create_entry_or_event(api, session, period, amount):
    emp_id = await _make_employee(api)
    response = await api.post(
        "/hr/payroll/accrue",
        json={"employee_id": emp_id, "period": period, "amount_byn": amount},
    )
    assert response.status_code == 422
    assert (await api.get("/hr/payroll")).json() == []
    events = (await session.execute(select(OutboxEvent))).scalars().all()
    assert not any(event.event_type == "hr.payroll.accrued" for event in events)


async def test_accrual_amount_is_canonical_decimal_string(api):
    emp_id = await _make_employee(api)
    response = await api.post(
        "/hr/payroll/accrue",
        json={"employee_id": emp_id, "period": "2026-06", "amount_byn": "12.3"},
    )
    assert response.status_code == 201
    assert response.json()["amount_byn"] == "12.30"


async def test_payroll_summary_empty(api):
    """GET /hr/payroll/summary → 200 + пустой список."""
    r = await api.get("/hr/payroll/summary")
    assert r.status_code == 200
    assert r.json() == []


async def test_payroll_summary_aggregates(api):
    """Два начисления за один период → count=2, total_byn = сумма."""
    emp1 = await _make_employee(api)
    emp2_r = await api.post("/hr/employees", json={"full_name": "Сидоров Сидор"})
    emp2 = emp2_r.json()["id"]
    await api.post("/hr/payroll/accrue", json={"employee_id": emp1, "period": "2026-10", "amount_byn": "1000.00"})
    await api.post("/hr/payroll/accrue", json={"employee_id": emp2, "period": "2026-10", "amount_byn": "2000.00"})
    r = await api.get("/hr/payroll/summary")
    assert r.status_code == 200
    periods = {s["period"]: s for s in r.json()}
    assert "2026-10" in periods
    s = periods["2026-10"]
    assert s["count"] == 2
    from decimal import Decimal
    assert Decimal(s["total_byn"]) == Decimal("3000.00")
    assert s["pending_count"] == 2


async def test_payroll_summary_pending_decreases(api):
    """После pay pending_count уменьшается."""
    emp_id = await _make_employee(api)
    await api.post("/hr/payroll/accrue", json={"employee_id": emp_id, "period": "2026-11", "amount_byn": "500.00"})
    await api.post("/hr/payroll/pay", json={"employee_id": emp_id, "period": "2026-11"})
    r = await api.get("/hr/payroll/summary")
    assert r.status_code == 200
    periods = {s["period"]: s for s in r.json()}
    assert "2026-11" in periods
    assert periods["2026-11"]["pending_count"] == 0


# Preview uses a standalone HR router with fatal DB/Core dependencies. It must
# work even without app.state.core, employee records, or a database session.
@pytest.fixture
async def preview_api():
    app = FastAPI()
    app.include_router(router, prefix="/hr")

    def forbidden_dependency():
        raise AssertionError("Payroll preview must not request DB or Core")

    app.dependency_overrides[get_session] = forbidden_dependency
    app.dependency_overrides[get_core] = forbidden_dependency
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _preview_inputs(**updates):
    return {
        "target_net_byn": "2000.00",
        "advance_byn": "250.00",
        "tax_deduction_byn": "0.00",
        "other_withholding_byn": "0.00",
        "income_tax_rate_pct": "13",
        "employee_fszn_rate_pct": "1",
        "employer_fszn_rate_pct": "34",
        **updates,
    }


async def test_preview_exact_example_without_db_or_core(preview_api):
    response = await preview_api.post("/hr/payroll/preview", json=_preview_inputs())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "draft"
    assert body["currency"] == "BYN"
    assert body["inputs"] == {**_preview_inputs(), "belgos_rate_pct": None}
    assert {key: body[key] for key in (
        "gross_byn", "taxable_base_byn", "income_tax_byn", "employee_fszn_byn",
        "employer_fszn_byn", "net_byn", "payout_byn", "belgos_byn",
    )} == {
        "gross_byn": "2325.59",
        "taxable_base_byn": "2325.59",
        "income_tax_byn": "302.33",
        "employee_fszn_byn": "23.26",
        "employer_fszn_byn": "790.70",
        "net_byn": "2000.00",
        "payout_byn": "1750.00",
        "belgos_byn": None,
    }
    assert any("Белгосстраха" in warning for warning in body["warnings"])
    assert any("не проверены" in warning for warning in body["warnings"])
    assert any("ROUND_HALF_UP" in assumption for assumption in body["assumptions"])
    assert "id" not in body


def test_preview_deduction_withholding_and_explicit_belgos():
    result = calculate_payroll_preview(PayrollPreviewIn(**_preview_inputs(
        tax_deduction_byn="100.00", other_withholding_byn="50.00", belgos_rate_pct="0.60",
    )))
    assert result.gross_byn == "2368.61"
    assert result.taxable_base_byn == "2268.61"
    assert result.income_tax_byn == "294.92"
    assert result.employee_fszn_byn == "23.69"
    assert result.employer_fszn_byn == "805.33"
    assert result.belgos_byn == "14.21"
    assert result.net_byn == "2000.00"
    assert result.payout_byn == "1750.00"
    assert len(result.warnings) == 1  # Legal assumptions remain unverified.


def test_preview_advance_and_employer_contributions_do_not_reduce_monthly_net():
    baseline = calculate_payroll_preview(PayrollPreviewIn(**_preview_inputs()))
    changed = calculate_payroll_preview(PayrollPreviewIn(**_preview_inputs(
        advance_byn="2000.00", employer_fszn_rate_pct="100", belgos_rate_pct="100",
    )))
    for name in ("gross_byn", "taxable_base_byn", "income_tax_byn", "employee_fszn_byn", "net_byn"):
        assert getattr(changed, name) == getattr(baseline, name)
    assert changed.payout_byn == "0.00"
    assert changed.employer_fszn_byn == changed.belgos_byn == changed.gross_byn


@pytest.mark.parametrize(("target", "deduction", "tax_rate", "worker_rate", "gross", "tax"), [
    ("0.00", "0.00", "13", "1", "0.00", "0.00"),
    ("100.00", "500.00", "13", "1", "101.01", "0.00"),
    # HALF_UP and the minimal gross among multiple exact solutions.
    ("0.01", "0.00", "50", "0", "0.02", "0.01"),
    # Rounded net drops from .43 at gross .49 to .42 at gross .50.
    ("0.43", "0.00", "13", "1", "0.49", "0.06"),
    ("0.42", "0.00", "13", "1", "0.48", "0.06"),
    ("0.01", "0.00", "99.99", "0", "50.01", "50.00"),
    ("999999999.99", "0.00", "0", "0", "999999999.99", "0.00"),
])
def test_preview_rounding_and_supported_boundaries(target, deduction, tax_rate, worker_rate, gross, tax):
    payload = PayrollPreviewIn(**_preview_inputs(
        target_net_byn=target, advance_byn="0.00", tax_deduction_byn=deduction,
        income_tax_rate_pct=tax_rate, employee_fszn_rate_pct=worker_rate,
        belgos_rate_pct="0",
    ))
    with localcontext() as ctx:
        ctx.prec = 5  # Caller arithmetic precision must not affect the result.
        result = calculate_payroll_preview(payload)
    assert result.gross_byn == gross
    assert result.income_tax_byn == tax
    assert result.net_byn == result.payout_byn == target
    assert result.belgos_byn == "0.00"  # Explicit zero is distinct from unknown.


def _cents_string(cents):
    return f"{cents // 100}.{cents % 100:02d}"


@pytest.mark.parametrize(("tax_basis_points", "worker_basis_points"), [
    (1300, 100), (5000, 4999), (3750, 4230), (0, 0), (9900, 0),
])
@pytest.mark.parametrize("deduction_cents", [0, 7, 50])
@pytest.mark.parametrize("other_cents", [0, 9])
def test_preview_matches_independent_integer_oracle(tax_basis_points, worker_basis_points,
                                                     deduction_cents, other_cents):
    """Exhaustively enumerate small gross amounts using integer HALF_UP, not the helper."""
    first_gross = {}
    for gross_cents in range(301):
        worker = (gross_cents * worker_basis_points + 5000) // 10000
        tax = (max(gross_cents - deduction_cents, 0) * tax_basis_points + 5000) // 10000
        net = gross_cents - worker - tax - other_cents
        if net >= 0:
            first_gross.setdefault(net, gross_cents)
    for target, expected_gross in first_gross.items():
        result = calculate_payroll_preview(PayrollPreviewIn(**_preview_inputs(
            target_net_byn=_cents_string(target), advance_byn="0.00",
            tax_deduction_byn=_cents_string(deduction_cents),
            other_withholding_byn=_cents_string(other_cents),
            income_tax_rate_pct=_cents_string(tax_basis_points),
            employee_fszn_rate_pct=_cents_string(worker_basis_points),
        )))
        assert result.gross_byn == _cents_string(expected_gross)
        assert result.net_byn == _cents_string(target)


@pytest.mark.parametrize(("field", "value"), [
    ("target_net_byn", 2000), ("target_net_byn", 2000.0), ("target_net_byn", True),
    ("target_net_byn", "2000.001"), ("target_net_byn", "NaN"),
    ("target_net_byn", "Infinity"), ("target_net_byn", "2e3"),
    ("target_net_byn", "2000,00"), ("target_net_byn", " 2000.00"),
    ("target_net_byn", "2000.00\n"), ("target_net_byn", "+2000.00"),
    ("target_net_byn", "1000000000.00"), ("target_net_byn", "-1.00"),
    ("advance_byn", "-0.01"), ("advance_byn", "2000.01"),
    ("tax_deduction_byn", None), ("tax_deduction_byn", "-0.01"),
    ("other_withholding_byn", None), ("other_withholding_byn", "-0.01"),
    ("income_tax_rate_pct", "13.001"), ("income_tax_rate_pct", "99"),
    ("income_tax_rate_pct", "100.01"), ("income_tax_rate_pct", "NaN"),
    ("employee_fszn_rate_pct", "87.01"), ("employee_fszn_rate_pct", "-1"),
    ("employer_fszn_rate_pct", "100.01"), ("employer_fszn_rate_pct", 34),
    ("belgos_rate_pct", "-0.60"), ("belgos_rate_pct", "100.01"),
    ("unsupported_legal_status", "resident"),
])
async def test_preview_rejects_invalid_inputs_without_dependencies(preview_api, field, value):
    response = await preview_api.post("/hr/payroll/preview", json=_preview_inputs(**{field: value}))
    assert response.status_code == 422


@pytest.mark.parametrize("field", list(_preview_inputs()))
async def test_preview_requires_explicit_inputs(preview_api, field):
    payload = _preview_inputs()
    del payload[field]
    response = await preview_api.post("/hr/payroll/preview", json=payload)
    assert response.status_code == 422


async def test_preview_rejects_impossible_amount_without_dependencies(preview_api):
    response = await preview_api.post("/hr/payroll/preview", json=_preview_inputs(
        target_net_byn="999999999.99",
    ))
    assert response.status_code == 422
    assert "999999999.99 BYN" in response.json()["detail"]


async def test_preview_preserves_existing_payroll_and_outbox(api, session):
    employee_id = await _make_employee(api)
    accrued = await api.post("/hr/payroll/accrue", json={
        "employee_id": employee_id, "period": "2026-09", "amount_byn": "900.00",
    })
    assert accrued.status_code == 201

    async def snapshot():
        return [
            (await session.execute(select(model.__table__))).mappings().all()
            for model in (PayrollEntry, OutboxEvent)
        ]

    before = await snapshot()
    for payload, expected_status in [
        (_preview_inputs(), 200),
        (_preview_inputs(belgos_rate_pct="0.60"), 200),
        (_preview_inputs(other_withholding_byn=None), 422),
        (_preview_inputs(target_net_byn="999999999.99"), 422),
    ]:
        response = await api.post("/hr/payroll/preview", json=payload)
        assert response.status_code == expected_status
    assert await snapshot() == before
