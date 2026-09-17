from decimal import Decimal

import pytest
from fastapi import HTTPException

from modules.procurement import routes as procurement_routes
from modules.procurement.schemas import CostEstimateOut, CostEstimateRequest
from modules.production import routes as production_routes
from modules.production.models import ProductionNorm, ProductionWorker
from modules.production.schemas import NormCreate
from modules.wms import routes as wms_routes
from modules.wms.models import Location
from modules.wms.schemas import LocationUpdate, StockMovementCreate


class FakeScalars:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return FakeScalars(self.rows)


class FakeSession:
    def __init__(self, *, rows=(), by_id=None):
        self.rows = list(rows)
        self.by_id = by_id or {}
        self.added = []
        self.statements = []
        self.commits = 0
        self.refreshed = []

    async def execute(self, statement):
        self.statements.append(statement)
        return FakeResult(self.rows)

    def add(self, obj):
        self.added.append(obj)

    async def get(self, model, identifier):
        return self.by_id.get(identifier)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        self.refreshed.append(obj)


@pytest.mark.asyncio
async def test_wms_create_movement_builds_decimal_orm_row_and_commits():
    session = FakeSession()

    created = await wms_routes.create_movement(
        StockMovementCreate(
            sku_code="SKU-1",
            warehouse="Главный",
            kind="out",
            qty=2.5,
            reason="sale",
            location_id=7,
            batch_ref="B-1",
            doc_ref="DOC-1",
            note="Проверка",
        ),
        session,
    )

    assert created is session.added[0]
    assert (
        created.sku_code,
        created.warehouse,
        created.kind,
        created.qty,
        created.reason,
        created.location_id,
        created.batch_ref,
        created.doc_ref,
        created.note,
    ) == ("SKU-1", "Главный", "out", Decimal("2.5"), "sale", 7, "B-1", "DOC-1", "Проверка")
    assert session.commits == 1
    assert session.refreshed == [created]


@pytest.mark.asyncio
async def test_wms_update_location_mutates_selected_fields_and_raises_for_missing():
    location = Location(id=4, warehouse="Главный", zone="A", code="A-01", title="Старая", is_active=True)
    session = FakeSession(by_id={4: location})

    updated = await wms_routes.update_location(4, LocationUpdate(title="Новая", is_active=False), session)

    assert updated is location
    assert (location.title, location.is_active, session.commits, session.refreshed) == (
        "Новая",
        False,
        1,
        [location],
    )

    with pytest.raises(HTTPException, match="Ячейка не найдена") as exc:
        await wms_routes.update_location(404, LocationUpdate(title="Нет"), FakeSession())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_procurement_cost_estimate_returns_validated_landed_cost_dto():
    raw = await procurement_routes.cost_estimate(
        CostEstimateRequest.model_validate(
            {
                "lines": [
                    {
                        "sku_code": "BAT-1",
                        "path": "usd",
                        "price": 10,
                        "qty": 2,
                        "weight": 1,
                        "duty_pct": 10,
                        "util": 3,
                    }
                ],
                "rates": {
                    "usd_byn": 3,
                    "commission_pct": 5,
                    "insurance_pct": 2,
                    "freight_usd_per_kg": 1,
                    "fx_buffer_pct": 10,
                },
            }
        )
    )

    result = CostEstimateOut.model_validate(raw)
    assert result.model_dump() == {
        "lines": [
            {
                "sku_code": "BAT-1",
                "goods_byn": 60.0,
                "commission_byn": 3.0,
                "insurance_byn": 1.2,
                "freight_byn": 6.0,
                "duty_byn": 6.6,
                "util_byn": 3.0,
                "unit_landed_cost_byn": 45.24,
            }
        ],
        "total_landed_byn": 90.48,
    }


@pytest.mark.asyncio
async def test_production_create_norm_sets_pending_status_and_persists_model():
    session = FakeSession()

    created = await production_routes.create_norm(
        NormCreate(title="Сборка", kind="operation", nh=1.75, note="Линия 1"), session
    )

    assert created is session.added[0]
    assert (created.title, created.kind, created.nh, created.status, created.note) == (
        "Сборка",
        "operation",
        1.75,
        "pending",
        "Линия 1",
    )
    assert session.commits == 1
    assert session.refreshed == [created]


@pytest.mark.asyncio
async def test_production_approve_norm_rejects_zero_hours_without_mutation():
    norm = ProductionNorm(id=6, title="Пустая", kind="product", nh=0, status="none", note="")
    session = FakeSession(by_id={6: norm})

    with pytest.raises(HTTPException, match="Нельзя утвердить норму") as exc:
        await production_routes.approve_norm(6, session)

    assert exc.value.status_code == 409
    assert (norm.status, session.commits, session.refreshed) == ("none", 0, [])


@pytest.mark.asyncio
async def test_production_payroll_returns_sorted_real_dto_with_totals():
    session = FakeSession(
        rows=[
            ProductionWorker(id=1, name="Иван", salary=2200, days_worked=11, nh_output=10),
            ProductionWorker(id=2, name="Анна", salary=2200, days_worked=22, nh_output=20),
        ]
    )

    result = await production_routes.payroll(session)

    assert result.model_dump() == {
        "rows": [
            {
                "id": 2,
                "name": "Анна",
                "nh_output": 20.0,
                "base": 2200.0,
                "premium": 125.0,
                "total": 2325.0,
                "contribution": 500.0,
            },
            {
                "id": 1,
                "name": "Иван",
                "nh_output": 10.0,
                "base": 1100.0,
                "premium": 62.5,
                "total": 1162.5,
                "contribution": 250.0,
            },
        ],
        "total_nh": 30.0,
        "total_base": 3300.0,
        "total_premium": 187.5,
        "total_payroll": 3487.5,
    }
    assert len(session.statements) == 1
