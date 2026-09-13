"""Actual HTTP order commands against the complete unallocated PostgreSQL proposal."""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from core.domain.models import IdentityInvitationRequest, User
from modules.procurement.models import PurchaseOrder, PurchaseOrderLine, PurchaseRequest
from modules.procurement.order_creation import (
    OrderCommand,
    PurchaseOrderCreation,
    create_order,
    reconcile_order_command,
)
from modules.procurement.ownership import OrderRequestLink
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.accounting.test_procurement_order_creation import command
from tests.accounting.test_procurement_request_creation import command as request_command
from tests.accounting.test_procurement_request_creation_postgres import schedule
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401

HEADERS = {"X-Expected-Principal": "issuer"}


@pytest.mark.parametrize("linked", [False, True])
async def test_pg_order_creation_and_exact_replay(issuance_pg, linked):  # noqa: F811
    api, factory = issuance_pg
    org_response = await api.post("/accounting/organizations", json={"name": "Synthetic orders", "unp": "999999914"})
    assert org_response.status_code == 201, org_response.text
    org = org_response.json()["id"]
    prefix = f"/procurement/organizations/{org}"
    body = command()
    if linked:
        request = await api.post(prefix + "/requests", json=request_command(), headers=HEADERS)
        assert request.status_code == 201, request.text
        request_id = request.json()["request_id"]
        for before, after in zip(("need", "sourcing", "nego", "analysis"), ("sourcing", "nego", "analysis", "approval"), strict=True):
            changed = await api.patch(prefix + f"/requests/{request_id}/stage",
                json={"expected_stage": before, "stage": after}, headers=HEADERS)
            assert changed.status_code == 200, changed.text
        basis = await api.get(prefix + f"/requests/{request_id}/order-basis")
        assert basis.status_code == 200, basis.text
        body["request_basis"] = {"request_id": request_id, "expected_stage": "approval",
            "expected_hash": basis.json()["basis_hash"], "link_evidence": "Reviewed synthetic request"}
    response = await api.post(prefix + "/orders", json=body, headers=HEADERS)
    assert response.status_code == 201, response.text
    saved = response.json()
    for suffix in ("/orders", "/order-commands/reconcile"):
        replay = await api.post(prefix + suffix, json=body, headers=HEADERS)
        assert replay.status_code == 201 and replay.json() == saved, replay.text
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(PurchaseOrder)) == 1
        assert await session.scalar(select(func.count()).select_from(PurchaseOrderLine)) == 2
        assert await session.scalar(select(func.count()).select_from(PurchaseOrderCreation)) == 1
        assert await session.scalar(select(func.count()).select_from(OrderRequestLink)) == int(linked)
        if linked:
            assert (await session.get(PurchaseRequest, saved["request_id"])).stage == "po"
        for sql in ("UPDATE procurement.purchase_order_creation SET actor='changed'",
                    "DELETE FROM procurement.purchase_order_creation", "TRUNCATE procurement.purchase_order_creation"):
            with pytest.raises(DBAPIError, match="immutable"):
                async with session.begin_nested():
                    await session.execute(text(sql))


async def test_pg_reconciliation_tombstone_blocks_late_original(issuance_pg):  # noqa: F811
    api, factory = issuance_pg
    response = await api.post("/accounting/organizations", json={"name": "Synthetic tombstone", "unp": "999999915"})
    assert response.status_code == 201, response.text
    prefix = f"/procurement/organizations/{response.json()['id']}"
    body = command()
    first = await api.post(prefix + "/order-commands/reconcile", json=body, headers=HEADERS)
    assert first.status_code == 409, first.text
    assert first.json()["code"] == "command_abandoned"
    late = await api.post(prefix + "/orders", json=body, headers=HEADERS)
    assert late.status_code == 409 and late.json() == first.json(), late.text
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(PurchaseOrder)) == 0
        assert await session.scalar(select(func.count()).select_from(PurchaseOrderCreation)) == 1


@pytest.mark.parametrize("case", ["same", "changed", "create-reconcile", "reconcile-create", "rollback"])
async def test_pg_order_real_waits(issuance_pg, tmp_path, case):  # noqa: F811
    api, factory = issuance_pg
    response = await api.post("/accounting/organizations", json={"name": "Concurrent orders", "unp": "999999916"})
    assert response.status_code == 201, response.text
    org = response.json()["id"]
    prefix = f"/procurement/organizations/{org}"
    body = command()
    first = ("POST", prefix + "/orders", body)
    second = deepcopy(first)
    if case == "changed":
        second[2]["document"]["freight_byn"] = "11.00"
    elif case == "create-reconcile":
        second = ("POST", prefix + "/order-commands/reconcile", body)
    elif case == "reconcile-create":
        first = ("POST", prefix + "/order-commands/reconcile", body)
    evidence = {"case": case, "locks": []}
    async with factory() as session:
        evidence["database"] = await session.scalar(text("SELECT current_database()"))
    pg = SimpleNamespace(api=api, factory=factory, org=org, prefix=prefix, evidence=evidence)
    try:
        results = await schedule(pg, first, second, fault=case == "rollback")
        expected = [409, 409] if case == "reconcile-create" else [201, 409] if case == "changed" else [422, 201] if case == "rollback" else [201, 201]
        assert [r["status"] for r in results] == expected, results
        if case in {"same", "create-reconcile", "reconcile-create"}:
            assert results[0]["body"] == results[1]["body"]
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(PurchaseOrderCreation)) == 1
            assert await session.scalar(select(func.count()).select_from(PurchaseOrder)) == int(case != "reconcile-create")
            assert await session.scalar(select(func.count()).select_from(PurchaseOrderLine)) == 2 * int(case != "reconcile-create")
    finally:
        (tmp_path / "order-lock-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.parametrize("replay", [False, True])
async def test_pg_order_revoked_user_after_real_wait(issuance_pg, tmp_path, replay):  # noqa: F811
    api, factory = issuance_pg
    response = await api.post("/accounting/organizations", json={"name": "Revocation orders", "unp": "999999917"})
    assert response.status_code == 201, response.text
    org = response.json()["id"]
    prefix = f"/procurement/organizations/{org}"
    body = command()
    if replay:
        initial = await api.post(prefix + "/orders", json=body, headers=HEADERS)
        assert initial.status_code == 201, initial.text
    evidence = {"locks": [], "replay": replay}
    async with factory() as session:
        connection = await session.connection()
        for model in (User, IdentityInvitationRequest):
            await connection.run_sync(lambda c, model=model: model.__table__.create(c, checkfirst=True))
        session.add(User(username="issuer", full_name="Synthetic", keycloak_user_id="issuer", role="director", status="active"))
        await session.commit()
        evidence["database"] = await session.scalar(text("SELECT current_database()"))
    pg = SimpleNamespace(api=api, factory=factory, org=org, prefix=prefix, evidence=evidence)
    try:
        results = await schedule(pg, ("POST", prefix + "/orders", command()),
                                 ("POST", prefix + "/orders", body), revoke={"status": "suspended"})
        assert [r["status"] for r in results] == [201, 403], results
        trace = evidence["locks"][-1]
        assert trace["cached_before"]["python_id"] == trace["cached_after"]["python_id"]
        assert trace["cached_after"]["status"] == "suspended"
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(PurchaseOrderCreation)) == 1 + int(replay)
            assert await session.scalar(select(func.count()).select_from(PurchaseOrder)) == 1 + int(replay)
    finally:
        (tmp_path / "order-revocation-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.parametrize("case", ["changed-line", "rejected-then-order"])
async def test_pg_deferred_guard_rejects_corrupted_package_at_commit(issuance_pg, case):  # noqa: F811
    api, factory = issuance_pg
    response = await api.post("/accounting/organizations", json={"name": "Deferred proof", "unp": "999999918"})
    assert response.status_code == 201, response.text
    org = response.json()["id"]
    async with factory() as session:
        data = OrderCommand.model_validate(command())
        if case == "changed-line":
            await create_order(org, data, ctx=(session, "issuer"))
            assert await session.scalar(select(func.count()).select_from(PurchaseOrderCreation)) == 1
            await session.execute(text("UPDATE procurement.purchase_order_line SET goods_value_byn=goods_value_byn+1"))
        else:
            await reconcile_order_command(org, data, ctx=(session, "issuer"))
            assert await session.scalar(select(func.count()).select_from(PurchaseOrderCreation)) == 1
            session.add(PurchaseOrder(number="Late forbidden order", supplier="Synthetic"))
            await session.flush()
        # A real database commit evaluates the deferred trigger, without an
        # injected Python failure or an early SET CONSTRAINTS operation.
        expected_error = "initial lines mismatch" if case == "changed-line" else "Invalid rejected order creation outcome"
        with pytest.raises(DBAPIError, match=expected_error):
            await session.commit()
        await session.rollback()
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(PurchaseOrderCreation)) == 0
        assert await session.scalar(select(func.count()).select_from(PurchaseOrder)) == 0
        assert await session.scalar(select(func.count()).select_from(PurchaseOrderLine)) == 0
