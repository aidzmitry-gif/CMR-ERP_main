from copy import deepcopy
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from core.services.auth import CurrentUser
from modules.accounting.gateway import AccountingService
from modules.sales.reservation_source import SalesReservationSource
from modules.wms.invoice_reservations import InvoiceReservation, ReserveInput, reserve
from modules.wms.models import ReservationVersion, StockMovement
from modules.wms.reservation_gateway import WmsReservationService
from tests.reservation_source import invoice


async def setup(api, session, *, physical="10"):
    api.headers["X-User"] = "allocator"
    response = await api.post("/accounting/organizations", json={"name": "Allocation test", "unp": "999999978"})
    assert response.status_code == 201, response.text
    org = response.json()["id"]
    await invoice(session, 1, [{"sku_code": "A", "qty": "2"}, {"sku_code": "A", "qty": "3"}], org)
    session.add(StockMovement(organization_id=org, sku_code="A", warehouse="W", kind="in", qty=physical, reason="receipt"))
    await session.commit()
    actor = await AccountingService().source_member(session, org, CurrentUser("allocator", ["director"]))
    facts = await SalesReservationSource().invoice_reservation(session, 1)
    data = ReserveInput(allocations=[{"line_no": 1, "warehouse": "W", "qty": "2"},
                                    {"line_no": 2, "warehouse": "W", "qty": "3"}],
                        journal_complete=True, evidence="Synthetic complete journal")
    return org, facts, data, actor


async def test_addressed_allocation_preserves_lines_and_replays_without_stock_movement(api, session):
    org, facts, data, actor = await setup(api, session)
    gateway = WmsReservationService()
    result = await gateway.reserve_invoice(session, org, facts, data.model_dump(), actor)
    assert (await gateway.reserve_invoice(session, org, facts, data.model_dump(), actor)) == result
    await session.commit()
    rows = (await session.scalars(select(ReservationVersion).order_by(ReservationVersion.id))).all()
    assert len(rows) == 2 and [row.qty for row in rows] == [Decimal("2"), Decimal("3")]
    assert rows[0].source != rows[1].source
    assert all(row.organization_id == org for row in rows)
    movements = (await session.scalars(select(StockMovement))).all()
    assert len(movements) == 1 and movements[0].qty == 10
    assert await session.scalar(select(InvoiceReservation.document_id)) == 1


async def test_invoice_reservation_facade_keeps_transaction_with_caller(api, session):
    org, facts, data, actor = await setup(api, session)
    await WmsReservationService().reserve_invoice(session, org, facts, data.model_dump(), actor)
    assert await session.scalar(select(InvoiceReservation.document_id)) == 1
    await session.rollback()
    assert await session.scalar(select(InvoiceReservation.document_id)) is None
    assert await session.scalar(select(ReservationVersion.id)) is None
    assert len((await session.scalars(select(StockMovement))).all()) == 1


async def test_invoice_availability_uses_current_owned_reserves_and_distinguishes_unknown(api, session):
    org, facts, data, actor = await setup(api, session)
    gateway = WmsReservationService()
    for version, qty in [(1, "99"), (2, "3")]:
        session.add(ReservationVersion(organization_id=org, source="manual-U", version=version,
            sku_code="A", warehouse="U", qty=qty, evidence="Synthetic", actor=actor))
    session.add(StockMovement(organization_id=org + 900, sku_code="A", warehouse="FOREIGN",
                             kind="in", qty="999", reason="receipt"))
    for kind in ("in", "out"):
        session.add(StockMovement(organization_id=org, sku_code="A", warehouse="ZERO", kind=kind,
                                 qty="1", reason="receipt" if kind == "in" else "shipment"))
    await session.flush()
    first = await gateway.invoice_availability(session, org, ["A", "UNKNOWN"])
    rows = {row["warehouse"]: row for row in first["rows"]}
    assert set(rows) == {"W", "U", "ZERO"}
    assert rows["W"]["free"] == "10.00"
    assert rows["U"]["reserved"] == "3.00" and rows["U"]["physical"] is None and rows["U"]["free"] is None
    assert rows["ZERO"]["physical"] == rows["ZERO"]["free"] == "0.00"
    assert first["basis_by_warehouse"]["U"] == {"version": None, "cutoff": None}
    assert len(first["basis_by_warehouse"]["W"]["version"]) == 64
    await gateway.reserve_invoice(session, org, facts, data.model_dump(), actor)
    current = await gateway.invoice_availability(session, org, ["A"])
    row = next(row for row in current["rows"] if row["warehouse"] == "W")
    assert row["physical"] == "10.00" and row["reserved"] == row["free"] == "5.00"


@pytest.mark.parametrize("quantity", [Decimal("NaN"), Decimal("Infinity"), Decimal("-2"), Decimal("0.001"), Decimal("1000000000000")])
async def test_availability_rejects_corrupt_stored_reserve_instead_of_inflating_free(quantity):
    from types import SimpleNamespace

    from modules.wms.invoice_reservations import invoice_availability

    class CorruptSnapshot:
        def in_transaction(self):
            return True

        async def scalars(self, statement):
            # First query is current reserved rows, second is warehouse names.
            if "reservation_version" in str(statement):
                return SimpleNamespace(all=lambda: [SimpleNamespace(warehouse="W", sku_code="A", qty=quantity)])
            return SimpleNamespace(all=lambda: ["W"])

    with pytest.raises(HTTPException, match="Stored reservation quantity") as error:
        await invoice_availability(CorruptSnapshot(), 1, ["A"])
    assert error.value.status_code == 409


@pytest.mark.parametrize("change", ["line_quantity", "wrong_line", "duplicate", "no_confirmation", "foreign_org", "short_stock"])
async def test_allocation_rejection_leaves_no_reservation(api, session, change):
    org, facts, data, actor = await setup(api, session, physical="4" if change == "short_stock" else "10")
    values = data.model_dump()
    if change == "line_quantity":
        values["allocations"][0]["qty"] = "3"
        values["allocations"][1]["qty"] = "2"  # Same SKU total cannot hide wrong original lines.
    elif change == "wrong_line":
        values["allocations"][0]["line_no"] = 99
    elif change == "duplicate":
        values["allocations"].append(values["allocations"][0])
    elif change == "no_confirmation":
        values["journal_complete"] = False
    elif change == "foreign_org":
        org += 1
    with pytest.raises(HTTPException):
        await reserve(session, org, facts, ReserveInput.model_validate(values), actor)
    assert await session.scalar(select(InvoiceReservation.document_id)) is None
    assert await session.scalar(select(ReservationVersion.id)) is None


async def test_current_manual_reservations_reduce_available_stock(api, session):
    org, facts, data, actor = await setup(api, session)
    for version, qty in [(1, "1"), (2, "6")]:
        session.add(ReservationVersion(organization_id=org, source="manual", version=version,
                                      sku_code="A", warehouse="W", qty=qty, evidence="Synthetic", actor=actor))
    await session.flush()
    with pytest.raises(HTTPException, match="Insufficient"):
        await reserve(session, org, facts, data, actor)
    assert await session.scalar(select(InvoiceReservation.document_id)) is None


async def test_manual_endpoint_cannot_overwrite_invoice_reservation_namespace(api, session):
    org, _, _, _ = await setup(api, session)
    response = await api.post("/wms/reservations", json={"organization_id": org, "source": "invoice:1:1:test",
        "version": 1, "sku_code": "A", "warehouse": "W", "qty": "2", "evidence": "Synthetic"})
    assert response.status_code == 422, response.text
    assert await session.scalar(select(ReservationVersion.id)) is None


async def erp_delivery_fixture(api, session):
    org, facts, data, actor = await setup(api, session)
    stored = await reserve(session, org, facts, data, actor)
    # The Sales facade owns receipt qualification. This fixture tests the WMS
    # boundary against actual persisted WMS allocations, not Sales issuance.
    anchor = {"document_id": 1, "request_key": "synthetic", "request_hash": "a" * 64,
              "snapshot_digest": "b" * 64}
    source = {**facts, "issuance_receipt": anchor, "reservation_digest": stored["digest"]}
    payload = {"schema_version": 1, "issuance_mode": "erp_issuance_v1",
               "document_id": 1, "deal_id": facts["deal_id"], "organization_id": org,
               "document_version": facts["version"], "content_sha256": facts["content_sha256"],
               "reservation_digest": stored["digest"], "issuance_receipt": deepcopy(anchor),
               "items": deepcopy(stored["snapshot"]["allocations"])}
    return source, payload


async def test_erp_delivery_validates_persisted_matrix_without_reserving_again(api, session):
    from modules.wms.events import _erp_reservation_items
    from modules.wms.models import Task
    from modules.wms.reservation_events import apply

    source, payload = await erp_delivery_fixture(api, session)
    for _ in range(2):
        items = await _erp_reservation_items(session, payload, source)
        await apply(session, 1, items, organization_id=source["organization_id"], release=False)
    assert len((await session.scalars(select(ReservationVersion))).all()) == 2
    assert len((await session.scalars(select(Task))).all()) == 2
    assert len((await session.scalars(select(StockMovement))).all()) == 1


@pytest.mark.parametrize("change", ["warehouse", "missing_warehouse", "line", "source", "quantity_swap",
    "duplicate", "float", "digest", "anchor", "boolean_anchor", "version", "organization", "missing_mode", "unqualified"])
async def test_erp_delivery_rejects_forged_identity_before_pick_effects(api, session, change):
    from modules.wms.events import _erp_reservation_items
    from modules.wms.models import Task

    source, payload = await erp_delivery_fixture(api, session)
    if change == "warehouse":
        payload["items"][0]["warehouse"] = "Foreign"
    elif change == "missing_warehouse":
        del payload["items"][0]["warehouse"]
    elif change == "line":
        payload["items"][0]["line_no"] = True
    elif change == "source":
        payload["items"][0]["source"] = "other"
    elif change == "quantity_swap":
        payload["items"][0]["qty"], payload["items"][1]["qty"] = "3.00", "2.00"
    elif change == "duplicate":
        payload["items"][1] = deepcopy(payload["items"][0])
    elif change == "float":
        payload["items"][0]["qty"] = 2.0
    elif change == "digest":
        payload["reservation_digest"] = "c" * 64
    elif change == "anchor":
        payload["issuance_receipt"]["request_key"] = "other"
    elif change == "boolean_anchor":
        payload["issuance_receipt"]["document_id"] = True
    elif change == "version":
        payload["document_version"] += 1
    elif change == "organization":
        payload["organization_id"] += 1
    elif change == "missing_mode":
        del payload["issuance_mode"]
    else:
        del source["issuance_receipt"]
    with pytest.raises(ValueError):
        await _erp_reservation_items(session, payload, source)
    assert await session.scalar(select(Task.id)) is None
