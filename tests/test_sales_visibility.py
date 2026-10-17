"""Regression contract for server-enforced per-employee deal visibility."""
from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from core.domain.models import Counterparty, User
from modules.sales.models import CallLog, CrmClient, CrmTimelineAttachment, CrmTimelineComment


def _sales_headers(username: str) -> dict[str, str]:
    return {"X-User": username, "X-User-Roles": "sales"}


async def _create(api, number: str, **extra) -> dict:
    response = await api.post(
        "/sales/deals",
        json={"number": number, "title": number, "counterparty": "Тест", **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_timeline_comments_follow_deal_visibility(api, session, tmp_path, monkeypatch):
    from modules.sales import timeline_storage

    monkeypatch.setattr(timeline_storage, "storage_root", lambda: tmp_path)
    session.add_all([
        User(username="timeline-owner", full_name="Owner", employee_id=311,
             department="Продажи", role="sales", status="active", deal_visibility="own"),
        User(username="timeline-other", full_name="Other", employee_id=312,
             department="Продажи", role="sales", status="active"),
    ])
    await session.commit()
    own = await _create(api, "COMMENT-VIS-OWN", owner_id=311)
    other = await _create(api, "COMMENT-VIS-OTHER", owner_id=312)
    own_comment = CrmTimelineComment(
        entity_type="deal", deal_id=own["id"], body="own comment",
        author_display="Owner", created_at=datetime(2025, 1, 1),
    )
    other_comment = CrmTimelineComment(
        entity_type="deal", deal_id=other["id"], body="private comment",
        author_display="Other", created_at=datetime(2025, 1, 1),
    )
    session.add_all([
        own_comment,
        other_comment,
    ])
    await session.flush()
    stored = timeline_storage.store_attachment([b"private file"], root=tmp_path)
    session.add_all([
        CrmTimelineAttachment(
            comment_id=own_comment.id, source_ref="test:own:attachment",
            sha256=stored.sha256, size_bytes=stored.size_bytes, filename="own.txt",
            content_type="text/plain", storage_path=stored.storage_path,
        ),
        CrmTimelineAttachment(
            comment_id=other_comment.id, source_ref="test:other:attachment",
            sha256=stored.sha256, size_bytes=stored.size_bytes, filename="other.txt",
            content_type="text/plain", storage_path=stored.storage_path,
        ),
    ])
    await session.commit()
    headers = _sales_headers("timeline-owner")
    own_response = await api.get(f"/sales/deals/{own['id']}/timeline/comments", headers=headers)
    assert own_response.status_code == 200
    assert [row["body"] for row in own_response.json()] == ["own comment"]
    own_attachments = await api.get(
        f"/sales/deals/{own['id']}/timeline/comments/{own_comment.id}/attachments",
        headers=headers,
    )
    assert own_attachments.status_code == 200 and len(own_attachments.json()) == 1
    own_download = await api.get(
        f"/sales/deals/{own['id']}/timeline/comments/{own_comment.id}/attachments/"
        f"{own_attachments.json()[0]['id']}/download",
        headers=headers,
    )
    assert own_download.status_code == 200 and own_download.content == b"private file"
    assert (await api.get(
        f"/sales/deals/{other['id']}/timeline/comments/{other_comment.id}/attachments",
        headers=headers,
    )).status_code == 404
    assert (await api.get(
        f"/sales/deals/{other['id']}/timeline/comments/{other_comment.id}/attachments/"
        f"{own_attachments.json()[0]['id']}/download",
        headers=headers,
    )).status_code == 404
    assert (await api.get(f"/sales/deals/{other['id']}/timeline/comments",
                          headers=headers)).status_code == 404
    assert (await api.get(f"/sales/deals/{own['id']}/timeline/comments",
                          headers={"X-User": "timeline-owner", "X-User-Roles": "hr"})).status_code == 403
    assert (await api.get(
        f"/sales/deals/{own['id']}/timeline/comments/{own_comment.id}/attachments",
        headers={"X-User": "timeline-owner", "X-User-Roles": "hr"},
    )).status_code == 403


@pytest.mark.asyncio
async def test_calls_follow_deal_scope_and_unlinked_confirmed_owner(api, session):
    session.add_all([
        User(username="call-owner", full_name="Call Owner", employee_id=301,
             department="Продажи", role="sales", status="active", deal_visibility="own"),
        User(username="call-other", full_name="Call Other", employee_id=302,
             department="Продажи", role="sales", status="active"),
    ])
    await session.commit()
    own = await _create(api, "CALL-VIS-OWN", owner_id=301)
    other = await _create(api, "CALL-VIS-OTHER", owner_id=302)
    calls = [
        CallLog(call_id="VIS-LINK-OWN", deal_id=own["id"], owner_id=302),
        CallLog(call_id="VIS-LINK-OTHER", deal_id=other["id"], owner_id=301),
        CallLog(call_id="VIS-UNLINK-OWN", owner_id=301),
        CallLog(call_id="VIS-UNLINK-OTHER", owner_id=302),
        CallLog(call_id="VIS-UNCONFIRMED", owner="Call Owner"),
    ]
    session.add_all(calls)
    await session.commit()
    headers = _sales_headers("call-owner")
    listed = await api.get("/sales/calls", headers=headers)
    assert listed.status_code == 200, listed.text
    assert {row["id"] for row in listed.json()} == {calls[0].id, calls[2].id}
    assert (await api.get(f"/sales/calls?deal_id={other['id']}", headers=headers)).status_code == 404
    assert len((await api.get("/sales/calls")).json()) == 5
    for call in (calls[1], calls[3], calls[4]):
        assert (await api.get(f"/sales/calls/{call.id}", headers=headers)).status_code == 404
        for action, payload in (("comment", {"comment": "forbidden"}),
                                ("result", {"result": "forbidden"}),
                                ("link-deal", {"deal_id": own["id"]})):
            assert (await api.post(f"/sales/calls/{call.id}/{action}", json=payload, headers=headers)).status_code == 404
    comment = await api.post(f"/sales/calls/{calls[0].id}/comment", json={"comment": "checked"}, headers=headers)
    assert comment.status_code == 200 and comment.json()["comment"] == "checked"
    result = await api.post(f"/sales/calls/{calls[0].id}/result", json={"result": "callback"}, headers=headers)
    assert result.status_code == 200 and result.json()["result"] == "callback"
    foreign_link = await api.post(f"/sales/calls/{calls[2].id}/link-deal", json={"deal_id": other["id"]}, headers=headers)
    assert foreign_link.status_code == 404
    created = await api.post(f"/sales/calls/{calls[2].id}/link-deal", json={"create": True}, headers=headers)
    assert created.status_code == 200, created.text
    deal = await api.get(f"/sales/deals/{created.json()['deal_id']}", headers=headers)
    assert deal.status_code == 200 and deal.json()["owner_id"] == 301
    from_visible = await api.post(f"/sales/calls/{calls[0].id}/link-deal", json={"create": True}, headers=headers)
    assert from_visible.status_code == 200, from_visible.text
    linked_deal = await api.get(f"/sales/deals/{from_visible.json()['deal_id']}", headers=headers)
    assert linked_deal.status_code == 200 and linked_deal.json()["owner_id"] == 301


@pytest.mark.asyncio
async def test_call_review_filters_and_client_link_use_distinct_authorized_ids(api, session):
    session.add_all([
        User(username="review-owner", full_name="Owner", employee_id=321,
             department="Продажи", role="sales", status="active", deal_visibility="own"),
        User(username="review-other", full_name="Other", employee_id=322,
             department="Продажи", role="sales", status="active", deal_visibility="own"),
    ])
    session.add(Counterparty(name="Unrelated master", unp="987654321"))
    await session.flush()
    cp = Counterparty(name="Synthetic 1C company", unp="123456789")
    session.add(cp)
    await session.flush()
    own_client = CrmClient(name=cp.name, name_key="review-owner-company", owner_id=321,
                           counterparty_id=cp.id, request_key="review-owner-key",
                           request_hash="owner-hash", created_by="test")
    other_client = CrmClient(name=cp.name, name_key="review-other-company", owner_id=322,
                             counterparty_id=cp.id, request_key="review-other-key",
                             request_hash="other-hash", created_by="test")
    session.add_all([own_client, other_client])
    await session.commit()
    assert cp.id != own_client.id
    deal = await _create(api, "REVIEW-LINKED", owner_id=321)
    calls = [
        CallLog(call_id="REVIEW-UNLINKED-OWN", counterparty_id=cp.id, owner_id=321),
        CallLog(call_id="REVIEW-LINKED-OWN", counterparty_id=cp.id,
                owner_id=321, deal_id=deal["id"]),
        CallLog(call_id="REVIEW-UNLINKED-OTHER", counterparty_id=cp.id, owner_id=322),
        CallLog(call_id="REVIEW-UNRELATED", owner_id=321),
    ]
    session.add_all(calls)
    await session.commit()

    owner_headers = _sales_headers("review-owner")
    own = await api.get(f"/sales/calls?counterparty_id={cp.id}&unlinked=true",
                        headers=owner_headers)
    assert own.status_code == 200, own.text
    assert [row["id"] for row in own.json()] == [calls[0].id]
    assert own.json()[0]["crm_client_id"] == own_client.id
    all_scope = await api.get(f"/sales/calls?counterparty_id={cp.id}&unlinked=true")
    assert all_scope.status_code == 200
    assert {row["id"] for row in all_scope.json()} == {calls[0].id, calls[2].id}
    assert all(row["crm_client_id"] is None for row in all_scope.json())
    assert (await api.get("/sales/calls?counterparty_id=0")).status_code == 422
    assert (await api.get(
        "/sales/calls?counterparty_id=9223372036854775808"
    )).status_code == 422


@pytest.mark.asyncio
async def test_all_scope_keeps_legacy_owner_and_confirms_employee_owner_id(api, session):
    session.add_all(
        [
            User(username="alice", full_name="Алиса CRM", employee_id=101, department="Продажи", role="sales", status="active"),
            User(username="bob", full_name="Боб CRM", employee_id=102, department="Продажи", role="sales", status="active"),
            User(username="finance", full_name="Финансы", employee_id=103, department="Финансы / офис", role="finance", status="active"),
        ]
    )
    await session.commit()

    legacy = await _create(api, "VIS-LEGACY", owner="Старый ответственный")
    assert legacy["owner"] == "Старый ответственный"
    assert legacy["owner_id"] is None

    confirmed = await _create(api, "VIS-CONFIRMED", owner="Подмена", owner_id=101)
    assert confirmed["owner_id"] == 101
    assert confirmed["owner"] == "Алиса CRM"

    unchanged = await api.patch(
        f"/sales/deals/{confirmed['id']}", json={"owner": "Алиса CRM"}
    )
    assert unchanged.status_code == 200
    assert unchanged.json()["owner_id"] == 101

    unconfirmed = await api.patch(
        f"/sales/deals/{confirmed['id']}", json={"owner": "Свободный текст"}
    )
    assert unconfirmed.status_code == 200
    assert unconfirmed.json()["owner"] == "Свободный текст"
    assert unconfirmed.json()["owner_id"] is None

    invalid = await api.patch(f"/sales/deals/{confirmed['id']}", json={"owner_id": 999})
    assert invalid.status_code == 422
    non_crm = await api.patch(f"/sales/deals/{confirmed['id']}", json={"owner_id": 103})
    assert non_crm.status_code == 422


@pytest.mark.asyncio
async def test_own_scope_enforces_visibility_and_runtime_switch(api, session):
    alice = User(
        username="alice", full_name="Алиса CRM", employee_id=101,
        department="Продажи", role="sales", status="active", deal_visibility="own",
    )
    session.add_all(
        [
            alice,
            User(
                username="bob", full_name="Боб CRM", employee_id=102,
                department="Продажи", role="sales", status="active", deal_visibility="all",
            ),
        ]
    )
    await session.commit()
    own = await _create(api, "VIS-OWN", owner_id=101)
    other = await _create(api, "VIS-OTHER", owner_id=102)
    legacy = await _create(api, "VIS-NO-OWNER", owner="Старый ответственный")
    headers = _sales_headers("alice")

    listed = await api.get("/sales/deals", headers=headers)
    assert listed.status_code == 200
    assert [deal["id"] for deal in listed.json()] == [own["id"]]
    board = await api.get("/sales/board", headers=headers)
    assert board.status_code == 200
    assert {deal["id"] for column in board.json()["stages"] for deal in column["deals"]} == {own["id"]}

    assert (await api.get(f"/sales/deals/{other['id']}", headers=headers)).status_code == 404
    assert (await api.get(f"/sales/deals/{legacy['id']}", headers=headers)).status_code == 404
    assert (
        await api.post(f"/sales/deals/{other['id']}/tasks", json={"title": "leak"}, headers=headers)
    ).status_code == 404
    assert (await api.get("/sales/skus", headers=headers)).status_code == 200
    assert (await api.get("/sales/prices/MISSING", headers=headers)).status_code == 200
    assert (await api.get("/sales/journal", headers=headers)).status_code == 403

    self_assigned = await api.post(
        "/sales/deals",
        json={"number": "VIS-SELF", "title": "self", "counterparty": "Тест", "owner": "Подмена"},
        headers=headers,
    )
    assert self_assigned.status_code == 201
    assert self_assigned.json()["owner_id"] == 101
    assert self_assigned.json()["owner"] == "Алиса CRM"
    assert (
        await api.patch(f"/sales/deals/{own['id']}", json={"owner_id": 102}, headers=headers)
    ).status_code == 403

    alice.deal_visibility = "all"
    await session.commit()
    assert (await api.get(f"/sales/deals/{other['id']}", headers=headers)).status_code == 200
    alice.deal_visibility = "own"
    await session.commit()
    assert (await api.get(f"/sales/deals/{other['id']}", headers=headers)).status_code == 404


async def _contact_access_users(session):
    session.add_all([
        User(username="contact-owner", full_name="Contact Owner", employee_id=201,
             department="Продажи", role="sales", status="active", deal_visibility="own"),
        User(username="contact-other", full_name="Contact Other", employee_id=202,
             department="Продажи", role="sales", status="active", deal_visibility="all"),
        User(username="contact-hr", full_name="Contact HR", department="HR",
             role="hr", status="active", deal_visibility="all"),
    ])
    await session.commit()


async def test_primary_contact_own_scope_preserves_foreign_contacts(api, session):
    from core.domain.models import Contact

    await _contact_access_users(session)
    headers = _sales_headers("contact-owner")
    for suffix, owner_id, expected in (("OWN", 201, 200), ("OTHER", 202, 404),
                                       ("UNASSIGNED", None, 404)):
        deal = await _create(api, f"CP-{suffix}", counterparty=f"Client {suffix}", owner_id=owner_id)
        first = await api.post(f"/sales/deals/{deal['id']}/contacts",
                               json={"full_name": "First", "is_primary": True})
        second = await api.post(f"/sales/deals/{deal['id']}/contacts",
                                json={"full_name": "Second"})
        assert first.status_code == second.status_code == 201
        response = await api.patch(f"/sales/contacts/{second.json()['id']}/primary", headers=headers)
        assert response.status_code == expected, response.text
        for created, was_primary in ((first, True), (second, False)):
            contact = await session.get(Contact, created.json()["id"])
            await session.refresh(contact)
            assert contact.is_primary == (not was_primary if expected == 200 else was_primary)

    orphan = Contact(full_name="Unlinked")
    session.add(orphan)
    await session.commit()
    for contact_id in (orphan.id, 999999):
        assert (await api.patch(f"/sales/contacts/{contact_id}/primary", headers=headers)).status_code == 404
    await session.refresh(orphan)
    assert orphan.is_primary is False


async def test_primary_contact_requires_write_permission(api, session):
    from core.domain.models import Contact

    await _contact_access_users(session)
    deal = await _create(api, "CP-NO-WRITE", owner_id=201)
    contact = (await api.post(f"/sales/deals/{deal['id']}/contacts",
                              json={"full_name": "Protected"})).json()
    response = await api.patch(f"/sales/contacts/{contact['id']}/primary",
                               headers={"X-User": "contact-hr", "X-User-Roles": "hr"})
    assert response.status_code == 403, response.text
    assert "sales.deal.write" in response.json()["detail"]
    persisted = await session.get(Contact, contact["id"])
    await session.refresh(persisted)
    assert persisted.is_primary is False


async def test_own_funnels_have_only_visible_counts_and_open_boards(api, session):
    await _contact_access_users(session)
    # Match the materialized stage catalog used by migrations and other board tests.
    assert (await api.get("/sales/stages")).status_code == 200
    own = await _create(api, "FUNNEL-OWN", owner_id=201)
    repeat = await _create(api, "FUNNEL-REPEAT", owner_id=201,
                           funnel="repeat_clients", stage="rp_request")
    await _create(api, "FUNNEL-OTHER", owner_id=202)
    await _create(api, "FUNNEL-UNASSIGNED")
    await _create(api, "FUNNEL-CLOSED", owner_id=201, stage="won")
    headers = _sales_headers("contact-owner")
    response = await api.get("/sales/funnels", headers=headers)
    assert response.status_code == 200, response.text
    counts = {row["code"]: row["active_deals"] for row in response.json()}
    assert counts == {"new_clients": 1, "repeat_clients": 1, "tenders": 0}
    # The combined page requests each returned board under the same identity.
    found = set()
    for code in counts:
        board = await api.get("/sales/board", params={"funnel": code}, headers=headers)
        assert board.status_code == 200
        found.update(deal["id"] for stage in board.json()["stages"] for deal in stage["deals"])
    assert own["id"] in found and repeat["id"] in found
    assert len(found) == 3  # Includes the own closed deal, never other/unassigned deals.

    all_scope = await api.get("/sales/funnels", headers=_sales_headers("contact-other"))
    assert all_scope.status_code == 200
    assert {row["code"]: row["active_deals"] for row in all_scope.json()} == {
        "new_clients": 3, "repeat_clients": 1, "tenders": 0,
    }
    denied = await api.get("/sales/funnels",
                           headers={"X-User": "contact-hr", "X-User-Roles": "hr"})
    assert denied.status_code == 403
    assert "sales.deal.read" in denied.json()["detail"]


@pytest.mark.asyncio
async def test_calls_stream_uses_authenticated_employee_and_rejects_owner_override(api, session):
    from starlette.requests import Request

    from core.services.auth import CurrentUser
    from core.services.crm_access import CrmAccess
    from modules.sales.access import _OWN_ROUTE_NAMES, deny_unscoped_own_routes
    from modules.sales.calls import _push_card, has_subscriber
    from modules.sales.routes import calls_stream

    employee_id = 614
    session.add(User(
        username="call-stream-owner", full_name="Shared Name", employee_id=employee_id,
        department="Продажи", role="sales", status="active", deal_visibility="own",
    ))
    await session.commit()

    response = await api.get(
        "/sales/calls/stream?owner=Other%20Seller",
        headers=_sales_headers("call-stream-owner"),
    )
    assert response.status_code == 400
    assert response.headers.get("content-type") != "text/event-stream"
    assert "Shared Name" not in response.text
    assert "calls_stream" in _OWN_ROUTE_NAMES

    session.add(User(
        username="call-stream-unlinked", full_name="Unlinked Seller", employee_id=None,
        department="Продажи", role="sales", status="active", deal_visibility="all",
    ))
    await session.commit()
    for headers in (
        _sales_headers("call-stream-unlinked"),
        {"X-User": "unlinked-super", "X-User-Roles": "admin"},
    ):
        denied = await asyncio.wait_for(api.get("/sales/calls/stream", headers=headers), timeout=1)
        assert denied.status_code == 403
        assert denied.headers.get("content-type") != "text/event-stream"
        assert "Shared Name" not in denied.text

    request = Request({"type": "http", "route": SimpleNamespace(name="calls_stream")})
    await deny_unscoped_own_routes(request, CrmAccess("own", employee_id))

    stream_response = await calls_stream(
        owner=None,
        user=CurrentUser(username="call-stream-owner", roles=["sales"]),
        access=CrmAccess("own", employee_id),
        session=session,
    )
    stream = stream_response.body_iterator
    try:
        assert await stream.__anext__() == ": connected\n\n"
        call = CallLog(
            id=3001, call_id="STREAM-OWN", direction="in", owner="Shared Name",
            owner_id=employee_id, status="ringing",
        )
        assert _push_card(call) is True
        event = await asyncio.wait_for(stream.__anext__(), timeout=1)
        assert "STREAM-OWN" in event
    finally:
        await stream.aclose()
    assert not has_subscriber(employee_id)


@pytest.mark.asyncio
async def test_calls_stream_releases_read_transaction_before_subscribing(session, monkeypatch):
    from sqlalchemy import select

    from core.services.auth import CurrentUser
    from core.services.crm_access import CrmAccess
    from modules.sales import calls
    from modules.sales.routes import calls_stream

    employee_id = 615
    await session.execute(select(User.id).limit(1))
    assert session.in_transaction()
    original_subscribe = calls.subscribe

    def subscribe_without_transaction(subscriber_id):
        assert not session.in_transaction()
        return original_subscribe(subscriber_id)

    monkeypatch.setattr(calls, "subscribe", subscribe_without_transaction)
    response = await calls_stream(
        owner=None,
        user=CurrentUser(username="stream-transaction-owner", roles=["sales"]),
        access=CrmAccess("own", employee_id),
        session=session,
    )
    stream = response.body_iterator
    try:
        assert await stream.__anext__() == ": connected\n\n"
        assert calls.has_subscriber(employee_id)
        call = CallLog(
            id=3002, call_id="STREAM-TRANSACTION", direction="in", owner="Synthetic Seller",
            owner_id=employee_id, status="ringing",
        )
        assert calls._push_card(call)
        assert "STREAM-TRANSACTION" in await asyncio.wait_for(stream.__anext__(), timeout=1)
    finally:
        await stream.aclose()
    assert not calls.has_subscriber(employee_id)


@pytest.mark.parametrize("roles", [["sales"], ["admin"]])
async def test_calls_stream_denies_users_without_employee_link(roles, monkeypatch):
    from fastapi import HTTPException

    from core.services.auth import CurrentUser
    from core.services.crm_access import CrmAccess
    from modules.sales import calls
    from modules.sales.routes import calls_stream

    monkeypatch.setattr(calls, "subscribe", lambda _employee_id: pytest.fail(
        "users without an employee link must be rejected before stream registration"
    ))

    with pytest.raises(HTTPException) as error:
        await calls_stream(
            owner=None,
            user=CurrentUser(username="unlinked", roles=roles),
            access=CrmAccess("all", None),
        )

    assert error.value.status_code == 403
