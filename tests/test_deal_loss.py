"""SQLite application tests; PostgreSQL trigger enforcement is a separate gate."""
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update

from core.domain.models import OutboxEvent, User
from modules.accounting.models import AccessGrant, Policy
from modules.sales.deal_loss import DealLossRequest, DealLossResolution
from modules.sales.models import Deal, DealDocument, Stage
from modules.sales.reservation_source import SalesReservationSource
from tests.accounting.test_invoice_settlements import bank
from tests.test_invoice_cancellation import cancel_request, prepared
from tests.test_invoice_issuance import command, create, erp_money_flow, seed


@pytest.fixture(autouse=True)
def expected_principal(api):
    api.headers["X-Expected-Principal"] = "issuer"


async def loss_command(api, org, deal=1, **changes):
    preview = await api.get(f"/sales/organizations/{org}/deals/{deal}/loss-preview")
    assert preview.status_code == 200, preview.text
    return {"organization_id": org, "request_key": str(uuid4()), "reason_code": "price",
            "expected_composition_digest": preview.json()["composition_digest"], **changes}


async def submit(api, org, deal=1, **changes):
    data = await loss_command(api, org, deal, **changes)
    response = await api.post(f"/sales/deals/{deal}/lose", json=data)
    assert response.status_code == 200, response.text
    return data, response.json()


def endpoint(org, row, action=""):
    return f"/sales/organizations/{org}/deals/1/loss-requests/{row['request_id']}" + ("/" + action if action else "")


def resolution(row):
    return {"request_key": str(uuid4()), "expected_request_digest": row["request_digest"],
            "evidence": "Explicit Sales closure after chief invoice processing"}


async def test_context_and_recovery_preserve_original_command(api, session):
    ids, _ = await seed(api, session)
    context_response = await api.get("/sales/deals/1/loss-context")
    assert context_response.status_code == 200, context_response.text
    current = context_response.json()
    assert current["principal"] == "issuer"
    assert current["organization_id"] == current["organization"]["id"] == ids["org"]
    assert current["mapping_required"] is False and current["pending_request_id"] is None
    data, row = await submit(api, ids["org"])
    current = (await api.get("/sales/deals/1/loss-context")).json()
    assert current["pending_request_id"] == current["latest_request_id"] == row["request_id"]
    for action in (None, "withdraw"):
        if action:
            assert (await api.post(endpoint(ids["org"], row, action), json=resolution(row))).status_code == 200
        recovered = await api.get(endpoint(ids["org"], row))
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["command"] == row["command"]
        assert recovered.json()["command"] == {"comment": None, "finalize_if_empty": False, **data}
        assert recovered.json()["snapshot"] == row["snapshot"]
        assert recovered.json()["command_hash"] == row["command_hash"]
    current = (await api.get("/sales/deals/1/loss-context")).json()
    assert current["pending_request_id"] is None and current["latest_request_state"] == "withdrawn"


async def test_context_unowned_does_not_assign_organization(api, session):
    await seed(api, session)
    session.add(Deal(number="context-unowned", title="Unowned", counterparty="Synthetic", amount=0))
    await session.commit()
    response = await api.get("/sales/deals/2/loss-context")
    assert response.status_code == 200, response.text
    assert response.json()["mapping_required"] is True
    assert response.json()["organization"] is None
    assert response.json()["organization_id"] is None


async def test_context_requires_current_book_access(api, session):
    await seed(api, session)
    await session.execute(delete(AccessGrant))
    await session.commit()
    response = await api.get("/sales/deals/1/loss-context")
    assert response.status_code == 403, response.text
    assert "organization" not in response.json()


@pytest.mark.parametrize("header,status", [(None, 422), ("other-session", 409)])
async def test_principal_required_before_new_and_replayed_commands(api, session, header, status):
    ids, _ = await seed(api, session)
    data = await loss_command(api, ids["org"])
    api.headers.pop("X-Expected-Principal", None)
    if header is not None:
        api.headers["X-Expected-Principal"] = header
    response = await api.post("/sales/deals/1/lose", json=data)
    assert response.status_code == status, response.text
    assert await session.scalar(select(func.count()).select_from(DealLossRequest)) == 0
    api.headers["X-Expected-Principal"] = "issuer"
    row = (await api.post("/sales/deals/1/lose", json=data)).json()
    for terminal in (False, True):
        body = resolution(row)
        if terminal:
            api.headers["X-Expected-Principal"] = "issuer"
            assert (await api.post(endpoint(ids["org"], row, "withdraw"), json=body)).status_code == 200
        api.headers.pop("X-Expected-Principal", None)
        if header is not None:
            api.headers["X-Expected-Principal"] = header
        assert (await api.post("/sales/deals/1/lose", json=data)).status_code == status
        for action in ("finalize", "withdraw"):
            response = await api.post(endpoint(ids["org"], row, action), json=body)
            assert response.status_code == status, response.text
        assert await session.scalar(select(func.count()).select_from(DealLossResolution)) == int(terminal)


async def test_empty_owned_requires_explicit_finalize_and_replays(api, session):
    ids, _ = await seed(api, session)
    grant = await session.scalar(select(AccessGrant))
    grant.role = "reader"
    await session.commit()
    data, row = await submit(api, ids["org"], finalize_if_empty=True)
    assert row["state"] == "finalized"
    replay = await api.post("/sales/deals/1/lose", json=data)
    assert replay.status_code == 200, replay.text
    assert replay.json()["resolution"] == row["resolution"]
    assert (await session.get(Deal, 1)).stage == "lost"
    assert await session.scalar(select(func.count()).select_from(DealLossResolution)) == 1
    assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
        OutboxEvent.event_type == "sales.deal.loss_requested")) == 1


async def test_empty_owned_pending_then_explicit_finalization(api, session):
    ids, _ = await seed(api, session)
    _, row = await submit(api, ids["org"])
    assert row["state"] == "pending"
    body = resolution(row)
    response = await api.post(endpoint(ids["org"], row, "finalize"), json=body)
    assert response.status_code == 200, response.text
    assert (await api.post(endpoint(ids["org"], row, "finalize"), json=body)).json() == response.json()


async def test_unowned_and_old_client_rejected_without_request(api, session):
    ids, _ = await seed(api, session)
    session.add(Deal(number="unowned", title="Unowned", counterparty="Synthetic", amount=0))
    await session.commit()
    response = await api.get(f"/sales/organizations/{ids['org']}/deals/2/loss-preview")
    assert response.status_code == 409
    assert (await api.post("/sales/deals/1/lose", json={"reason_code": "price"})).status_code == 422
    assert await session.scalar(select(func.count()).select_from(DealLossRequest)) == 0


@pytest.mark.parametrize("funnel,stage", [("new_clients", "lost"), ("repeat_clients", "rp_lost")])
async def test_generic_patch_cannot_set_effective_lost_pair(api, session, funnel, stage):
    await seed(api, session)
    response = await api.patch("/sales/deals/1", json={"funnel": funnel, "stage": stage})
    assert response.status_code == 409, response.text
    await session.rollback()
    assert (await session.get(Deal, 1)).stage == "new"


async def test_pending_freezes_stages_issuance_and_physical_fulfillment_but_allows_replay(api, session):
    ids, base = await seed(api, session)
    issued_data, _ = await command(api, ids, base)
    assert (await create(api, ids, issued_data)).status_code == 201
    _, row = await submit(api, ids["org"])
    assert (await api.patch("/sales/deals/1", json={"stage": "won"})).status_code == 409
    await session.rollback()
    assert (await api.post("/sales/deals/1/win")).status_code == 409
    await session.rollback()
    assert (await create(api, ids, issued_data)).status_code == 200
    fresh = {**issued_data, "request_key": "another-issue"}
    assert (await create(api, ids, fresh)).status_code == 409
    await session.rollback()
    doc = await session.get(DealDocument, 1)
    exact = {"organization_id": ids["org"], "expected_version": doc.version,
             "expected_content_sha256": doc.content_sha256}
    with pytest.raises(ValueError, match="loss request"):
        await SalesReservationSource().invoice_shipping_source(session, 1, **exact)
    historical = await SalesReservationSource().invoice_shipping_source(session, 1, **exact, operation="historical_claim")
    assert historical["fulfillment_allowed"] is False
    await session.commit()
    assert (await api.get(endpoint(ids["org"], row))).json()["ready_to_finalize"] is False


async def test_two_invoice_versions_include_draft_and_cannot_finalize_as_empty(api, session):
    org, _ = await prepared(api, session)
    session.add(DealDocument(deal_id=1, kind="invoice", number="draft-v2", version=2, supersedes_id=1))
    await session.commit()
    _, row = await submit(api, org, finalize_if_empty=True)
    assert len(row["snapshot"]["invoices"]) == 2
    assert row["state"] == "pending"
    response = await api.post(endpoint(org, row, "finalize"), json=resolution(row))
    assert response.status_code == 409
    invoices = response.json()["detail"]["invoices"]
    assert [x["document_id"] for x in invoices] == [1, 2]
    assert all(not x["ready"] for x in invoices)


async def test_request_identity_immutable_composition_fenced_and_withdrawal_new_uuid(api, session):
    org, _ = await prepared(api, session)
    data, row = await submit(api, org)
    assert (await api.post("/sales/deals/1/lose", json={**data, "comment": "changed"})).status_code == 409
    assert (await api.post("/sales/deals/1/lose", json={**data, "request_key": str(uuid4())})).status_code == 409
    session.add(DealDocument(deal_id=1, kind="invoice", number="new", version=2))
    with pytest.raises(ValueError, match="freezes every"):
        await session.flush()
    await session.rollback()
    withdrawal = await api.post(endpoint(org, row, "withdraw"), json=resolution(row))
    assert withdrawal.status_code == 200, withdrawal.text
    _, next_row = await submit(api, org)
    assert next_row["request_id"] != row["request_id"]
    old = (await api.post("/sales/deals/1/lose", json=data)).json()
    assert old["state"] == "withdrawn" and old["resolution"] == withdrawal.json()


@pytest.mark.parametrize("paid_refunded", [False, True])
async def test_cancel_then_finalize_with_reader_membership_and_exact_release_evidence(api, session, paid_refunded):
    if paid_refunded:
        await erp_money_flow(api, session)
        org = (await session.scalar(select(Policy))).organization_id
        facts = await SalesReservationSource().invoice_reservation(session, 1)
        await session.commit()
    else:
        org, facts = await prepared(api, session)
    _, row = await submit(api, org)
    path, body = await cancel_request(api, org, facts)
    cancelled = await api.post(path, json=body)
    assert cancelled.status_code == 201, cancelled.text
    grant = await session.scalar(select(AccessGrant))
    grant.role = "reader"
    await session.commit()
    progress = await api.get(endpoint(org, row))
    assert progress.status_code == 200, progress.text
    assert progress.json()["ready_to_finalize"], progress.text
    response = await api.post(endpoint(org, row, "finalize"), json=resolution(row))
    assert response.status_code == 200, response.text
    assert response.json()["snapshot"]["invoices"][0]["cancellation_receipt"]["cancellation_id"] == cancelled.json()["cancellation_id"]


async def test_current_book_membership_is_checked_on_replay_and_finalize(api, session):
    ids, _ = await seed(api, session)
    data, row = await submit(api, ids["org"])
    grant = await session.scalar(select(AccessGrant))
    await session.delete(grant)
    await session.commit()
    assert (await api.post("/sales/deals/1/lose", json=data)).status_code == 403
    assert (await api.post(endpoint(ids["org"], row, "finalize"), json=resolution(row))).status_code == 403


async def test_fault_after_resolution_rolls_back_stage_receipt_and_outbox(api, session, monkeypatch):
    ids, _ = await seed(api, session)
    _, row = await submit(api, ids["org"])
    bus = api._transport.app.state.core.event_bus
    original = bus.emit
    def fail(session, name, payload):
        if name == "sales.deal.loss_finalized":
            raise RuntimeError("Synthetic failure before commit")
        return original(session, name, payload)
    monkeypatch.setattr(bus, "emit", fail)
    body = resolution(row)
    with pytest.raises(RuntimeError, match="Synthetic"):
        await api.post(endpoint(ids["org"], row, "finalize"), json=body)
    assert await session.scalar(select(func.count()).select_from(DealLossResolution)) == 0
    assert (await session.get(DealLossRequest, row["request_id"])).state == "pending"
    assert (await session.get(Deal, 1)).stage == "new"
    monkeypatch.setattr(bus, "emit", original)
    assert (await api.post(endpoint(ids["org"], row, "finalize"), json=body)).status_code == 200


async def test_populated_stage_cannot_be_reclassified(api, session):
    session.add(Stage(code="custom", title="Custom", funnel="new_clients", kind="normal"))
    await session.commit()
    await seed(api, session)
    response = await api.patch("/sales/stages/custom", json={"kind": "lost"})
    assert response.status_code == 409, response.text


async def test_corrupted_missing_composition_history_fails_closed(api, session):
    org, _ = await prepared(api, session)
    _, row = await submit(api, org)
    # SQLite deliberately lacks PG guards: fault injection demonstrates app CAS.
    await session.execute(update(DealDocument).where(DealDocument.id == 1).values(deal_id=999))
    await session.commit()
    response = await api.post(endpoint(org, row, "finalize"), json=resolution(row))
    assert response.status_code == 409
    assert "composition changed" in response.text


async def test_paid_with_later_unreturned_money_blocks_finalization(api, session):
    await erp_money_flow(api, session)
    policy = await session.scalar(select(Policy))
    org, policy_id = policy.organization_id, policy.id
    _, row = await submit(api, org)
    entry = await bank(api, (org, policy_id), 1, "later-payment", amount="20.00")
    paid = await api.post(f"/sales/organizations/{org}/invoices/1/settlements", json={
        "bank_entry_id": entry, "source_key": "later-payment", "amount": "20.00", "evidence": "Synthetic later receipt"})
    assert paid.status_code == 201, paid.text
    response = await api.post(endpoint(org, row, "finalize"), json=resolution(row))
    assert response.status_code == 409
    invoice = response.json()["detail"]["invoices"][0]
    assert invoice["money"]["state"] == "funds_held"
    assert "funds_not_fully_refunded_or_history_unknown" in invoice["blockers"]


async def test_missing_cancellation_receipt_never_accepts_status_only(api, session):
    from modules.sales.invoice_cancellation import InvoiceCancellationReceipt
    org, facts = await prepared(api, session)
    _, row = await submit(api, org)
    path, body = await cancel_request(api, org, facts)
    assert (await api.post(path, json=body)).status_code == 201
    await session.execute(delete(InvoiceCancellationReceipt))  # SQLite-only corruption injection
    await session.commit()
    response = await api.post(endpoint(org, row, "finalize"), json=resolution(row))
    assert response.status_code == 409
    assert response.json()["detail"]["invoices"][0]["ready"] is False


async def test_current_sales_permission_checked_on_request_replay_and_withdraw(api, session):
    ids, _ = await seed(api, session)
    data, row = await submit(api, ids["org"])
    api.headers["X-User-Roles"] = "guest"
    assert (await api.post("/sales/deals/1/lose", json=data)).status_code == 403
    assert (await api.post(endpoint(ids["org"], row, "withdraw"), json=resolution(row))).status_code == 403


async def test_current_deal_scope_rechecked_on_replay_and_finalize(api, session):
    ids, _ = await seed(api, session)
    data, row = await submit(api, ids["org"])
    session.add(User(username="issuer", full_name="Synthetic seller", role="sales", status="active",
                     employee_id=777, deal_visibility="own"))
    await session.commit()
    api.headers["X-User-Roles"] = "sales"
    assert (await api.post("/sales/deals/1/lose", json=data)).status_code == 404
    assert (await api.post(endpoint(ids["org"], row, "finalize"), json=resolution(row))).status_code == 404


@pytest.mark.parametrize("action", ["request", "replay", "finalize", "patch"])
@pytest.mark.parametrize("changed,expected", [({"deal_visibility": "own"}, 404), ({"status": "suspended"}, 403)])
async def test_access_changed_at_lock_boundary_is_rechecked(api, session, monkeypatch, action, changed, expected):
    from modules.sales import deal_loss

    ids, _ = await seed(api, session)
    body = await loss_command(api, ids["org"])
    row = None
    if action in {"replay", "finalize"}:
        response = await api.post("/sales/deals/1/lose", json=body)
        assert response.status_code == 200
        row = response.json()
    retained = User(username="issuer", full_name="Synthetic seller", role="sales", status="active",
                    employee_id=777, deal_visibility="all")
    session.add(retained)
    await session.commit()
    api.headers["X-User-Roles"] = "sales"
    original_lock = deal_loss.lock_deal

    async def changed_after_lock(db, deal_id):
        await original_lock(db, deal_id)
        await db.execute(update(User).where(User.id == retained.id).values(**changed)
                         .execution_options(synchronize_session=False))

    monkeypatch.setattr(deal_loss, "lock_deal", changed_after_lock)
    if action == "finalize":
        response = await api.post(endpoint(ids["org"], row, "finalize"), json=resolution(row))
    elif action == "patch":
        response = await api.patch("/sales/deals/1", json={"title": "Must not change"})
    else:
        response = await api.post("/sales/deals/1/lose", json=body)
    assert response.status_code == expected, response.text
    await session.rollback()
    assert (await session.get(Deal, 1)).stage == "new"
    assert await session.scalar(select(func.count()).select_from(DealLossResolution)) == 0
    assert await session.scalar(select(func.count()).select_from(DealLossRequest)) == (1 if row else 0)


async def test_funnel_only_patch_cannot_reinterpret_same_code_as_lost(api, session):
    session.add(Stage(code="same", title="Lost target", funnel="repeat_clients", kind="lost"))
    await session.commit()
    await seed(api, session)
    deal = await session.get(Deal, 1)
    deal.stage = "same"  # unknown code in current funnel, normal legacy state
    await session.commit()
    response = await api.patch("/sales/deals/1", json={"funnel": "repeat_clients"})
    assert response.status_code == 409


async def test_two_issued_invoices_require_both_cancellations(api, session):
    ids, base = await seed(api, session)
    first, _ = await command(api, ids, base)
    assert (await create(api, ids, first)).status_code == 201
    # The new-invoice route deliberately permits only the first invoice. Model
    # an already-existing second draft, then issue it through the real API.
    draft = DealDocument(deal_id=ids["deal"], kind="invoice", number="SECOND", version=2)
    session.add(draft)
    await session.commit()
    draft_id = draft.id
    second, _ = await command(api, ids, base, doc_id=draft_id, key="second-invoice")
    created = await api.post(f"/sales/documents/{draft_id}/issue", json=second)
    assert created.status_code == 200, created.text
    second_id = created.json()["document"]["id"]
    assert second_id != 1
    _, row = await submit(api, ids["org"])
    facts = await SalesReservationSource().invoice_reservation(session, 1)
    await session.commit()
    path, data = await cancel_request(api, ids["org"], facts)
    assert (await api.post(path, json=data)).status_code == 201
    incomplete = await api.post(endpoint(ids["org"], row, "finalize"), json=resolution(row))
    assert incomplete.status_code == 409
    assert [i["ready"] for i in incomplete.json()["detail"]["invoices"]] == [True, False]
    class SecondInvoice:
        async def get(self, path, **kw):
            return await api.get(path.replace("/invoices/1", f"/invoices/{second_id}"), **kw)
        async def post(self, path, **kw):
            return await api.post(path.replace("/invoices/1", f"/invoices/{second_id}"), **kw)
    facts = await SalesReservationSource().invoice_reservation(session, second_id)
    await session.commit()
    path, data = await cancel_request(SecondInvoice(), ids["org"], facts)
    result = await SecondInvoice().post(path, json=data)
    assert result.status_code == 201, result.text
    finalized = await api.post(endpoint(ids["org"], row, "finalize"), json=resolution(row))
    assert finalized.status_code == 200, finalized.text


async def test_durable_cancelled_evidence_survives_midnight(api, session, monkeypatch):
    from datetime import date, timedelta

    from modules.sales import deal_loss, invoice_reconciliation
    org, facts = await prepared(api, session)
    _, row = await submit(api, org)
    path, body = await cancel_request(api, org, facts)
    assert (await api.post(path, json=body)).status_code == 201
    class Tomorrow(date):
        @classmethod
        def today(cls):
            return date.today() + timedelta(days=1)
    monkeypatch.setattr(deal_loss, "date", Tomorrow)
    monkeypatch.setattr(invoice_reconciliation, "date", Tomorrow)
    response = await api.post(endpoint(org, row, "finalize"), json=resolution(row))
    assert response.status_code == 200, response.text
