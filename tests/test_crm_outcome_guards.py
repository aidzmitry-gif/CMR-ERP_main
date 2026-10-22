"""Standalone own deal closure must use canonical audited transitions."""
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from core.domain.models import OutboxEvent
from modules.accounting.models import AccessGrant, Organization
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.deal_loss import (
    DealLossRequest,
    DealLossResolution,
    available_kinds,
    connection_kinds,
    kind_map,
)
from modules.sales.models import Deal, LossReason, Stage
from tests.test_crm_client_contacts import FOREIGN, OWN, selected_buyer_id, setup_client


async def loss_fixture(session, deal_id):
    """Authorization model only in this test's disposable in-memory SQLite DB."""
    org = Organization(name="Synthetic closure book", unp="190000007")
    session.add(org)
    await session.flush()
    org_id = org.id
    session.add_all([
        AccessGrant(organization_id=org_id, subject=h["X-User"], role="reader")
        for h in (OWN, FOREIGN)
    ])
    session.add(DealOwnership(deal_id=deal_id, organization_id=org_id,
                              snapshot={}, evidence="Synthetic unit fixture", actor=OWN["X-User"]))
    session.add(LossReason(code="price", title="Synthetic price reason", active=True))
    await session.commit()
    return org_id


async def loss_command(api, org_id, deal_id, **changes):
    preview = await api.get(f"/sales/organizations/{org_id}/deals/{deal_id}/loss-preview", headers=OWN)
    assert preview.status_code == 200, preview.text
    return {"organization_id": org_id, "request_key": str(uuid4()), "reason_code": "price",
            "expected_composition_digest": preview.json()["composition_digest"], **changes}


async def loss_rows(session):
    return [await session.scalar(select(func.count()).select_from(model))
            for model in (DealLossRequest, DealLossResolution, OutboxEvent)]


@pytest.mark.parametrize("stage", ["won", "lost", "rp_won", "missing"])
async def test_standalone_creation_rejects_terminal_or_foreign_stage(api, session, stage):
    client_id = await setup_client(api, session)
    response = await api.post("/sales/deals", headers=OWN, json={
        "number": "GUARD-CREATE", "title": "Synthetic", "counterparty": "ignored",
        "crm_client_id": client_id, "counterparty_id": await selected_buyer_id(session, client_id), "stage": stage})
    assert response.status_code == (409 if stage == "lost" else 422), response.text
    if stage == "lost":
        assert response.json()["detail"] == "Create an open deal before requesting loss"


async def test_own_close_reopen_requires_canonical_route_and_preserves_deadlines(api, session):
    client_id = await setup_client(api, session)
    created = await api.post("/sales/deals", headers=OWN, json={
        "number": "OUTCOME-OWN", "title": "Synthetic", "counterparty": "ignored",
        "crm_client_id": client_id, "counterparty_id": await selected_buyer_id(session, client_id),
        "next_step": "Follow up", "next_step_at": "2026-09-15T07:00:00",
        "ship_deadline": "2026-09-20", "expected_close_date": "2026-09-18"})
    assert created.status_code == 201, created.text
    deal = created.json()
    deal_id = deal["id"]
    path = f"/sales/deals/{deal_id}"
    org_id = await loss_fixture(session, deal_id)
    headers = {**OWN, "X-Expected-Principal": OWN["X-User"]}
    command = await loss_command(api, org_id, deal_id)
    initial_detail = (await api.get(path, headers=OWN)).json()
    for patch in [{"stage": "won"}, {"stage": "lost"}, {"closed_date": "01.01.2000"}]:
        denied = await api.patch(path, headers=OWN, json=patch)
        assert denied.status_code == (409 if patch.get("stage") == "lost" else 422), denied.text
        assert (await api.get(path, headers=OWN)).json() == initial_detail
    for suffix in ["win", "lose"]:
        response = await api.post(path + "/" + suffix, headers={**FOREIGN, "X-Expected-Principal": FOREIGN["X-User"]}, json=command)
        assert response.status_code == 404, response.text
    assert (await api.post(path + "/lose", headers=headers, json={**command, "reason_code": ""})).status_code == 422
    won = await api.post(path + "/win", headers=OWN)
    assert won.status_code == 200, won.text
    assert won.json()["stage"] == "won" and won.json()["closed_date"]
    assert (await api.post(path + "/win", headers=OWN)).status_code == 409
    assert (await api.patch(path, headers=OWN, json={"stage": "qual", "closed_date": "01.01.2000"})).status_code == 422
    reopened = await api.patch(path, headers=OWN, json={"stage": "qual"})
    assert reopened.status_code == 200 and reopened.json()["closed_date"] is None
    command = await loss_command(api, org_id, deal_id, comment="Synthetic reason", finalize_if_empty=True)
    lost = await api.post(path + "/lose", headers=headers, json=command)
    assert lost.status_code == 200, lost.text
    assert lost.json()["state"] == "finalized" and lost.json()["resolution"]["action"] == "finalized"
    detail = (await api.get(path, headers=OWN)).json()
    assert detail["stage"] == "lost" and detail["lost_reason_code"] == "price"
    assert detail["lost_comment"] == "Synthetic reason" and detail["closed_date"]
    replay = await api.post(path + "/lose", headers=headers, json=command)
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    assert replay.json()["resolution"] == lost.json()["resolution"]
    denied = await api.post(path + "/lose", headers=headers, json={**command, "request_key": str(uuid4())})
    assert denied.status_code == 409 and denied.json()["detail"] == "An open deal and configured lost stage are required"
    for field in ["next_step", "next_step_at", "ship_deadline", "expected_close_date"]:
        assert detail[field] == deal[field]
    history = (await api.get(path + "/history", headers=OWN)).json()
    assert [row["to_stage"] for row in history][-3:] == ["won", "qual", "lost"]
    events = (await session.scalars(select(OutboxEvent).where(
        OutboxEvent.event_type.in_(["sales.deal.won", "sales.deal.loss_requested", "sales.deal.loss_finalized"])))).all()
    assert sorted(row.event_type for row in events if row.payload.get("deal_id") == deal_id) == [
        "sales.deal.loss_finalized", "sales.deal.loss_requested", "sales.deal.won"]
    assert (await loss_rows(session))[:2] == [1, 1]


async def test_numeric_director_and_unlinked_own_cannot_bypass_closure(api, session):
    client_id = await setup_client(api, session)
    base = {"number": "DIRECTOR-NUMERIC", "title": "Synthetic", "counterparty": "ignored",
            "crm_client_id": client_id, "counterparty_id": await selected_buyer_id(session, client_id), "owner_id": 651, "stage": "won"}
    assert (await api.post("/sales/deals", json=base)).status_code == 422
    response = await api.post("/sales/deals", json={**base, "stage": "new"})
    assert response.status_code == 201, response.text
    denied = await api.patch(f"/sales/deals/{response.json()['id']}", json={"stage": "lost"})
    assert denied.status_code == 409 and denied.json()["detail"] == "Lost stage requires the deal loss coordinator"
    unlinked = {"number": "OWN-UNLINKED", "title": "Synthetic", "counterparty": "Legacy", "stage": "won"}
    assert (await api.post("/sales/deals", headers=OWN, json=unlinked)).status_code == 422
    created = await api.post("/sales/deals", headers=OWN, json={
        **unlinked, "counterparty_id": base["counterparty_id"], "stage": "cond_lost"})
    assert created.status_code == 201, created.text
    detail = created.json()
    assert detail["counterparty_id"] == base["counterparty_id"] and detail["owner_id"] == 651
    assert detail["crm_client_id"] is None and detail["stage"] == "cond_lost" and detail["closed_date"] is None


async def test_disabled_terminal_stage_cannot_be_invented_by_closure(api, session):
    client_id = await setup_client(api, session)
    response = await api.post("/sales/deals", headers=OWN, json={
        "number": "DISABLED-TERMINAL", "title": "Synthetic", "counterparty": "ignored",
        "crm_client_id": client_id, "counterparty_id": await selected_buyer_id(session, client_id)})
    assert response.status_code == 201, response.text
    deal_id = response.json()["id"]
    path = f"/sales/deals/{deal_id}"
    org_id = await loss_fixture(session, deal_id)
    command = await loss_command(api, org_id, deal_id, finalize_if_empty=True)
    session.add(Stage(code="new", title="Disabled", kind="normal", funnel="new_clients", is_active=False))
    await session.commit()
    before = await loss_rows(session)
    original = (await api.get(path, headers=OWN)).json()
    context = await api.get(path + "/loss-context", headers=OWN)
    assert context.status_code == 200 and context.json()["lost_stage"] is None
    preview = await api.get(f"/sales/organizations/{org_id}/deals/{deal_id}/loss-preview", headers=OWN)
    assert preview.status_code == 200 and preview.json()["snapshot"]["lost_stage"] is None
    won = await api.post(path + "/win", headers=OWN)
    assert won.status_code == 422 and won.json()["detail"] == "В воронке нет активной стадии успеха"
    # Both a pre-disable and fresh preview must fail at the actual stage guard.
    for body in [command, {**command, "request_key": str(uuid4()), "expected_composition_digest": preview.json()["composition_digest"]}]:
        denied = await api.post(path + "/lose", headers={**OWN, "X-Expected-Principal": OWN["X-User"]}, json=body)
        assert denied.status_code == 409 and denied.json()["detail"] == "An open deal and configured lost stage are required"
        assert (await api.get(path, headers=OWN)).json() == original
        assert await loss_rows(session) == before


async def test_disabled_reason_catalog_cannot_accept_arbitrary_reason(api, session):
    client_id = await setup_client(api, session)
    response = await api.post("/sales/deals", headers=OWN, json={
        "number": "DISABLED-REASON", "title": "Synthetic", "counterparty": "ignored",
        "crm_client_id": client_id, "counterparty_id": await selected_buyer_id(session, client_id)})
    assert response.status_code == 201, response.text
    deal_id = response.json()["id"]
    path = f"/sales/deals/{deal_id}"
    org_id = await loss_fixture(session, deal_id)
    command = await loss_command(api, org_id, deal_id, finalize_if_empty=True)
    reason = await session.scalar(select(LossReason).where(LossReason.code == "price"))
    assert reason is not None and reason.active is True
    reason.active = False
    await session.commit()
    before = await loss_rows(session)
    original = (await api.get(path, headers=OWN)).json()
    for reason_code in ["price", "invented"]:
        denied = await api.post(path + "/lose", headers={**OWN, "X-Expected-Principal": OWN["X-User"]},
                                json={**command, "request_key": str(uuid4()), "reason_code": reason_code})
        assert denied.status_code == 422 and denied.json()["detail"] == "Unknown loss reason"
        assert (await api.get(path, headers=OWN)).json() == original
        assert await loss_rows(session) == before


@pytest.mark.parametrize("configured", [False, True], ids=["empty-canonical", "all-inactive"])
async def test_availability_never_weakens_lost_write_guards(api, session, configured):
    await setup_client(api, session)
    if configured:
        session.add(Stage(code="new", title="Disabled", kind="normal", funnel="new_clients", is_active=False))
        await session.commit()
    available = await available_kinds(session, "new_clients")
    assert available == {} if configured else available.get("lost") == "lost"
    assert (await kind_map(session, "new_clients"))["lost"] == "lost"
    conn = await session.connection()
    assert (await conn.run_sync(lambda c: connection_kinds(c, "new_clients")))["lost"] == "lost"
    for headers in [OWN, {"X-User-Roles": "director"}]:
        denied = await api.post("/sales/deals", headers=headers, json={
            "number": "BYPASS", "title": "Synthetic", "counterparty": "Synthetic", "stage": "lost"})
        assert denied.status_code == 409 and denied.json()["detail"] == "Create an open deal before requesting loss"
    before = await loss_rows(session)
    session.add(Deal(number="DIRECT-INSERT", title="Synthetic", counterparty="Synthetic", stage="lost"))
    with pytest.raises(ValueError, match="A new deal cannot bypass the loss coordinator"):
        await session.commit()
    await session.rollback()
    assert await session.scalar(select(func.count()).select_from(Deal)) == 0
    deal = Deal(number="DIRECT-UPDATE", title="Synthetic", counterparty="Synthetic", stage="new")
    session.add(deal)
    await session.commit()
    deal_id = deal.id
    deal.stage = "lost"
    with pytest.raises(ValueError, match="Lost transition requires an exact durable loss resolution"):
        await session.commit()
    await session.rollback()
    assert (await session.get(Deal, deal_id)).stage == "new"
    assert await session.scalar(select(func.count()).select_from(Deal)) == 1
    assert await loss_rows(session) == before
