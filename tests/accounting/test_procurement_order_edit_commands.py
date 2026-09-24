"""Durable editor protocol using real validators and ephemeral SQLite ASGI."""

from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, update

from core.domain.models import OutboxEvent, Sku
from modules.accounting.models import AccessGrant
from modules.procurement import order_edit_commands as commands
from modules.procurement.models import PurchaseOrderLine
from tests.accounting.test_procurement_scoped_reads import setup_routes, state  # noqa: F401
from tests.accounting.test_procurement_scoped_reads import source as _source

source = _source
pytestmark = pytest.mark.asyncio


def command(order_id, action="add_line", payload=None):
    return {
        "version": 1,
        "request_key": str(uuid4()),
        "order_id": order_id,
        "action": action,
        "payload": payload
        if payload is not None
        else {
            "sku_code": "NEW",
            "qty": "1.00",
            "goods_value_byn": "2.00",
            "weight": "0.000",
            "volume": "0.0000",
        },
    }


def url(book, source, reconcile=False):
    return f"/procurement/organizations/{book[0]}/orders/{source[0]}/edit-commands" + (
        "/reconcile" if reconcile else ""
    )


ACTIONS = ["add_line", "delete_line", "header", "status", "plan"]


def payload(action, line):
    return {
        "delete_line": {"line_id": line},
        "header": {"freight_byn": "7.13"},
        "status": {"status": "ordered"},
        "plan": {"transport_method_code": "truck", "target_arrival_date": "2026-12-01"},
    }.get(action)


@pytest.mark.parametrize("action", ACTIONS)
async def test_exact_replay_and_reconcile_preserve_effect(client, db, book, source, action):
    cmd = command(source[0], action, payload(action, source[1]))
    first = await client.post(url(book, source), json=cmd)
    assert first.status_code == 200, first.text
    assert first.json()["outcome"] == "applied"
    before = await state(db, source[0])
    events = (await db.scalars(select(OutboxEvent.id))).all()
    for target in [url(book, source), url(book, source, True)]:
        again = await client.post(target, json=cmd)
        assert again.status_code == first.status_code and again.content == first.content
        assert await state(db, source[0]) == before
        assert (await db.scalars(select(OutboxEvent.id))).all() == events
    assert await db.scalar(select(func.count()).select_from(commands.PurchaseOrderEditCommand)) == 1


async def test_save_batches_changes_in_one_receipt_and_replays_without_writes(client, db, book, source):
    changes = {"add_line": command(source[0])["payload"],
               "header": {"freight_byn": "7.13"},
               "plan": {"transport_method_code": "truck", "target_arrival_date": "2026-12-01"},
               "status": {"status": "ordered"}}
    cmd = command(source[0], "save", changes)
    saved = await client.post(url(book, source), json=cmd)
    assert saved.status_code == 200, saved.text
    assert set(saved.json()["effect"]) == set(changes)
    assert await db.scalar(select(func.count()).select_from(commands.PurchaseOrderEditCommand)) == 1
    history = (await client.get(f"/procurement/organizations/{book[0]}/orders/{source[0]}/edit-history")).json()
    assert len(history["items"]) == 1
    assert [change["field"] for change in history["items"][0]["changes"]] == [
        f"lines/{saved.json()['effect']['add_line']['line']['id']}", "freight_byn", "plan", "status"]
    before = await state(db, source[0])
    events = (await db.scalars(select(OutboxEvent.id))).all()
    assert (await client.post(url(book, source), json=cmd)).content == saved.content
    assert (await client.post(url(book, source, True), json=cmd)).content == saved.content
    assert await state(db, source[0]) == before
    assert (await db.scalars(select(OutboxEvent.id))).all() == events


async def test_save_later_step_failure_rolls_back_earlier_changes(client, db, book, source, monkeypatch):
    before = await state(db, source[0])
    async def broken_plan(*_args, **_kwargs):
        raise HTTPException(409, "Injected plan failure")
    monkeypatch.setattr(commands.routes, "apply_order_plan", broken_plan)
    cmd = command(source[0], "save", {"add_line": command(source[0])["payload"],
               "header": {"freight_byn": "7.13"},
               "plan": {"transport_method_code": "truck", "target_arrival_date": "2026-12-01"}})
    failed = await client.post(url(book, source), json=cmd)
    assert failed.status_code == 409
    db.expire_all()
    assert await state(db, source[0]) == before
    assert await db.scalar(select(func.count()).select_from(commands.PurchaseOrderEditCommand)) == 0


@pytest.mark.parametrize("action", ACTIONS)
async def test_reconcile_tombstone_blocks_original_arriving_later(client, db, book, source, action):
    cmd = command(source[0], action, payload(action, source[1]))
    before = await state(db, source[0])
    closed = await client.post(url(book, source, True), json=cmd)
    assert closed.status_code == 409 and closed.json()["code"] == "command_abandoned"
    assert closed.json()["no_business_write"] is True
    late = await client.post(url(book, source), json=cmd)
    assert late.content == closed.content and late.status_code == 409
    assert await state(db, source[0]) == before
    assert (await db.scalars(select(OutboxEvent))).all() == []


async def test_replay_add_survives_later_delete_without_resurrection(client, db, book, source):
    add = command(source[0])
    original = await client.post(url(book, source), json=add)
    line_id = original.json()["effect"]["line"]["id"]
    delete = command(source[0], "delete_line", {"line_id": line_id})
    removed = await client.post(url(book, source), json=delete)
    assert removed.status_code == 200
    assert removed.json()["effect"]["line"] == original.json()["effect"]["line"]
    for cmd, saved in [(add, original), (delete, removed)]:
        replay = await client.post(url(book, source), json=cmd)
        assert replay.content == saved.content
    assert await db.get(PurchaseOrderLine, line_id) is None


async def test_order_history_shows_actor_time_and_exact_header_change(client, book, source):
    cmd = command(source[0], "header", {"freight_byn": "7.13"})
    saved = await client.post(url(book, source), json=cmd)
    assert saved.status_code == 200, saved.text
    history_url = f"/procurement/organizations/{book[0]}/orders/{source[0]}/edit-history"
    history = await client.get(history_url)
    assert history.status_code == 200, history.text
    body = history.json()
    assert body["organization_id"] == book[0]
    assert body["order_id"] == source[0]
    assert body["number"]
    assert body["next_after_id"] is None
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["changed_by"] == "tester"
    assert item["changed_at"]
    assert item["action"] == "header"
    assert item["changes"] == [{"field": "freight_byn", "before": "2.00", "after": "7.13"}]
    assert (await client.get(history_url, params={"after_id": item["id"]})).json()["items"] == []
    await client.post(url(book, source), json=cmd)
    assert len((await client.get(history_url)).json()["items"]) == 1
    foreign = await client.get(f"/procurement/organizations/{book[0] + 1}/orders/{source[0]}/edit-history")
    assert foreign.status_code in {403, 404, 409}
    assert "tester" not in foreign.text


async def test_selected_sku_is_checked_and_snapshotted_in_edit_receipt(client, db, book, source):
    sku = Sku(code="SKU-CATALOG-1", title="Аккумулятор из справочника", unit="шт", is_active=True)
    db.add(sku)
    await db.commit()
    options = await client.get(f"/procurement/organizations/{book[0]}/sku-options", params={"q": "CATALOG"})
    assert options.status_code == 200, options.text
    assert options.json()["items"] == [{"id": sku.id, "code": sku.code,
                                        "title": sku.title, "unit": sku.unit}]
    payload = {"sku_code": sku.code, "sku_id": sku.id, "sku_title": sku.title,
               "sku_unit": sku.unit, "qty": "1.00", "goods_value_byn": "2.00",
               "weight": "0.000", "volume": "0.0000"}
    selected = command(source[0], "add_line", payload)
    saved = await client.post(url(book, source), json=selected)
    assert saved.status_code == 200, saved.text
    history = (await client.get(
        f"/procurement/organizations/{book[0]}/orders/{source[0]}/edit-history")).json()
    assert history["items"][0]["changes"][0]["after"]["catalog_snapshot"] == {
        "sku_id": sku.id, "title": "Аккумулятор из справочника", "unit": "шт"}
    sku.title = "Новое название"
    await db.commit()
    assert (await client.post(url(book, source), json=selected)).json() == saved.json()
    stale = await client.post(url(book, source), json=command(source[0], "add_line", payload))
    assert stale.status_code == 409
    assert stale.json()["code"] == "sku_catalog_changed"
    assert stale.json()["no_business_write"] is True


@pytest.mark.parametrize("action", ["header", "status", "plan"])
async def test_historical_result_not_recomputed_from_later_state(client, db, book, source, action):
    first = command(source[0], action, payload(action, source[1]))
    response = await client.post(url(book, source), json=first)
    new_payload = {
        "header": {"freight_byn": "9.99"},
        "status": {"status": "shipped"},
        "plan": {"transport_method_code": "container", "target_arrival_date": "2027-01-01"},
    }[action]
    assert (
        await client.post(url(book, source), json=command(source[0], action, new_payload))
    ).status_code == 200
    before = await state(db, source[0])
    assert (await client.post(url(book, source), json=first)).content == response.content
    assert await state(db, source[0]) == before


@pytest.mark.parametrize("change", ["payload", "action", "order"])
async def test_uuid_conflict_is_not_terminal_evidence(client, db, book, source, change):
    cmd = command(source[0])
    assert (await client.post(url(book, source), json=cmd)).status_code == 200
    changed = deepcopy(cmd)
    if change == "payload":
        changed["payload"]["qty"] = "2.00"
    if change == "action":
        changed.update(action="header", payload={"freight_byn": "4.00"})
    if change == "order":
        changed["order_id"] += 1
    before = await state(db, source[0])
    response = await client.post(url(book, source), json=changed)
    assert response.status_code == 409 and "outcome" not in response.json()
    assert await state(db, source[0]) == before


async def test_another_chief_cannot_read_or_close_first_actors_key(client, db, book, source):
    from core.services.auth import CurrentUser, get_current_user

    cmd = command(source[0])
    first = await client.post(url(book, source), json=cmd)
    assert first.status_code == 200
    db.add(AccessGrant(organization_id=book[0], subject="second", role="chief"))
    await db.commit()
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        "second", ["director"]
    )
    client.headers["X-Expected-Principal"] = "second"
    for target in [url(book, source), url(book, source, True)]:
        response = await client.post(target, json=cmd)
        assert response.status_code == 403 and "effect" not in response.json()


@pytest.mark.parametrize("action", ACTIONS)
async def test_fault_after_effect_and_receipt_rolls_everything_back(
    client, db, book, source, monkeypatch, action
):
    cmd = command(source[0], action, payload(action, source[1]))
    before = await state(db, source[0])
    original = commands.persist

    async def fail(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("fault before commit")

    monkeypatch.setattr(commands, "persist", fail)
    with pytest.raises(RuntimeError, match="before commit"):
        await client.post(url(book, source), json=cmd)
    assert await state(db, source[0]) == before
    assert (await db.scalars(select(commands.PurchaseOrderEditCommand))).all() == []
    assert (await db.scalars(select(OutboxEvent))).all() == []
    monkeypatch.setattr(commands, "persist", original)
    closed = await client.post(url(book, source, True), json=cmd)
    assert closed.status_code == 409
    assert (await client.post(url(book, source), json=cmd)).content == closed.content
    assert await state(db, source[0]) == before


async def test_corrupt_stored_effect_blocks_replay(client, db, book, source):
    cmd = command(source[0])
    first = await client.post(url(book, source), json=cmd)
    forged = first.json()
    forged["effect"]["line"]["qty"] = "999.00"
    await db.execute(update(commands.PurchaseOrderEditCommand).values(result=forged))
    await db.commit()
    response = await client.post(url(book, source), json=cmd)
    assert response.status_code == 409 and "outcome" not in response.json()


async def test_business_rejection_is_durable(client, db, book, source):
    cmd = command(source[0], "delete_line", {"line_id": 999999})
    first = await client.post(url(book, source), json=cmd)
    assert first.status_code == 409 and first.json()["code"] == "line_unavailable"
    assert (await client.post(url(book, source, True), json=cmd)).content == first.content
    row = await db.scalar(select(commands.PurchaseOrderEditCommand))
    row.actor = "changed"
    with pytest.raises(ValueError):
        await db.flush()
    await db.rollback()


@pytest.mark.parametrize(
    "method,suffix,body",
    [
        ("POST", "/lines", {"sku_code": "B", "qty": "1.00"}),
        ("DELETE", "/lines/{line}", None),
        ("PATCH", "/header", {"freight_byn": "1.00"}),
        ("PATCH", "", {"status": "ordered"}),
        ("POST", "/plan", {"transport_method_code": "truck", "target_arrival_date": "2026-12-01"}),
    ],
)
async def test_authorized_legacy_writers_do_not_bypass_receipts(
    client, db, source, method, suffix, body
):
    before = await state(db, source[0])
    response = await client.request(
        method,
        f"/procurement/orders/{source[0]}" + suffix.format(line=source[1]),
        **({"json": body} if body else {}),
    )
    assert response.status_code == 410 and set(response.json()) == {"detail"}
    assert await state(db, source[0]) == before
