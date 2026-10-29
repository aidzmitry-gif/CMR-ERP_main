"""Draft authorship never grants reviewer assignment or another author's data."""
import pytest
from sqlalchemy import func, select

from core.domain.models import OutboxEvent, User
from modules.office.models import OfficeDoc
from modules.office.shipping_associations import ShippingReviewAssignment
from modules.office.shipping_producer import office_row_snapshot


async def login(api, session, username, role):
    session.add(User(username=username, full_name="Synthetic Office actor", role=role, status="active"))
    await session.commit()
    api.headers.update({"X-User": username, "X-User-Roles": role})


@pytest.mark.parametrize("role", ["finance", "assistant"])
async def test_author_can_read_only_their_own_draft(api, session, role):
    await login(api, session, "draft-author", role)
    created = await api.post("/office/docs", json={
        "title": "Synthetic draft", "owner": "someone-else", "draft_owner_subject": "someone-else",
    })
    assert created.status_code == 201, created.text
    doc_id = created.json()["id"]
    assert created.json()["stage"] == "draft"
    doc = await session.get(OfficeDoc, doc_id)
    assert doc.draft_owner_subject == "draft-author"
    assert office_row_snapshot(doc)["draft_owner_subject"] == "draft-author"
    assert doc_id in {row["id"] for row in (await api.get("/office/docs")).json()}
    assert (await api.patch(f"/office/docs/{doc_id}", json={"stage": "draft"})).status_code == 200
    await login(api, session, "other-author", role)
    assert doc_id not in {row["id"] for row in (await api.get("/office/docs")).json()}
    assert (await api.get(f"/office/docs/{doc_id}/shipping-source")).status_code == 404
    assert (await api.patch(f"/office/docs/{doc_id}", json={"stage": "draft"})).status_code == 404
    doc.draft_owner_subject = "other-author"
    with pytest.raises(ValueError, match="draft owner is immutable"):
        await session.commit()
    await session.rollback()
    assert (await session.get(OfficeDoc, doc_id)).draft_owner_subject == "draft-author"


@pytest.mark.parametrize("role", ["finance", "assistant"])
async def test_author_needs_supervisor_to_assign_reviewer(api, session, role):
    await login(api, session, "draft-author", role)
    created = await api.post("/office/docs", json={"title": "Synthetic review"})
    assert created.status_code == 201, created.text
    doc_id = created.json()["id"]
    assignment = {"subject": "draft-author", "expected_revision": 0, "evidence": "Synthetic supervisor decision"}
    assert (await api.post(f"/office/docs/{doc_id}/shipping-reviewer", json=assignment)).status_code == 403
    assert await session.scalar(select(func.count()).select_from(ShippingReviewAssignment)) == 0
    assert (await api.patch(f"/office/docs/{doc_id}", json={"stage": "paid"})).status_code == 403
    await login(api, session, "draft-supervisor", "director")
    assigned = await api.post(f"/office/docs/{doc_id}/shipping-reviewer", json=assignment)
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["assignment_revision"] == 1
    api.headers.update({"X-User": "draft-author", "X-User-Roles": role})
    moved = await api.patch(f"/office/docs/{doc_id}", json={"stage": "ready"})
    assert moved.status_code == 200, moved.text
    assert (await api.post(f"/office/docs/{doc_id}/shipping-reviewer", json={
        **assignment, "subject": "", "expected_revision": 1,
    })).status_code == 403


@pytest.mark.parametrize("role", ["finance", "assistant"])
async def test_author_cannot_create_processed_document(api, session, role):
    await login(api, session, "draft-author", role)
    result = await api.post("/office/docs", json={"title": "Synthetic bypass", "stage": "paid"})
    assert result.status_code == 403
    assert await session.scalar(select(func.count()).select_from(OfficeDoc)) == 0
    assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 0


async def test_legacy_owner_label_does_not_grant_draft_access(api, session):
    await login(api, session, "legacy-label", "finance")
    doc = OfficeDoc(title="Synthetic legacy", owner="legacy-label", stage="draft")
    session.add(doc)
    await session.commit()
    doc_id = doc.id
    assert doc.draft_owner_subject is None
    assert "draft_owner_subject" not in office_row_snapshot(doc)
    assert (await api.get("/office/docs")).json() == []
    assert (await api.patch(f"/office/docs/{doc_id}", json={"stage": "draft"})).status_code == 404


async def test_anonymous_cannot_create_office_draft(api, session):
    api.headers.update({"X-User": "anonymous", "X-User-Roles": "finance"})
    assert (await api.post("/office/docs", json={"title": "Synthetic anonymous"})).status_code == 403
    assert await session.scalar(select(func.count()).select_from(OfficeDoc)) == 0


@pytest.mark.parametrize("role", ["finance", "assistant", "guest"])
async def test_review_queue_is_supervisor_only(api, session, role):
    await login(api, session, "ordinary-viewer", role)
    assert (await api.get("/office/review-queue")).status_code == 403


async def test_supervisor_queue_uses_active_eligible_stable_identities(api, session):
    await login(api, session, "author", "finance")
    draft = (await api.post("/office/docs", json={"title": "Synthetic review queue"})).json()
    session.add_all([
        User(username="renamed-reviewer", keycloak_user_id="stable-reviewer", full_name="Synthetic Reviewer",
             email="synthetic@example.invalid", role="assistant", status="active"),
        User(username="inactive-reviewer", full_name="Inactive", role="finance", status="suspended"),
        User(username="ineligible-reviewer", full_name="Guest", role="guest", status="active"),
        OfficeDoc(title="Not a draft", stage="ready"),
    ])
    await session.commit()
    await login(api, session, "supervisor", "director")
    response = await api.get("/office/review-queue")
    assert response.status_code == 200, response.text
    result = response.json()
    assert [row["id"] for row in result["documents"]] == [draft["id"]]
    assert result["documents"][0]["assignment_revision"] == 0
    subjects = {row["subject"] for row in result["reviewers"]}
    assert "stable-reviewer" in subjects
    assert subjects.isdisjoint({"renamed-reviewer", "inactive-reviewer", "ineligible-reviewer"})
    assert "email" not in response.text and "synthetic@example.invalid" not in response.text


async def test_production_queue_never_offers_username_fallback(api, session, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from modules.office import routes

    session.add_all([
        User(username="dev-only", full_name="Dev", role="finance", status="active"),
        User(username="linked", keycloak_user_id="stable-linked", full_name="Linked", role="finance", status="active"),
    ])
    await session.commit()
    # Isolate only identity discovery policy; access denial is exercised above via HTTP.
    monkeypatch.setattr(routes, "current_actor", AsyncMock())
    monkeypatch.setattr(routes, "visible_docs", AsyncMock(return_value=[]))
    core = api._transport.app.state.core
    production_core = SimpleNamespace(roles=core.roles, services=SimpleNamespace(config=SimpleNamespace(auth_mode="oidc")))
    result = await routes.review_queue(session=session, core=production_core, user=None)
    assert result["reviewers"] == [{"subject": "stable-linked", "name": "Linked"}]


async def test_revoked_draft_assignment_restores_original_author_scope(api, session):
    await login(api, session, "draft-author", "finance")
    doc_id = (await api.post("/office/docs", json={"title": "Synthetic revoke"})).json()["id"]
    await login(api, session, "reviewer", "assistant")
    await login(api, session, "supervisor", "director")
    url = f"/office/docs/{doc_id}/shipping-reviewer"
    assert (await api.post(url, json={"subject": "reviewer", "expected_revision": 0, "evidence": "Assign"})).status_code == 200
    api.headers.update({"X-User": "draft-author", "X-User-Roles": "finance"})
    assert (await api.get("/office/docs")).json() == []
    api.headers.update({"X-User": "supervisor", "X-User-Roles": "director"})
    assert (await api.post(url, json={"subject": "", "expected_revision": 1, "evidence": "Revoke"})).status_code == 200
    api.headers.update({"X-User": "draft-author", "X-User-Roles": "finance"})
    assert [row["id"] for row in (await api.get("/office/docs")).json()] == [doc_id]
    assert (await api.patch(f"/office/docs/{doc_id}", json={"stage": "ready"})).status_code == 403


async def test_review_queue_revision_prevents_stale_assignment(api, session):
    await login(api, session, "author", "finance")
    doc_id = (await api.post("/office/docs", json={"title": "Synthetic concurrent assignment"})).json()["id"]
    await login(api, session, "supervisor", "director")
    url = f"/office/docs/{doc_id}/shipping-reviewer"
    original = (await api.get("/office/review-queue")).json()["documents"][0]
    payload = {"subject": "author", "expected_revision": original["assignment_revision"], "evidence": "First decision"}
    assert (await api.post(url, json=payload)).status_code == 200
    assert (await api.post(url, json=payload)).status_code == 409
    current = (await api.get("/office/review-queue")).json()["documents"][0]
    assert current["assignment_revision"] == 1 and current["reviewer_subject"] == "author"
    assert await session.scalar(select(func.count()).select_from(ShippingReviewAssignment)) == 1
