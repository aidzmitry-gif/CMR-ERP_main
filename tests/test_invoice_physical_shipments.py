from copy import deepcopy
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update

from modules.accounting.models import AccessGrant, Period
from modules.sales import deal_loss  # noqa: F401 -- register guard tables before fixture create_all
from modules.wms.invoice_reservations import invoice_availability, release_preview, reserve
from modules.wms.invoice_shipments import PhysicalShipmentAct, PhysicalShipmentLine
from modules.wms.models import ReservationVersion, StockMovement, Task
from modules.wms.reservation_events import apply
from modules.wms.reservation_gateway import WmsReservationService
from tests.test_invoice_stock_allocation import setup


async def prepared(api, session):
    org, facts, data, actor = await setup(api, session)
    await reserve(session, org, facts, data, actor)
    await apply(session, 1, [("A", "W", Decimal("2")), ("A", "W", Decimal("3"))], organization_id=org, release=False)
    await session.commit()
    return org, facts


def endpoint(org):
    return f"/wms/organizations/{org}/invoices/1/physical-shipments"


async def request(api, org, facts, lines=None):
    identity = {"expected_version": facts["version"], "expected_content_sha256": facts["content_sha256"]}
    response = await api.post(endpoint(org) + "/preview", json=identity)
    assert response.status_code == 200, response.text
    basis = response.json()
    return {**identity, "source_key": str(uuid4()), "expected_reservation_digest": basis["reservation_digest"],
        "expected_remaining_digest": basis["remaining_digest"], "expected_physical_digest": basis["physical_digest"],
        "operation_date": date.today().isoformat(), "evidence": "Synthetic actual release by authorized operator",
        "lines": lines or [{"line_no": 1, "warehouse": "W", "qty": "1.00"}]}


async def test_accountant_source_opens_verified_internal_act_without_stock_changes(api, session, tmp_path):
    org, facts = await prepared(api, session)
    body = await request(api, org, facts)
    body["evidence"] = 'Учебная отгрузка <script>alert("x")</script>'
    created = await api.post(endpoint(org), json=body)
    assert created.status_code == 201, created.text
    count = await session.scalar(select(func.count()).select_from(StockMovement))
    url = f"/wms/organizations/{org}/physical-shipments/by-key/{body['source_key']}/document"
    response = await api.get(url)
    assert response.status_code == 200, response.text
    assert "Внутренний акт отгрузки" in response.text and "Не является ТН или ТТН" in response.text
    assert "&lt;script&gt;" in response.text and '<script>' not in response.text
    assert "1.00" in response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    artifact = tmp_path / "internal-shipment.html"
    artifact.write_text(response.text, encoding="utf-8")
    print(f"Internal act HTML: {artifact}")
    assert await session.scalar(select(func.count()).select_from(StockMovement)) == count
    assert (await api.get(url.replace(str(org) + "/physical", "999/physical"))).status_code in {403, 404}
    assert (await api.get(url.replace(body["source_key"], str(uuid4())))).status_code == 404
    # Existing act integrity validation must also protect this view.
    await session.execute(update(PhysicalShipmentAct).where(
        PhysicalShipmentAct.source_key == body["source_key"]).values(digest="0" * 64))
    await session.commit()
    assert (await api.get(url)).status_code == 409


async def test_wms_register_projection_keeps_internal_act_distinct_from_tn_ttn(api, session):
    from modules.wms.reservation_gateway import WmsReservationService

    org, facts = await prepared(api, session)
    body = await request(api, org, facts)
    created = await api.post(endpoint(org), json=body)
    assert created.status_code == 201, created.text
    projection = await WmsReservationService().invoice_shipments_register(session, org, [facts["document_id"]])
    assert projection["status"] == "internal_acts_only"
    assert projection["tn_ttn_status"] == "not_certified"
    assert projection["items"][0]["act_id"] == created.json()["act_id"]
    assert projection["items"][0]["status"] == "verified_internal_act"
    assert projection["items"][0]["tn_ttn_status"] == "not_certified"


async def test_accounting_tn_ttn_draft_is_source_bound_and_never_certified(api, session):
    org, facts = await prepared(api, session)
    body = await request(api, org, facts)
    created = await api.post(endpoint(org), json=body)
    assert created.status_code == 201, created.text
    url = f"/accounting/organizations/{org}/shipments/{body['source_key']}/tn-ttn-draft"
    draft = await api.get(url + "?kind=ttn")
    assert draft.status_code == 200, draft.text
    value = draft.json()
    assert value["status"] == "draft_required"
    assert value["document_kind"] == "ttn"
    assert value["document_label"] == "ТТН"
    assert value["statutory_certified"] is False and value["can_issue"] is False
    assert "vehicle_registration" in value["required_fields"]
    assert value["source"]["source_key"] == body["source_key"]
    assert len(value["draft_digest"]) == 64
    assert draft.headers["cache-control"] == "private, no-store"
    assert (await api.get(url + "?kind=bad")).status_code == 422


async def test_accountant_source_snapshot_is_verified_scoped_and_read_only(api, session):
    from modules.accounting.models import SourceControl

    org, facts = await prepared(api, session)
    body = await request(api, org, facts)
    created = await api.post(endpoint(org), json=body)
    assert created.status_code == 201, created.text
    expected = created.json()
    count = await session.scalar(select(func.count()).select_from(StockMovement))
    url = f"/wms/organizations/{org}/physical-shipments/by-key/{body['source_key']}"
    response = await api.get(url)
    assert response.status_code == 200, response.text
    assert response.json() == expected
    assert response.headers["cache-control"] == "private, no-store"
    assert await session.scalar(select(func.count()).select_from(StockMovement)) == count
    source = f"wms:physical-shipment:{org}:{body['source_key']}"
    control = await session.scalar(select(SourceControl).where(SourceControl.source == source))
    assert control is not None and control.entry_id is None
    assert (await api.get(url.replace(f"/{org}/physical", "/999/physical"))).status_code in {403, 404}
    assert (await api.get(url.replace(body["source_key"], str(uuid4())))).status_code == 404
    await session.execute(update(PhysicalShipmentAct).where(
        PhysicalShipmentAct.source_key == body["source_key"]).values(digest="0" * 64))
    await session.commit()
    assert (await api.get(url)).status_code == 409


async def test_whole_act_accounting_preview_uses_actual_act_and_keeps_it_pending(api, session):
    from modules.accounting import models, service
    from modules.accounting.schemas import PostingInput

    org, facts = await prepared(api, session)
    body = await request(api, org, facts, [{"line_no": 1, "warehouse": "W", "qty": "1.00"},
                                         {"line_no": 2, "warehouse": "W", "qty": "2.00"}])
    response = await api.post(endpoint(org), json=body)
    assert response.status_code == 201, response.text
    act = response.json()
    policy = models.Policy(organization_id=org, effective_from=date(2026, 1, 1), reference="Synthetic only",
        inventory_method="specific", allocation_basis="direct_cost", depreciation_method="straight_line",
        normative_reference="Synthetic", normative_verified=False, approved_by="allocator")
    session.add(policy)
    for code, category in [("41.2", "asset"), ("60", "liability"), ("62", "asset"),
                           ("90.1", "income"), ("90.2", "income"), ("68.2", "liability"), ("90.4", "expense")]:
        session.add(models.Account(organization_id=org, code=code, title=code, category=category,
            valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
            quantity_tracking=code == "41.2", cash=False, normative_ref="Synthetic"))
    await session.flush()
    policy_id = policy.id
    await service.post(session, org, PostingInput(source="Synthetic stock receipt", source_version=1,
        operation="manual", document_date=date.today(), operation_date=date.today(), posting_date=date.today(),
        policy_id=policy_id, rule_version="synthetic", explanation="Synthetic stock",
        lines=[{"account": "41.2", "side": "debit", "amount": "10.00", "quantity": "3",
                "dimensions": {"warehouse": "W", "sku": "A", "lot": "L"}},
               {"account": "60", "side": "credit", "amount": "10.00"}]), "allocator")
    await session.commit()
    data = {"expected_act_digest": act["digest"], "policy_id": policy_id, "document_date": date.today().isoformat(),
            "posting_date": date.today().isoformat(), "explanation": "Synthetic shipment sale",
            "recognition": "sale_on_shipment", "recognition_basis": "Synthetic decision", "unit_basis": "Same units verified",
            "cost_allocation": "cumulative_floor_last", "vat_rounding": "commercial_line_half_up",
            "allocations": [{"line_source": line["source"], "account": "41.2", "lot": "L", "quantity": line["qty"],
                             "expense_account": "90.4"} for line in act["snapshot"]["lines"]],
            "commercial_lines": [{"line_no": i, "net_amount": "20.00", "vat_rate": "20", "vat_basis": "Synthetic",
                                  "buyer_account": "62", "revenue_account": "90.1", "vat_revenue_account": "90.2", "vat_payable_account": "68.2",
                                  "buyer_dimensions": {"counterparty": "Buyer", "contract": "C", "settlement_document": "sales:document:1"}} for i in [1, 2]]}
    url = f"/wms/organizations/{org}/physical-shipments/by-key/{body['source_key']}/accounting-preview"
    response = await api.post(url, json=data)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["costs"][0]["issue_cost_byn"] == "10.00" and result["gross_byn"] == "48.00"
    assert result["confirmation_available"] is True
    assert result["posted"] is False
    assert await session.scalar(select(func.count()).select_from(models.Entry)) == 1
    assert await session.scalar(select(models.SourceControl.entry_id).where(models.SourceControl.source == result["source"])) is None
    changed = deepcopy(data)
    changed["allocations"].pop()
    assert (await api.post(url, json=changed)).status_code == 422
    await session.execute(update(AccessGrant).where(AccessGrant.organization_id == org).values(role="reader"))
    await session.commit()
    assert (await api.post(url, json=data)).status_code == 403


async def test_preview_exposes_addressed_duplicate_sku_lines_and_consumed_line(api, session):
    org, facts = await prepared(api, session)
    identity = {"expected_version": facts["version"], "expected_content_sha256": facts["content_sha256"]}
    before = (await api.post(endpoint(org) + "/preview", json=identity)).json()
    assert before["identity"] == {"organization_id": org, "document_id": 1,
                                  "document_version": facts["version"], "content_sha256": facts["content_sha256"]}
    assert [(row["line_no"], row["sku_code"], row["warehouse"], row["original_qty"], row["remaining_qty"])
            for row in before["lines"]] == [(1, "A", "W", "2.00", "2.00"), (2, "A", "W", "3.00", "3.00")]
    assert all(row["blocking_reason"] is None for row in before["lines"])
    body = await request(api, org, facts, [{"line_no": 1, "warehouse": "W", "qty": "2.00"}])
    response = await api.post(endpoint(org), json=body)
    assert response.status_code == 201, response.text
    after = (await api.post(endpoint(org) + "/preview", json=identity)).json()
    assert [(row["remaining_qty"], row["blocking_reason"]) for row in after["lines"]] == [
        ("0.00", "fully_shipped"), ("3.00", None),
    ]
    assert all(row["physical"] is not None and row["reserved"] is not None for row in after["lines"])


async def test_history_pages_verified_acts_after_full_consumption(api, session):
    org, facts = await prepared(api, session)
    identity = {"expected_version": facts["version"], "expected_content_sha256": facts["content_sha256"]}
    path = endpoint(org) + "/history"
    empty = await api.post(path, json=identity)
    assert empty.status_code == 200 and empty.json()["items"] == []
    acts = []
    for line, quantity in [(1, "2.00"), (2, "3.00")]:
        body = await request(api, org, facts, [{"line_no": line, "warehouse": "W", "qty": quantity}])
        response = await api.post(endpoint(org), json=body)
        assert response.status_code == 201, response.text
        acts.append(response.json())
    page1 = await api.post(path, json={**identity, "limit": 1})
    assert page1.status_code == 200, page1.text
    assert page1.json()["items"] == acts[:1]
    page2 = await api.post(path, json={**identity, "limit": 1, "after_id": page1.json()["next_after_id"]})
    assert page2.status_code == 200, page2.text
    assert page2.json()["items"] == acts[1:] and page2.json()["next_after_id"] is None
    assert page1.json()["identity"]["document_id"] == facts["document_id"]
    assert (await api.post(path, json={**identity, "expected_version": facts["version"] + 1})).status_code == 409
    assert (await api.post(endpoint(org + 100) + "/history", json=identity)).status_code == 403
    await session.execute(update(PhysicalShipmentAct).where(PhysicalShipmentAct.id == acts[0]["act_id"])
                          .values(digest="0" * 64).execution_options(synchronize_session=False))
    await session.commit()
    assert (await api.post(path, json=identity)).status_code == 409


async def counts(session):
    return [await session.scalar(select(func.count()).select_from(t)) for t in
            (PhysicalShipmentAct, PhysicalShipmentLine, ReservationVersion, StockMovement)]


async def fulfillment_snapshot(session, org, facts):
    from modules.accounting.service import lock_organization
    from modules.sales.reservation_source import SalesReservationSource

    await lock_organization(session, org)
    await SalesReservationSource().invoice_reservation(session, facts["document_id"])
    return await WmsReservationService().invoice_fulfillment_snapshot(session, org, facts)


async def test_fulfillment_snapshot_stable_detached_read_only_and_started_pick(api, session):
    from sqlalchemy import event

    from modules.wms.invoice_reservations import InvoiceReservation, _digest

    org, facts = await prepared(api, session)
    await fulfillment_snapshot(session, org, facts)  # Caller obtains locks before observing collector I/O.
    writes = []
    commits = []
    def committed(sync_session):
        commits.append(True)
    def observe(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)
    event.listen(session.bind.sync_engine, "before_cursor_execute", observe)
    event.listen(session.sync_session, "after_commit", committed)
    try:
        gateway = WmsReservationService()
        first = await gateway.invoice_fulfillment_snapshot(session, org, facts)
        assert await gateway.invoice_fulfillment_snapshot(session, org, facts) == first
        assert not writes and not commits and session.in_transaction()
        assert first["digest"] == _digest({k: v for k, v in first.items() if k != "digest"})
        assert first["observed_state"] == "no_shipment" and first["coverage_complete"] is False
        assert first["snapshot"]["acts"] == first["snapshot"]["movements"] == []
        assert len(first["snapshot"]["versions"]) == 2
        first["snapshot"]["reservation"]["original_snapshot"]["evidence"] = "local mutation"
        assert (await session.get(InvoiceReservation, 1)).snapshot["evidence"] != "local mutation"
    finally:
        event.remove(session.bind.sync_engine, "before_cursor_execute", observe)
        event.remove(session.sync_session, "after_commit", committed)
    task = await session.scalar(select(Task))
    # SQL write deliberately leaves the cached ORM instance stale.
    await session.execute(text("UPDATE task SET status='in_progress' WHERE id=:id"), {"id": task.id})
    started = await fulfillment_snapshot(session, org, facts)
    assert started["digest"] != first["digest"]
    assert started["observed_state"] == "no_shipment" and started["coverage_complete"] is False
    assert started["snapshot"]["picks"][0]["status"] == "in_progress"
    assert await counts(session) == [0, 0, 2, 1]


async def test_fulfillment_snapshot_preserves_partial_full_history_and_return(api, session):
    org, facts = await prepared(api, session)
    first = await api.post(endpoint(org), json=await request(api, org, facts))
    assert first.status_code == 201, first.text
    partial = await fulfillment_snapshot(session, org, facts)
    assert partial["observed_state"] == "shipped" and partial["coverage_complete"] is False
    assert len(partial["snapshot"]["acts"]) == len(partial["snapshot"]["movements"]) == 1
    body = await request(api, org, facts, [{"line_no": 1, "warehouse": "W", "qty": "1"},
                                         {"line_no": 2, "warehouse": "W", "qty": "3"}])
    assert (await api.post(endpoint(org), json=body)).status_code == 201
    full = await fulfillment_snapshot(session, org, facts)
    assert full["observed_state"] == "shipped" and full["coverage_complete"] is False
    assert len(full["snapshot"]["versions"]) == 5 and len(full["snapshot"]["movements"]) == 3
    lines = [line for act in full["snapshot"]["acts"] for line in act["snapshot"]["lines"]]
    assert [line["line_no"] for line in lines] == [1, 1, 2]
    assert {line["movement_id"] for line in lines} == {m["id"] for m in full["snapshot"]["movements"]}
    assert all(p["status"] == "done" for p in full["snapshot"]["picks"])
    session.add(StockMovement(organization_id=org, sku_code="A", warehouse="W", kind="in", qty=5, reason="receipt"))
    await session.commit()
    restored = await fulfillment_snapshot(session, org, facts)
    assert restored["observed_state"] == "shipped"
    assert restored["snapshot"]["acts"] == full["snapshot"]["acts"]
    assert restored["snapshot"]["movements"] == full["snapshot"]["movements"]


@pytest.mark.parametrize("change", ["movement_qty", "movement_org", "act_digest", "version_gap",
                                    "legacy_out", "pick_org", "pick_done_at", "historical_receipt", "source_identity"])
async def test_fulfillment_snapshot_rejects_corruption_despite_cached_orm(api, session, change):
    from fastapi import HTTPException

    from modules.wms.invoice_reservations import InvoiceReservation

    org, facts = await prepared(api, session)
    assert (await api.post(endpoint(org), json=await request(api, org, facts))).status_code == 201
    cached = await fulfillment_snapshot(session, org, facts)
    assert cached["observed_state"] == "shipped"
    # Keep strong references: SQLAlchemy's identity map otherwise weakly retains rows.
    cached_rows = [(await session.scalars(select(model))).all() for model in
                   (InvoiceReservation, PhysicalShipmentAct, PhysicalShipmentLine, StockMovement, ReservationVersion, Task)]
    assert all(cached_rows)
    statements = {
        "movement_qty": "UPDATE stock_movement SET qty=99 WHERE kind='out'",
        "movement_org": "UPDATE stock_movement SET organization_id=999 WHERE kind='out'",
        "act_digest": "UPDATE physical_shipment_act SET digest='broken'",
        "version_gap": "UPDATE reservation_version SET version=3 WHERE version=2",
        "pick_org": "UPDATE task SET organization_id=999",
        "pick_done_at": "UPDATE task SET status='in_progress', done_at='2026-09-10 00:00:00'",
        "historical_receipt": "UPDATE stock_movement SET qty=11 WHERE kind='in'",
    }
    if change in statements:
        await session.execute(text(statements[change]))
    elif change == "legacy_out":
        session.add(StockMovement(organization_id=org, sku_code="A", warehouse="W", kind="out", qty=1,
                                 reason="pick", doc_ref="sales:document:1"))
        await session.flush()
    else:
        facts = {**facts, "content_sha256": "0" * 64}
    with pytest.raises(HTTPException) as error:
        await fulfillment_snapshot(session, org, facts)
    assert error.value.status_code == 409


async def test_partial_remainder_exact_retry_and_no_shipment_exclusion(api, session):
    org, facts = await prepared(api, session)
    identity = {"expected_version": facts["version"], "expected_content_sha256": facts["content_sha256"]}
    before = (await api.post(endpoint(org) + "/preview", json=identity)).json()
    assert Decimal(before["lines"][0]["physical"]) == 10
    assert Decimal(before["lines"][0]["reserved"]) == 5
    body = await request(api, org, facts)
    first = await api.post(endpoint(org), json=body)
    assert first.status_code == 201, first.text
    assert await counts(session) == [1, 1, 3, 2]
    partial = (await api.post(endpoint(org) + "/preview", json=identity)).json()
    assert Decimal(partial["lines"][0]["physical"]) == 9
    assert Decimal(partial["lines"][0]["reserved"]) == 4
    assert sum(Decimal(row["remaining_qty"]) for row in partial["lines"]) == 4
    remaining = await request(api, org, facts, [{"line_no": 1, "warehouse": "W", "qty": "1.00"},
                                              {"line_no": 2, "warehouse": "W", "qty": "3.00"}])
    second = await api.post(endpoint(org), json=remaining)
    assert second.status_code == 201, second.text
    assert await counts(session) == [2, 3, 5, 4]
    full = (await api.post(endpoint(org) + "/preview", json=identity)).json()
    assert Decimal(full["lines"][0]["physical"]) == 5
    assert Decimal(full["lines"][0]["reserved"]) == 0
    assert all(Decimal(row["remaining_qty"]) == 0 for row in full["lines"])
    again = await api.post(endpoint(org), json=body)
    assert again.status_code == 201 and again.json() == first.json()
    found = await api.get(endpoint(org) + "/by-key/" + body["source_key"])
    assert found.status_code == 200 and found.json() == first.json()
    assert await counts(session) == [2, 3, 5, 4]
    assert all(t.status == "done" for t in (await session.scalars(select(Task))).all())
    with pytest.raises(Exception, match="physical_act_excludes"):
        await release_preview(session, org, facts)
    with pytest.raises(Exception, match="physical_act_excludes"):
        await apply(session, 1, [("A", "W", Decimal("2")), ("A", "W", Decimal("3"))], organization_id=org, release=True)
    await apply(session, 1, [("A", "W", Decimal("2")), ("A", "W", Decimal("3"))], organization_id=org, release=False)
    assert await counts(session) == [2, 3, 5, 4]


@pytest.mark.parametrize("change", ["over", "duplicate", "warehouse", "line", "remaining", "physical", "version", "hash", "future", "boolean"])
async def test_rejections_do_not_change_stock(api, session, change):
    org, facts = await prepared(api, session)
    body = await request(api, org, facts)
    if change == "over":
        body["lines"][0]["qty"] = "2.01"
    if change == "duplicate":
        body["lines"] *= 2
    if change == "warehouse":
        body["lines"][0]["warehouse"] = "OTHER"
    if change == "line":
        body["lines"][0]["line_no"] = 3
    if change == "remaining":
        body["expected_remaining_digest"] = "0" * 64
    if change == "physical":
        body["expected_physical_digest"] = "0" * 64
    if change == "version":
        body["expected_version"] += 1
    if change == "hash":
        body["expected_content_sha256"] = "0" * 64
    if change == "future":
        body["operation_date"] = "2099-01-01"
    if change == "boolean":
        body["journal_complete"] = True
    response = await api.post(endpoint(org), json=body)
    assert response.status_code in (409, 422), response.text
    await session.rollback()
    assert await counts(session) == [0, 0, 2, 1]


async def test_replay_after_close_and_terminal_new_request_denied(api, session):
    org, facts = await prepared(api, session)
    body = await request(api, org, facts)
    result = await api.post(endpoint(org), json=body)
    assert result.status_code == 201, result.text
    period = await session.scalar(select(Period).where(Period.organization_id == org))
    period.closed = True
    # Synthetic terminal state, not proof that cancellation is implemented.
    await session.execute(text("UPDATE deal_document SET status='cancelled' WHERE id=1"))
    await session.commit()
    retry = await api.post(endpoint(org), json=body)
    assert retry.status_code == 201 and retry.json() == result.json()
    changed = deepcopy(body)
    changed["evidence"] = "Changed"
    assert (await api.post(endpoint(org), json=changed)).status_code == 409
    changed["source_key"] = str(uuid4())
    assert (await api.post(endpoint(org), json=changed)).status_code == 409


async def test_closed_period_and_revoked_foreign_access(api, session):
    org, facts = await prepared(api, session)
    body = await request(api, org, facts)
    session.add(Period(organization_id=org, month=body["operation_date"][:7], generation=0, closed=True))
    await session.commit()
    assert (await api.post(endpoint(org), json=body)).status_code == 409
    await session.rollback()
    assert (await api.post(endpoint(org+1), json=body)).status_code in (403, 404)
    await session.rollback()
    grant = await session.scalar(select(AccessGrant).where(AccessGrant.organization_id == org))
    await session.delete(grant)
    await session.commit()
    assert (await api.post(endpoint(org), json=body)).status_code == 403


async def test_owned_pick_and_generic_out_cannot_consume_reserve(api, session):
    org, _ = await prepared(api, session)
    task = await session.scalar(select(Task))
    assert (await api.patch(f"/wms/tasks/{task.id}", json={"status": "done"})).status_code == 409
    for url, body in [
        ("/wms/shipment", dict(qty=6)),
        ("/wms/movements", dict(qty=6, kind="out", reason="shipment")),
        ("/wms/adjustment", dict(qty=-6)),
        ("/wms/shipment", dict(qty=1, doc_ref="sales:document:1")),
    ]:
        response = await api.post(url, json={"organization_id": org, "sku_code": "A", "warehouse": "W", **body})
        assert response.status_code == 409, response.text
        await session.rollback()
    assert await counts(session) == [0, 0, 2, 1]


async def test_owned_pick_assignment_start_partial_and_full_shipment(api, session):
    org, facts = await prepared(api, session)
    task = await session.scalar(select(Task))
    task_id = task.id
    original = (task.organization_id, task.sku_code, task.warehouse, task.qty, task.doc_ref,
                task.from_location_id, task.to_location_id)
    for payload in ({"assignee": "picker", "note": "Collect original invoice goods"},
                    {"status": "in_progress"}):
        response = await api.patch(f"/wms/tasks/{task_id}", json=payload)
        assert response.status_code == 200, response.text
        assert await counts(session) == [0, 0, 2, 1]
    await session.refresh(task)
    assert task.status == "in_progress" and task.done_at is None
    assert task.assignee == "picker" and task.note == "Collect original invoice goods"
    assert (task.organization_id, task.sku_code, task.warehouse, task.qty, task.doc_ref,
            task.from_location_id, task.to_location_id) == original
    partial = await api.post(endpoint(org), json=await request(api, org, facts))
    assert partial.status_code == 201, partial.text
    await session.refresh(task)
    assert task.status == "in_progress" and task.done_at is None
    assert await counts(session) == [1, 1, 3, 2]
    remaining = await request(api, org, facts, [{"line_no": 1, "warehouse": "W", "qty": "1"},
                                              {"line_no": 2, "warehouse": "W", "qty": "3"}])
    full = await api.post(endpoint(org), json=remaining)
    assert full.status_code == 201, full.text
    await session.refresh(task)
    assert task.status == "done" and task.done_at is not None
    assert task.qty == original[3]
    assert await counts(session) == [2, 3, 5, 4]
    assert (await api.patch(f"/wms/tasks/{task_id}", json={"note": "closed"})).status_code == 409


@pytest.mark.parametrize("payload", [{"status": status} for status in
    ("done", "canceled", "cancelled", "open", "unknown", "")] + [{"to_location_id": 123}])
async def test_owned_pick_forbidden_changes_are_atomic(api, session, payload):
    await prepared(api, session)
    task = await session.scalar(select(Task))
    task_id, original_assignee, original_note = task.id, task.assignee, task.note
    response = await api.patch(f"/wms/tasks/{task_id}", json={**payload, "assignee": "changed", "note": "changed"})
    assert response.status_code == 409, response.text
    await session.rollback()
    task = await session.get(Task, task_id)
    assert task.assignee == original_assignee and task.note == original_note
    assert task.status == "open" and task.done_at is None and task.to_location_id is None
    assert await counts(session) == [0, 0, 2, 1]


async def test_started_pick_release_requires_verified_no_shipment_and_replays():
    from modules.wms.invoice_reservations import release
    from modules.wms.reservation_events import ReservationPick
    from tests.test_invoice_reservation_release import (
        RegistryVerifier,
        database,
        seed,
        state,
    )
    from tests.test_invoice_reservation_release import (
        request as release_request,
    )

    async with database() as factory:
        await seed(factory)
        async with factory() as session:
            task = await session.scalar(select(Task).join(ReservationPick).where(ReservationPick.document_id == 1))
            task.status = "in_progress"
            await session.commit()
            source, data = await release_request(session)
            before = await state(session)
            with pytest.raises(Exception):
                await release(session, 1, source, data, "tester", None)
            assert await state(session) == before
            first = await release(session, 1, source, data, "tester", RegistryVerifier())
            await session.commit()
            await session.refresh(task)
            assert task.status == "canceled" and task.done_at is None
            assert (await state(session))["movements"] == before["movements"]
            assert await release(session, 1, source, data, "tester", None) == first


@pytest.mark.parametrize("table", ["reservation_version", "stock_movement", "physical_shipment_act", "physical_shipment_line", "outbox_event"])
async def test_failure_rolls_back_whole_transaction(api, session, table):
    from sqlalchemy import event

    org, facts = await prepared(api, session)
    body = await request(api, org, facts)
    def fail(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO") and table in statement.split("(")[0]:
            raise RuntimeError("Synthetic failure")
    event.listen(session.bind.sync_engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="Synthetic failure"):
            await api.post(endpoint(org), json=body)
    finally:
        event.remove(session.bind.sync_engine, "before_cursor_execute", fail)
        await session.rollback()
    assert await counts(session) == [0, 0, 2, 1]


async def test_unlinked_reduction_and_corrupt_journal_rejected(api, session):
    org, facts = await prepared(api, session)
    row = await session.scalar(select(ReservationVersion))
    session.add(ReservationVersion(organization_id=org, source=row.source, version=2, sku_code="A", warehouse="W",
        qty=1, evidence="Synthetic unexplained", actor="allocator"))
    await session.commit()
    response = await api.post(endpoint(org)+"/preview", json={"expected_version": facts["version"], "expected_content_sha256": facts["content_sha256"]})
    assert response.status_code == 409 and "unexplained" in response.text


async def test_persisted_basis_cannot_be_replaced_by_current_stock_or_client_flag(api, session):
    org, facts = await prepared(api, session)
    await session.execute(text("UPDATE stock_movement SET qty=11"))
    await session.commit()
    response = await api.post(endpoint(org)+"/preview", json={"expected_version": facts["version"], "expected_content_sha256": facts["content_sha256"]})
    assert response.status_code == 409 and "persisted_physical_basis_changed" in response.text


async def test_neutral_pack_transfer_and_receipt_do_not_spend_reserve(api, session):
    org, _ = await prepared(api, session)
    first = await api.post("/wms/locations", json={"warehouse": "W", "code": "L1"})
    second = await api.post("/wms/locations", json={"warehouse": "W", "code": "L2"})
    assert first.status_code == second.status_code == 201
    common = {"organization_id": org, "sku_code": "A", "warehouse": "W", "qty": "8"}
    moved = await api.post("/wms/transfer", json={**common, "from_location_id": first.json()["id"], "to_location_id": second.json()["id"]})
    assert moved.status_code == 201, moved.text
    packed = await api.post("/wms/pack", json=common)
    assert packed.status_code == 201, packed.text
    received = await api.post("/wms/receipt", json=common)
    assert received.status_code == 201, received.text
    assert (await counts(session))[0:3] == [0, 0, 2]


async def test_actual_event_and_api_receipt_after_unknown_response(api, session, monkeypatch):
    import httpx

    from core.domain.models import OutboxEvent

    org, facts = await prepared(api, session)
    body = await request(api, org, facts)
    original = api._transport.handle_async_request
    async def lose_response(req):
        response = await original(req)
        if req.method == "POST" and req.url.path == endpoint(org) and response.status_code == 201:
            raise httpx.ReadError("Synthetic response lost AFTER real commit")
        return response
    monkeypatch.setattr(api._transport, "handle_async_request", lose_response)
    with pytest.raises(httpx.ReadError):
        await api.post(endpoint(org), json=body)
    assert await counts(session) == [1, 1, 3, 2]

    monkeypatch.setattr(api._transport, "handle_async_request", original)
    assert (await api.post(endpoint(org), json=body)).status_code == 201
    events = (await session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "wms.invoice.physical_shipped"))).all()
    assert len(events) == 1 and events[0].payload["source_key"] == body["source_key"]
    assert await counts(session) == [1, 1, 3, 2]


async def test_confirmed_inventory_records_shortage_preserves_reserve_and_blocks_fulfillment(api, session):
    org, facts = await prepared(api, session)
    created = await api.post("/wms/inventory", json={"organization_id": org, "warehouse": "W",
        "expected_source": "wms_physical", "source_evidence": "Synthetic complete journal", "journal_complete": True})
    assert created.status_code == 201, created.text
    count_id = created.json()["id"]
    line = await api.post(f"/wms/inventory/{count_id}/lines", json={"sku_code": "A", "counted_qty": "4"})
    assert line.status_code == 201, line.text
    complete = await api.post(f"/wms/inventory/{count_id}/complete")
    assert complete.status_code == 200, complete.text
    assert complete.json()["status"] == "done"
    repeated = await api.post(f"/wms/inventory/{count_id}/complete")
    assert repeated.status_code == 200, repeated.text
    assert await counts(session) == [0, 0, 2, 2]
    loss = await session.scalar(select(StockMovement).where(StockMovement.kind == "out"))
    assert loss.qty == Decimal("6") and loss.reason == "adjustment"
    available = await invoice_availability(session, org, ["A"])
    assert available["rows"] == [{"sku_code": "A", "warehouse": "W", "physical": "4.00",
                                  "reserved": "5.00", "free": "-1.00"}]
    body = await request(api, org, facts)
    denied = await api.post(endpoint(org), json=body)
    assert denied.status_code == 409 and "physical_reserves_exceed_stock" in denied.text
    await session.rollback()
    assert await counts(session) == [0, 0, 2, 2]


@pytest.mark.parametrize("change", ["confirmation", "stale", "access", "uncounted"])
async def test_inventory_shortage_still_requires_authorized_confirmed_current_count(api, session, change):
    from modules.wms.models import InventoryCount

    org, _ = await prepared(api, session)
    created = await api.post("/wms/inventory", json={"organization_id": org, "warehouse": "W",
        "expected_source": "wms_physical", "source_evidence": "Synthetic complete journal", "journal_complete": True})
    assert created.status_code == 201, created.text
    count_id = created.json()["id"]
    counted = {} if change == "uncounted" else {"counted_qty": "4"}
    line = await api.post(f"/wms/inventory/{count_id}/lines", json={"sku_code": "A", **counted})
    assert line.status_code == 201, line.text
    if change == "confirmation":
        doc = await session.get(InventoryCount, count_id)
        doc.journal_confirmed_at = None
    elif change == "stale":
        session.add(StockMovement(organization_id=org, sku_code="A", warehouse="W", kind="in", qty=1, reason="receipt"))
    elif change == "access":
        grant = await session.scalar(select(AccessGrant).where(AccessGrant.organization_id == org))
        await session.delete(grant)
    await session.commit()
    before = await counts(session)
    response = await api.post(f"/wms/inventory/{count_id}/complete")
    assert response.status_code == (403 if change == "access" else 409), response.text
    await session.rollback()
    assert await counts(session) == before
    assert (await session.get(InventoryCount, count_id)).status == "open"


async def test_started_pick_with_done_timestamp_still_requires_reconciliation(api, session):
    from datetime import datetime

    org, facts = await prepared(api, session)
    task = await session.scalar(select(Task))
    task.status, task.done_at = "in_progress", datetime(2026, 9, 10)
    await session.commit()
    response = await api.post(endpoint(org) + "/preview", json={"expected_version": facts["version"],
        "expected_content_sha256": facts["content_sha256"]})
    assert response.status_code == 409 and "pick_execution_requires_reconciliation" in response.text
    assert await counts(session) == [0, 0, 2, 1]


async def test_delayed_first_reservation_event_does_not_reopen_exhausted_pick(api, session):
    org, facts, data, actor = await setup(api, session)
    await reserve(session, org, facts, data, actor)
    await session.commit()
    body = await request(api, org, facts, [{"line_no": 1, "warehouse": "W", "qty": "2"},
                                         {"line_no": 2, "warehouse": "W", "qty": "3"}])
    response = await api.post(endpoint(org), json=body)
    assert response.status_code == 201, response.text
    await apply(session, 1, [("A", "W", Decimal("2")), ("A", "W", Decimal("3"))], organization_id=org, release=False)
    await session.commit()
    assert all(t.status == "done" for t in (await session.scalars(select(Task))).all())
    assert await counts(session) == [1, 2, 4, 3]
