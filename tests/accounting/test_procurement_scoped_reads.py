"""Owned reads and current-context editor mutations; no PostgreSQL assumptions."""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select

from core.domain.models import OutboxEvent
from core.services.auth import CurrentUser, get_current_user
from core.services.eventbus import OutboxEventBus
from modules.accounting.models import AccessGrant, Organization
from modules.procurement import order_creation, order_edit_commands, ownership, routes, scoped_reads
from modules.procurement.expected_reservations import PhysicalReceiptAcceptance
from modules.procurement.models import (
    LandedCost,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderMilestone,
    PurchaseRequest,
    ShipRequirement,
    TransportMethod,
)
from modules.procurement.receipt_documents import ReceiptDocument, ReceiptPosting, ReceiptRevision

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def setup_routes(client, db):
    async with db.bind.begin() as conn:
        await conn.run_sync(
            lambda c: PurchaseOrderMilestone.metadata.create_all(
                c,
                tables=[
                    PurchaseOrderMilestone.__table__,
                    TransportMethod.__table__,
                    ShipRequirement.__table__,
                    LandedCost.__table__,
                    OutboxEvent.__table__,
                    order_edit_commands.PurchaseOrderEditCommand.__table__,
                ],
            )
        )
    client.test_app.include_router(order_edit_commands.router, prefix="/procurement")
    client.test_app.include_router(routes.router, prefix="/procurement")
    client.test_app.include_router(scoped_reads.router, prefix="/procurement")
    client.test_app.include_router(order_creation.router, prefix="/procurement")
    client.test_app.state.core.event_bus = OutboxEventBus()


@pytest_asyncio.fixture
async def source(db, book, client):
    row = PurchaseOrder(number="OWN-A", supplier="A", freight_byn=Decimal("2.00"))
    db.add(row)
    await db.flush()
    owner = ownership.PurchaseOwnership(
        organization_id=book[0],
        kind="order",
        source_id=row.id,
        snapshot={},
        evidence="Synthetic",
        actor="tester",
    )
    line = PurchaseOrderLine(
        order_id=row.id,
        sku_code="SAME",
        qty=Decimal("2.00"),
        goods_value_byn=Decimal("10.00"),
        weight=Decimal("1.000"),
        volume=Decimal("0.1000"),
    )
    db.add_all([owner, line])
    await db.commit()
    client.headers.update(
        {"X-Expected-Organization": str(book[0]), "X-Expected-Principal": "tester"}
    )
    client.command_org = book[0]
    return row.id, line.id


def scoped(book, order_id, suffix=""):
    return f"/procurement/organizations/{book[0]}/orders/{order_id}{suffix}"


async def state(db, order_id):
    row = await db.get(PurchaseOrder, order_id, populate_existing=True)
    lines = (
        await db.scalars(
            select(PurchaseOrderLine)
            .where(PurchaseOrderLine.order_id == order_id)
            .order_by(PurchaseOrderLine.id)
        )
    ).all()
    milestones = (
        await db.scalars(
            select(PurchaseOrderMilestone).where(PurchaseOrderMilestone.order_id == order_id)
        )
    ).all()
    methods = (await db.scalars(select(TransportMethod))).all()
    return (
        row.status,
        str(row.freight_byn),
        row.target_arrival_date,
        [(x.id, x.sku_code, str(x.qty), str(x.goods_value_byn)) for x in lines],
        [(x.stage, x.planned_date, x.actual_date) for x in milestones],
        len(methods),
    )


async def test_purchase_chain_shows_only_verified_linked_stages(client, db, book, source):
    order_id, line_id = source
    order_owner = await db.scalar(select(ownership.PurchaseOwnership).where(
        ownership.PurchaseOwnership.organization_id == book[0],
        ownership.PurchaseOwnership.kind == "order",
        ownership.PurchaseOwnership.source_id == order_id,
    ))
    request = PurchaseRequest(number="REQ-CHAIN", supplier="A", item="SAME", qty=2,
                              amount=Decimal("10.00"), stage="approval")
    db.add(request)
    await db.flush()
    request_owner = ownership.PurchaseOwnership(
        organization_id=book[0], kind="request", source_id=request.id,
        snapshot={"number": request.number}, evidence="request evidence", actor="tester",
    )
    db.add(request_owner)
    await db.flush()
    db.add(ownership.OrderRequestLink(
        organization_id=book[0], order_ownership_id=order_owner.id,
        request_ownership_id=request_owner.id, evidence="link evidence", actor="tester",
    ))
    document = ReceiptDocument(
        organization_id=book[0], source_key="chain-receipt", current_version=1,
        status="draft", created_by="tester",
    )
    db.add(document)
    await db.flush()
    facts = {
        "currency": "BYN", "invoice_reference": "INV-CHAIN", "document_date": "2026-09-01",
        "operation_date": "2026-09-02", "supplier": "A", "contract": "C-1",
        "warehouse": "Главный", "items": [{
            "order_id": order_id, "order_line_id": line_id, "sku": "SAME", "lot": "L-1",
            "unit": "шт", "quantity": "2.00", "net_amount": "10.00",
        }],
    }
    db.add(ReceiptRevision(receipt_id=document.id, version=1, document=facts, actor="tester"))
    db.add(ReceiptPosting(receipt_id=document.id, version=1, entry_id=9001,
                          options={"expected_version": 1}, digest="a" * 64, actor="tester"))
    db.add(PhysicalReceiptAcceptance(
        organization_id=book[0], event_id=9001, receipt_id=7001,
        source_receipt_id=document.id, source_version=1,
        lines=[{"position": 1, "order_line_id": line_id, "sku_code": "SAME",
                 "accepted_qty": "2.00", "source_line": f"procurement:receipt:{document.id}:1:1"}],
        evidence="QC confirmed", actor="warehouse",
    ))
    await db.commit()

    response = await client.get(f"/procurement/organizations/{book[0]}/orders/{order_id}/chain")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "complete"
    assert body["stages"] == {"request": "linked", "order": "owned",
                               "incoming_invoice": "posted", "warehouse": "accepted"}
    assert body["blockers"] == []
    assert body["request_links"][0]["number"] == "REQ-CHAIN"
    assert body["receipts"][0]["invoice_reference"] == "INV-CHAIN"
    assert body["receipts"][0]["posting"] == {"entry_id": 9001, "version": 1}
    assert body["receipts"][0]["physical_acceptance"][0]["receipt_id"] == 7001
    assert body["receipts"][0]["lines"][0]["order_line_id"] == line_id


async def test_purchase_chain_exposes_missing_invoice_and_qc_without_guessing(client, db, book, source):
    response = await client.get(f"/procurement/organizations/{book[0]}/orders/{source[0]}/chain")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "partial"
    assert body["stages"]["order"] == "owned"
    assert body["stages"]["incoming_invoice"] == "missing"
    assert body["stages"]["warehouse"] == "missing"
    assert body["blockers"] == ["purchase_request_not_linked", "incoming_invoice_not_registered"]


@pytest.mark.parametrize(
    "path",
    [
        "/orders",
        "/open-orders",
        "/orders/1",
        "/orders/1/landed-preview",
        "/orders/1/plan",
        "/requests",
        "/board",
    ],
)
async def test_global_reads_never_return_documents(client, path):
    response = await client.get("/procurement" + path)
    assert response.status_code == 410
    assert set(response.json()) == {"detail"}


async def test_owned_lists_exclude_foreign_and_unassigned(client, db, book, source):
    own = await db.get(PurchaseOrder, source[0])
    own.status = "ordered"
    other_org = Organization(name="B", unp="999999998")
    db.add(other_org)
    await db.flush()
    foreign = PurchaseOrder(number="FOREIGN-SECRET", supplier="B", status="ordered")
    unknown = PurchaseOrder(number="UNASSIGNED-SECRET", supplier="legacy", status="ordered")
    db.add_all([foreign, unknown])
    await db.flush()
    db.add(
        ownership.PurchaseOwnership(
            organization_id=other_org.id,
            kind="order",
            source_id=foreign.id,
            snapshot={},
            evidence="B",
            actor="tester",
        )
    )
    await db.commit()
    other_org_id = other_org.id
    for endpoint in ["open-orders", "owned-sources?kind=order"]:
        response = await client.get(f"/procurement/organizations/{book[0]}/{endpoint}")
        assert response.status_code == 200
        assert [x["id"] for x in response.json()["items"]] == [source[0]]
        assert "SECRET" not in response.text
    for other in [foreign.id, unknown.id, 99999]:
        for suffix in ["", "/landed-preview", "/plan"]:
            denied = await client.get(scoped(book, other, suffix))
            assert denied.status_code == 409
            assert "SECRET" not in denied.text
    assert (
        await client.get(f"/procurement/organizations/{other_org_id}/open-orders")
    ).status_code == 403


async def test_reader_can_read_but_cannot_mutate(client, db, book, source):
    grant = await db.scalar(select(AccessGrant).where(AccessGrant.organization_id == book[0]))
    grant.role = "reader"
    await db.commit()
    assert (await client.get(scoped(book, source[0]))).status_code == 200
    before = await state(db, source[0])
    response = await _edit(client, "PATCH",
        f"/procurement/orders/{source[0]}/header", json={"freight_byn": "7.00"}
    )
    assert response.status_code == 403
    assert await state(db, source[0]) == before


COMMANDS = [
    ("POST", "/lines", {"sku_code": "NEW", "qty": "1.00"}),
    ("DELETE", "/lines/{line}", None),
    ("PATCH", "/header", {"freight_byn": "4.00"}),
    ("PATCH", "", {"status": "ordered"}),
    ("POST", "/plan", {"transport_method_code": "truck", "target_arrival_date": "2026-12-01"}),
]


@pytest.mark.parametrize("method,suffix,body", COMMANDS)
async def test_unauthorized_order_does_not_reveal_owner_by_expected_header(
    client, db, book, source, method, suffix, body
):
    grant = await db.scalar(select(AccessGrant).where(AccessGrant.organization_id == book[0]))
    await db.delete(grant)
    await db.commit()
    before = await state(db, source[0])
    responses = []
    for expected in (book[0], book[0] + 999):
        client.headers["X-Expected-Organization"] = str(expected)
        response = await _edit(client, method,
            f"/procurement/orders/{source[0]}" + suffix.format(line=source[1]),
            **({"json": body} if body is not None else {}))
        assert response.status_code == 403
        responses.append(response.json())
    assert responses[0] == responses[1]
    assert await state(db, source[0]) == before


@pytest.mark.parametrize("method,suffix,body", COMMANDS)
@pytest.mark.parametrize("wrong", ["org", "principal", "missing", "revoked", "disabled"])
async def test_writes_refuse_stale_context_without_changes(
    client, db, book, source, method, suffix, body, wrong
):
    before = await state(db, source[0])
    if wrong == "org":
        client.headers["X-Expected-Organization"] = str(book[0] + 999)
    if wrong == "principal":
        client.headers["X-Expected-Principal"] = "new-person"
    if wrong == "missing":
        del client.headers["X-Expected-Principal"]
    if wrong == "revoked":
        grant = await db.scalar(select(AccessGrant).where(AccessGrant.organization_id == book[0]))
        await db.delete(grant)
        await db.commit()
    if wrong == "disabled":
        client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            "tester", ["director"], local_status="disabled"
        )
    response = await _edit(client, method,
        f"/procurement/orders/{source[0]}" + suffix.format(line=source[1]),
        **({"json": body} if body is not None else {}),
    )
    assert (
        response.status_code
        == {"org": 409, "principal": 409, "missing": 422, "revoked": 403, "disabled": 403}[wrong]
    ), response.text
    assert await state(db, source[0]) == before


async def test_exact_decimals_and_line_ownership(client, db, book, source):
    result = await _edit(client, "POST",
        f"/procurement/orders/{source[0]}/lines",
        json={
            "sku_code": "EXACT",
            "qty": "2.13",
            "goods_value_byn": "1234567.89",
            "weight": "1.123",
            "volume": "0.1234",
        },
    )
    assert result.status_code == 200, result.text
    ack = result.json()
    assert (
        ack["organization_id"] == book[0]
        and ack["principal"] == "tester"
        and ack["action"] == "add_line"
    )
    saved = await db.get(PurchaseOrderLine, ack["effect"]["line"]["id"])
    assert (saved.qty, saved.goods_value_byn, saved.weight, saved.volume) == tuple(
        map(Decimal, ["2.13", "1234567.89", "1.123", "0.1234"])
    )
    own2 = PurchaseOrder(number="OTHER", supplier="B")
    db.add(own2)
    await db.flush()
    line = PurchaseOrderLine(order_id=own2.id, sku_code="B", qty=1, goods_value_byn=1)
    db.add(line)
    await db.commit()
    before = await state(db, source[0])
    assert (
        await _edit(client, "DELETE",f"/procurement/orders/{source[0]}/lines/{line.id}")
    ).status_code == 409
    assert await db.get(PurchaseOrderLine, line.id) is not None
    assert await state(db, source[0]) == before


@pytest.mark.parametrize(
    "value", [1.23, -1, "-1.00", "1.001", "1e2", "NaN", "1000000000000.00", None]
)
async def test_inexact_money_never_writes(client, db, source, value):
    before = await state(db, source[0])
    assert (
        await _edit(client, "PATCH",f"/procurement/orders/{source[0]}/header", json={"freight_byn": value})
    ).status_code == 422
    assert await state(db, source[0]) == before


@pytest.mark.parametrize(
    "body",
    [
        {"transport_method_code": "truck"},
        {"transport_method_code": "truck", "target_arrival_date": None},
        {"transport_method_code": "truck", "target_arrival_date": "bad"},
    ],
)
async def test_missing_plan_date_does_not_even_seed_methods(client, db, source, body):
    before = await state(db, source[0])
    assert (
        await _edit(client, "POST",f"/procurement/orders/{source[0]}/plan", json=body)
    ).status_code == 422
    assert await state(db, source[0]) == before


async def test_get_and_post_plan_never_read_foreign_requirements(
    client, db, book, source, monkeypatch
):
    db.add(
        ShipRequirement(
            deal_id=999,
            sku_code="SAME",
            number="SECRET",
            counterparty="FOREIGN",
            ship_deadline_date=date(2020, 1, 1),
            penalty_terms="SECRET",
        )
    )
    await db.commit()
    forbidden = AsyncMock(side_effect=AssertionError("Unscoped requirement read"))
    monkeypatch.setattr(routes, "_order_requirements", forbidden)
    response = await _edit(client, "POST",
        f"/procurement/orders/{source[0]}/plan",
        json={"transport_method_code": "truck", "target_arrival_date": "2026-12-01"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["principal"] == "tester"
    fetched = await client.get(scoped(book, source[0], "/plan"))
    for data in [response.json()["effect"], fetched.json()]:
        assert data["target_arrival_date"] == "2026-12-01"
        assert data["total_days"] == 83
        assert data["customer_requirements_status"] == "unverified"
        assert all(
            data[x] is None for x in ["required_by", "required_arrival", "slack_days", "at_risk"]
        )
        assert data["at_risk_deals"] == []
        assert "SECRET" not in str(data)
    forbidden.assert_not_called()


async def test_pagination_and_terminal_filter(client, db, book, source):
    for i in range(53):
        row = PurchaseOrder(
            number=f"P{i}",
            supplier="same",
            status="ordered",
            eta_date=None if i % 2 else date(2026, 12, 1),
        )
        db.add(row)
        await db.flush()
        db.add(
            ownership.PurchaseOwnership(
                organization_id=book[0],
                kind="order",
                source_id=row.id,
                snapshot={},
                evidence="test",
                actor="tester",
            )
        )
    db.add_all(
        [
            PurchaseOrderLine(order_id=source[0], sku_code=f"LINE{i}", qty=1, goods_value_byn=0)
            for i in range(201)
        ]
    )
    await db.commit()
    first = (await client.get(f"/procurement/organizations/{book[0]}/open-orders")).json()
    second = (
        await client.get(
            f"/procurement/organizations/{book[0]}/open-orders?after_id={first['next_after_id']}"
        )
    ).json()
    ids = [r["id"] for r in first["items"] + second["items"]]
    assert len(first["items"]) == 50 and len(set(ids)) == 53 and ids == sorted(ids)
    assert source[0] not in ids and second["next_after_id"] is None
    assert all("lines" not in x for x in first["items"])
    detail = (await client.get(scoped(book, source[0]))).json()
    tail = (
        await client.get(scoped(book, source[0]) + f"?after_line_id={detail['next_after_line_id']}")
    ).json()
    assert (
        len(detail["lines"]) == 200
        and len(tail["lines"]) == 2
        and tail["next_after_line_id"] is None
    )
    assert len({x["id"] for x in detail["lines"] + tail["lines"]}) == 202


async def test_preview_is_exact_and_non_mutating(client, db, book, source, monkeypatch):
    from core.services import sku_master

    lookup = AsyncMock(return_value={"SAME": {"duty_pct": 10}})
    monkeypatch.setattr(sku_master, "landed_inputs_batch", lookup)
    before = await state(db, source[0])
    denied = await client.get(scoped(book, 999999, "/landed-preview"))
    assert denied.status_code == 409
    lookup.assert_not_called()
    response = await client.get(scoped(book, source[0], "/landed-preview"))
    assert response.status_code == 200, response.text
    assert Decimal(response.json()["total_landed_byn"]) == Decimal("13.20")
    assert Decimal(response.json()["lines"][0]["unit_landed_cost_byn"]) == Decimal("6.60")
    assert await state(db, source[0]) == before
    assert (await db.scalars(select(LandedCost))).all() == []


@pytest.mark.parametrize(
    "suffix",
    ["owned-sources?kind=order", "purchase-ownership", "order-request-links", "open-orders"],
)
async def test_read_rechecks_effective_identity_after_authorization(
    client, book, source, monkeypatch, suffix
):
    resolve = AsyncMock(
        side_effect=[
            CurrentUser("tester", ["director"]),
            CurrentUser("tester", ["director"], local_status="disabled"),
        ]
    )
    monkeypatch.setattr(ownership, "resolve_effective_oidc_user", resolve)
    response = await client.get(f"/procurement/organizations/{book[0]}/{suffix}")
    assert response.status_code == 403
    assert resolve.await_count == 2


async def test_read_identity_lookup_failure_is_not_an_empty_list(client, book, source, monkeypatch):
    from core.services.auth import EffectiveIdentityLookupError

    monkeypatch.setattr(
        ownership,
        "resolve_effective_oidc_user",
        AsyncMock(side_effect=EffectiveIdentityLookupError("unavailable")),
    )
    response = await client.get(f"/procurement/organizations/{book[0]}/open-orders")
    assert response.status_code == 503
    assert "items" not in response.json()


@pytest.mark.parametrize("role", ["reader", "accountant"])
@pytest.mark.parametrize("method,suffix,body", COMMANDS)
async def test_nonchief_cannot_execute_any_editor_command(
    client, db, book, source, role, method, suffix, body
):
    grant = await db.scalar(select(AccessGrant).where(AccessGrant.organization_id == book[0]))
    grant.role = role
    await db.commit()
    before = await state(db, source[0])
    response = await _edit(client, method,
        f"/procurement/orders/{source[0]}" + suffix.format(line=source[1]),
        **({"json": body} if body is not None else {}),
    )
    assert response.status_code == 403
    assert await state(db, source[0]) == before


async def _edit(client, method, path, json=None):
    import re
    from uuid import uuid4
    match = re.fullmatch(r"/procurement/orders/(\d+)(.*)", path)
    order_id, suffix = int(match[1]), match[2]
    action = "delete_line" if method == "DELETE" else {"/lines": "add_line", "/header": "header", "/plan": "plan", "": "status"}[suffix]
    payload = {"line_id": int(suffix.rsplit("/", 1)[1])} if action == "delete_line" else json
    org = getattr(client, "command_org", client.headers["X-Expected-Organization"])
    return await client.post(f"/procurement/organizations/{org}/orders/{order_id}/edit-commands", json={
        "version": 1, "request_key": str(uuid4()), "order_id": order_id, "action": action, "payload": payload})
