"""Creation commands against the frozen proposal in fresh owned PostgreSQL databases."""
# The remaining tests exercise real request transactions and production guards.
import asyncio
import json
import os
import re
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import Request
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import IdentityInvitationRequest, User
from core.runtime.deps import get_session
from core.services.auth import CurrentUser, get_current_user
from modules.procurement.models import PurchaseOrder, PurchaseOrderLine, PurchaseRequest
from modules.procurement.ownership import (
    OrderRequestLink,
    PurchaseOwnership,
    PurchaseRequestCreation,
    request_command_hash,
)
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.accounting.test_procurement_request_creation import command
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401
from tests.test_shipping_producer_concurrency_postgres import (
    TIMEOUT,
    connection_identity,
    isolated_target,  # noqa: F401
    observe_wait,
    ready,
)


@pytest.mark.parametrize("supplier", ["Поставщик Беларусь", 'Поставщик "quoted" \\ line\nnext 🙂', "\u001c\u00a0Поставщик\u001cвнутри\u001f"])
async def test_pg_request_creation_unicode_and_historical_replay(issuance_pg, supplier):  # noqa: F811
    client, _ = issuance_pg
    organization = await client.post("/accounting/organizations", json={"name": "Synthetic procurement", "unp": "999999911"})
    assert organization.status_code == 201, organization.text
    org = organization.json()["id"]
    body = command()
    body["document"]["supplier"] = supplier
    body["document"]["item"] = "\u001c" + body["document"]["item"] + "\u001f"
    body["ownership_evidence"] = "\u001c" + body["ownership_evidence"] + "\u001f"
    path = f"/procurement/organizations/{org}/requests"
    headers = {"X-Expected-Principal": "issuer"}
    created = await client.post(path, json=body, headers=headers)
    assert created.status_code == 201, created.text
    result = created.json()
    changed = await client.patch(path + f'/{result["request_id"]}/stage',
        json={"expected_stage": "need", "stage": "sourcing"}, headers=headers)
    assert changed.status_code == 200, changed.text
    repeated = await client.post(path, json=body, headers=headers)
    assert repeated.status_code == 201 and repeated.json() == result, repeated.text

HEADERS = {"X-Expected-Principal": "issuer"}


@pytest_asyncio.fixture(autouse=True)
async def evidence(pg_factory, request):  # noqa: F811
    async with pg_factory() as session:
        name = await session.scalar(text("SELECT current_database()"))
        assert re.fullmatch(r"acc_test_[0-9a-f]{32}", name)
    output = Path(os.environ["PRODUCER_PG_EVIDENCE_DIR"]) / (name + ".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    record = {"database": name, "test": request.node.name, "locks": []}
    output.write_text(json.dumps(record), encoding="utf-8")
    try:
        yield record
    finally:
        output.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")


@pytest_asyncio.fixture
async def plan_pg(issuance_pg, evidence):  # noqa: F811
    api, factory = issuance_pg
    async with factory() as session:
        conn = await session.connection()
        for model in (PurchaseOrder, PurchaseOrderLine, User, IdentityInvitationRequest):
            await conn.run_sync(lambda c, model=model: model.__table__.create(c, checkfirst=True))
        assert await session.scalar(text("SELECT to_regclass('procurement.purchase_request_creation')"))
        await session.commit()
    response = await api.post("/accounting/organizations", json={"name": "PG synthetic procurement", "unp": "999999913"})
    assert response.status_code == 201, response.text
    org = response.json()["id"]
    return SimpleNamespace(api=api, factory=factory, org=org, prefix=f"/procurement/organizations/{org}", evidence=evidence)


async def create_request(pg, body=None):
    response = await pg.api.post(pg.prefix + "/requests", json=body or command(), headers=HEADERS)
    assert response.status_code == 201, response.text
    return response.json()


async def counts(pg):
    async with pg.factory() as session:
        return {model.__name__: await session.scalar(select(func.count()).select_from(model))
                for model in (PurchaseRequest, PurchaseOwnership, PurchaseRequestCreation, OrderRequestLink)}


async def approve(pg, request_id):
    for before, after in zip(("need", "sourcing", "nego", "analysis"), ("sourcing", "nego", "analysis", "approval"), strict=True):
        response = await pg.api.patch(pg.prefix + f"/requests/{request_id}/stage", headers=HEADERS,
                                      json={"expected_stage": before, "stage": after})
        assert response.status_code == 200, response.text


async def owned_order(pg):
    async with pg.factory() as session:
        order = PurchaseOrder(number="PG-ORDER", supplier="Synthetic")
        session.add(order)
        await session.commit()
        order_id = order.id
    response = await pg.api.post(pg.prefix + "/purchase-ownership", json={"kind": "order", "source_id": order_id, "evidence": "PG owner"})
    assert response.status_code == 201, response.text
    return order_id


async def schedule(pg, first, second, *, fault=False, revoke=None):
    holding, started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    trace = {"fault_before_commit": fault}
    app = pg.api._transport.app
    original = app.dependency_overrides[get_session]
    old_auth = app.dependency_overrides.get(get_current_user)

    class BoundarySession(AsyncSession):
        async def commit(self):
            if self.info["role"] == "holder" and not self.info.get("held"):
                self.info["held"] = True
                holding.set()
                await asyncio.wait_for(release.wait(), TIMEOUT)
                if fault:
                    raise ValueError("Synthetic request package fault before commit")
            await super().commit()
            trace[self.info["role"] + "_committed"] = True

        async def rollback(self):
            if self.info.get("retained_user") is not None:
                retained = self.info["retained_user"]
                trace["cached_after"] = {"status": retained.status, "role": retained.role, "python_id": id(retained)}
            await super().rollback()
            trace[self.info["role"] + "_rolled_back"] = True

    async def session_dependency(request: Request):
        role = request.headers["X-PG-Test-Role"]
        async with BoundarySession(bind=pg.factory.kw["bind"], expire_on_commit=False) as session:
            session.info["role"] = role
            trace[role] = await connection_identity(session)
            if revoke and role == "waiter":
                retained = await session.scalar(select(User).where(User.keycloak_user_id == "issuer"))
                assert retained.status == "active" and retained.role == "director"
                session.info["retained_user"] = retained  # strong ref: identity map must not expire it
                trace["cached_before"] = {"status": retained.status, "role": retained.role, "python_id": id(retained)}
            if role == "waiter":
                started.set()
            yield session

    async def call(operation, role):
        method, url, body = operation
        response = await pg.api.request(method, url, json=body, headers={**HEADERS, "X-PG-Test-Role": role})
        return {"status": response.status_code, "body": response.json()}

    app.dependency_overrides[get_session] = session_dependency
    if revoke:
        # Same fixture subject and director claims; exercise real OIDC local-account
        # resolution rather than replacing it or manufacturing an actor/grant.
        app.dependency_overrides[get_current_user] = lambda: CurrentUser("issuer", ["director"], keycloak_user_id="issuer")
    tasks = []
    try:
        tasks.append(asyncio.create_task(call(first, "holder")))
        await ready(holding, tasks[0])
        tasks.append(asyncio.create_task(call(second, "waiter")))
        await ready(started, tasks[1])
        assert trace["holder"]["pid"] != trace["waiter"]["pid"]
        assert trace["holder"]["txid"] != trace["waiter"]["txid"]
        trace["blocked"] = await observe_wait(pg, trace["waiter"]["pid"], trace["holder"]["pid"])
        assert "accounting.organization" in trace["blocked"]["query"]
        if revoke:
            async with pg.factory() as session:
                trace["revoker"] = await connection_identity(session)
                await session.execute(update(User).where(User.keycloak_user_id == "issuer").values(**revoke))
                await session.commit()
            trace["revocation"] = revoke
        release.set()
        result = await asyncio.wait_for(asyncio.gather(*tasks), TIMEOUT)
        trace["results"] = result
        return result
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        app.dependency_overrides[get_session] = original
        if old_auth is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = old_auth
        pg.evidence["locks"].append(trace)


@pytest.mark.parametrize("case", ["same-command", "changed-command", "stage", "link"])
async def test_pg_plan_actual_waits(plan_pg, case):
    pg = plan_pg
    body = command()
    first = ("POST", pg.prefix + "/requests", body)
    second = deepcopy(first)
    if case == "changed-command":
        second[2]["document"]["qty"] = 4
    if case in {"stage", "link"}:
        created = await create_request(pg)
        request_id = created["request_id"]
        if case == "stage":
            first = ("PATCH", pg.prefix + f"/requests/{request_id}/stage", {"expected_stage": "need", "stage": "sourcing"})
        else:
            await approve(pg, request_id)
            order_id = await owned_order(pg)
            first = ("POST", pg.prefix + f"/requests/{request_id}/order-link", {"expected_stage": "approval", "order_id": order_id, "evidence": "PG link"})
        second = deepcopy(first)
    results = await schedule(pg, first, second)
    assert [r["status"] for r in results] == ([201, 409] if case == "changed-command" else [200, 200] if case == "stage" else [201, 201])
    if case != "changed-command":
        assert results[0]["body"] == results[1]["body"]
    after = await counts(pg)
    assert after["PurchaseRequestCreation"] == after["PurchaseRequest"] == 1
    assert after["OrderRequestLink"] == int(case == "link")
    async with pg.factory() as session:
        row = await session.scalar(select(PurchaseRequest))
        assert row.stage == ("po" if case == "link" else "sourcing" if case == "stage" else "need")
        pg.evidence["request_stage"] = row.stage
        if case == "link":
            link = await session.scalar(select(OrderRequestLink))
            owner = await session.get(PurchaseOwnership, link.request_ownership_id)
            assert owner.source_id == row.id and link.organization_id == owner.organization_id == pg.org
            pg.evidence["link"] = {"id": link.id, "request_id": row.id, "request_ownership_id": owner.id}
    if case == "stage":
        advanced = await pg.api.patch(first[1], json={"expected_stage": "sourcing", "stage": "nego"}, headers=HEADERS)
        assert advanced.status_code == 200
        stale = await pg.api.patch(first[1], json=first[2], headers=HEADERS)
        assert stale.status_code == 409
        pg.evidence["stale_stage_status"] = stale.status_code
    pg.evidence["after"] = after


async def test_pg_creation_root_rollback_unblocks_identical_retry(plan_pg):
    pg = plan_pg
    operation = ("POST", pg.prefix + "/requests", command())
    results = await schedule(pg, operation, operation, fault=True)
    assert [r["status"] for r in results] == [422, 201]
    assert await counts(pg) == {"PurchaseRequest": 1, "PurchaseOwnership": 1, "PurchaseRequestCreation": 1, "OrderRequestLink": 0}


async def test_pg_creation_two_company_isolation(plan_pg):
    pg = plan_pg
    other = await pg.api.post("/accounting/organizations", json={"name": "Other", "unp": "999999914"})
    assert other.status_code == 201
    other_id = other.json()["id"]
    body = command()
    first = await create_request(pg, body)
    second = await pg.api.post(f"/procurement/organizations/{other_id}/requests", json=body, headers=HEADERS)
    assert second.status_code == 201 and second.json()["request_id"] != first["request_id"]
    cross = await pg.api.patch(f"/procurement/organizations/{other_id}/requests/{first['request_id']}/stage", headers=HEADERS, json={"expected_stage": "need", "stage": "sourcing"})
    assert cross.status_code == 409
    for org, expected in ((pg.org, first["request_id"]), (other_id, second.json()["request_id"])):
        listed = await pg.api.get(f"/procurement/organizations/{org}/owned-sources?kind=request")
        assert [x["id"] for x in listed.json()["items"]] == [expected]
    pg.evidence["after"] = await counts(pg)


@pytest.mark.parametrize("replay", [False, True])
@pytest.mark.parametrize("revoke", [{"status": "suspended"}, {"role": "sales"}])
async def test_pg_retained_oidc_user_revoked_during_wait(plan_pg, replay, revoke):
    pg = plan_pg
    body = command()
    if replay:
        await create_request(pg, body)
    async with pg.factory() as session:
        session.add(User(username="issuer", full_name="Synthetic", keycloak_user_id="issuer", role="director", status="active"))
        await session.commit()
    before = await counts(pg)
    results = await schedule(pg, ("POST", pg.prefix + "/requests", command()), ("POST", pg.prefix + "/requests", body), revoke=revoke)
    assert [x["status"] for x in results] == [201, 403]
    after = await counts(pg)
    assert after["PurchaseRequestCreation"] == before["PurchaseRequestCreation"] + 1
    trace = pg.evidence["locks"][-1]
    assert trace["cached_before"]["role"] == "director"
    assert trace["cached_before"]["python_id"] == trace["cached_after"]["python_id"]
    for field, value in revoke.items():
        assert trace["cached_after"][field] == value
    pg.evidence.update(before=before, after=after)

async def raw_creation(pg, case):
    """Fresh, mutually consistent source/owner for every fault, never a duplicate."""
    body = command()
    if case.startswith("date:"):
        body["document"]["due_date"] = case[5:]
    if case == "outer-whitespace":
        body["document"]["supplier"] = " Supplier "
    if case == "nbsp-supplier":
        body["document"]["supplier"] = "\u00a0Поставщик\u00a0"
    if case == "control-item":
        body["document"]["item"] = "\x1cДеталь\x1f"
    if case == "nbsp-evidence":
        body["ownership_evidence"] = "\u00a0Решение\u00a0"
    d = body["document"]
    async with pg.factory() as session:
        row = PurchaseRequest(number="RAW-" + body["request_key"], supplier=d["supplier"], item=d["item"], qty=d["qty"], amount=d["amount"], due_date=d["due_date"], stage="need", origin="deficit" if case == "origin-deficit" else "")
        session.add(row)
        await session.flush()
        owner = PurchaseOwnership(organization_id=pg.other_org if case == "foreign-organization" else pg.org, kind="request", source_id=row.id,
            snapshot={"number": row.number, "supplier": d["supplier"], "supplier_id": None, "item": d["item"], "quantity": str(d["qty"]), "planned_amount": d["amount"], "due_date": d["due_date"]}, evidence=body["ownership_evidence"], actor="issuer")
        session.add(owner)
        await session.flush()
        ownership_id = owner.id
        if case == "foreign-owner":
            other = PurchaseRequest(number="OTHER-" + body["request_key"], supplier=d["supplier"], item=d["item"], qty=d["qty"], amount=d["amount"])
            session.add(other)
            await session.flush()
            wrong = PurchaseOwnership(organization_id=pg.org, kind="request", source_id=other.id, snapshot=owner.snapshot, evidence=owner.evidence, actor="issuer")
            session.add(wrong)
            await session.flush()
            ownership_id = wrong.id
        result = {"organization_id": pg.org, "request_key": body["request_key"], "request_id": row.id, "ownership_id": ownership_id, "number": row.number, "stage": "need"}
        digest = request_command_hash(body)
        command_json = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        if case == "qty-exponent":
            command_json = command_json.replace('"qty":3', '"qty":3e0')
            assert '"qty":3e0' in command_json
        if case == "null-command":
            command_json = None
        if case == "malformed-command":
            command_json = '[]'
        if case == "tampered-hash":
            digest = "0" * 64
        if case == "tampered-result":
            result["stage"] = "po"
        params = {"org": pg.org, "key": body["request_key"], "request": row.id, "owner": ownership_id, "command": command_json, "digest": digest, "result": None if case == "null-result" else json.dumps(result)}
        statement = text("INSERT INTO procurement.purchase_request_creation (organization_id,request_key,request_id,ownership_id,command,command_hash,result,actor) VALUES (:org,:key,:request,:owner,CAST(:command AS json),:digest,CAST(:result AS json),'issuer')")
        if case == "valid":
            await session.execute(statement, params)
            await session.commit()
            return {"case": case, "accepted": True}
        try:
            await session.execute(statement, params)
            await session.commit()
        except DBAPIError as exc:
            state = getattr(exc.orig, "sqlstate", None)
            assert state != "23505", "Uniqueness failure is not evidence of the creation guard"
            assert "purchase request creation" in str(exc).lower() or state in {"22007", "22008"}, str(exc)
            await session.rollback()
            return {"case": case, "sqlstate": state, "error": str(exc.orig)}
        raise AssertionError(f"Creation SQL guard accepted invalid case: {case}")


async def test_pg_creation_raw_sql_guards(plan_pg):
    pg = plan_pg
    other = await pg.api.post("/accounting/organizations", json={"name": "Other raw guard company", "unp": "999999915"})
    assert other.status_code == 201
    pg.other_org = other.json()["id"]
    pg.evidence["raw_sql"] = [await raw_creation(pg, "valid")]
    for case in ["date:infinity", "date:-infinity", "date:10000-01-01", "date:2026-02-30", "qty-exponent", "null-command", "malformed-command", "foreign-owner", "foreign-organization", "tampered-hash", "tampered-result", "null-result", "origin-deficit", "outer-whitespace", "nbsp-supplier", "control-item", "nbsp-evidence"]:
        pg.evidence["raw_sql"].append(await raw_creation(pg, case))
    before = await counts(pg)
    for sql in ["UPDATE procurement.purchase_request_creation SET actor='changed'", "DELETE FROM procurement.purchase_request_creation", "TRUNCATE procurement.purchase_request_creation"]:
        async with pg.factory() as session:
            with pytest.raises(DBAPIError, match="immutable") as rejected:
                await session.execute(text(sql))
            await session.rollback()
            pg.evidence["raw_sql"].append({"sql": sql, "error": str(rejected.value.orig)})
    assert await counts(pg) == before
    assert before["PurchaseRequestCreation"] == 1
