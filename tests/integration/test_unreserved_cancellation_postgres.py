"""Draft SQL verification; a numbered Alembic release remains mandatory."""
import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401
from tests.test_invoice_cancellation import (
    test_atomic_cancellation_releases_once_preserves_original_and_records_event as exercise_reserved_cancellation,
)
from tests.test_unreserved_invoice_cancellation import (
    issue_unreserved,
)
from tests.test_unreserved_invoice_cancellation import (
    test_unreserved_cancellation_allows_explicit_deal_loss_finalization as exercise_loss,
)
from tests.test_unreserved_invoice_cancellation import (
    test_unreserved_cancellation_allows_linked_replacement_with_own_issuance as exercise_replacement,
)
from tests.test_unreserved_invoice_cancellation import (
    test_unreserved_cancellation_preserves_original_without_fake_release as exercise_cancellation,
)


@pytest_asyncio.fixture
async def unreserved_pg(issuance_pg):  # noqa: F811
    api, factory = issuance_pg
    draft = os.getenv("ERP_UNRESERVED_SQL_DRAFT")
    if not draft:
        pytest.skip("Explicit local SQL draft required; no automatic schema adaptation")
    statement = text(Path(draft).read_text(encoding="utf-8").replace(":", r"\:"))
    assert not statement._bindparams
    async with factory() as session:
        await session.execute(statement)
        await session.commit()
    yield api, factory


@pytest.mark.parametrize("paid_refunded", [False, True])
async def test_pg_draft_never_reserved_cancellation(unreserved_pg, paid_refunded):
    api, factory = unreserved_pg
    async with factory() as session:
        await exercise_cancellation(api, session, paid_refunded)


@pytest.mark.parametrize("exercise", [exercise_loss, exercise_replacement], ids=["loss", "replacement"])
async def test_pg_draft_never_reserved_followup(unreserved_pg, exercise):
    api, factory = unreserved_pg
    async with factory() as session:
        await exercise(api, session)


@pytest.mark.parametrize("name,options", [
    ("test_pg_fulfillment_review_concurrent_replay_and_database_guards", {}),
    ("test_pg_cancelled_invoice_replacement_preserves_original_and_new_reserve", {}),
    ("test_pg_atomic_cancellation_and_deferred_package", {"paid_refunded": False}),
    ("test_pg_atomic_cancellation_and_deferred_package", {"paid_refunded": True}),
    ("test_pg_cancellation_rejects_direct_status_and_incomplete_package", {"monkeypatch": True}),
    ("test_pg_cancellation_package_rechecks_bank_written_after_application_review", {"monkeypatch": True, "correction": False}),
    ("test_pg_cancellation_package_rechecks_bank_written_after_application_review", {"monkeypatch": True, "correction": True}),
    ("test_pg_cancellation_rejects_malformed_saved_sections_even_with_faulty_verifier", {"monkeypatch": True}),
    ("test_pg_cancellation_requires_actual_withdrawal_of_bound_targets", {"monkeypatch": True}),
])
async def test_pg_original_reserved_contract_on_changed_guards(unreserved_pg, monkeypatch, name, options):
    from tests import test_invoice_cancellation as original

    kwargs = {**options}
    if "monkeypatch" in kwargs:
        kwargs["monkeypatch"] = monkeypatch
    await getattr(original, name)(unreserved_pg, **kwargs)


@pytest.mark.parametrize("same_key", [True, False], ids=["same-key", "different-key"])
async def test_pg_concurrent_never_reserved_cancellation_is_single(unreserved_pg, same_key):
    from core.domain.models import OutboxEvent
    from modules.sales.invoice_cancellation import InvoiceCancellationReceipt
    from modules.wms.invoice_reservations import InvoiceReservationRelease
    from tests.test_invoice_cancellation import cancel_request

    api, factory = unreserved_pg
    async with factory() as session:
        ids, invoice = await issue_unreserved(api, session)
        await session.commit()
    path, body = await cancel_request(api, ids["org"], {
        "version": invoice["version"], "content_sha256": invoice["content_sha256"]})
    second = body if same_key else {**body, "request_key": str(uuid4())}
    replies = await asyncio.gather(api.post(path, json=body), api.post(path, json=second))
    assert sorted(r.status_code for r in replies) == ([201, 201] if same_key else [201, 409]), [r.text for r in replies]
    if same_key:
        assert replies[0].json() == replies[1].json()
    confirmed = next(r.json() for r in replies if r.status_code == 201)
    assert confirmed["stock_outcome"] == "no_stock_release" and confirmed["release_id"] is None
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(InvoiceCancellationReceipt)) == 1
        assert await session.scalar(select(func.count()).select_from(InvoiceReservationRelease)) == 0
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.event_type == "sales.invoice.cancelled")) == 1


def draft_sql(name):
    path = Path(os.environ["ERP_UNRESERVED_SQL_DRAFT"])
    if name in {"upgrade", "downgrade"}:
        path = path.with_name(path.name.replace("upgrade", name))
    else:
        path = path.with_name(name)
    return path.read_text(encoding="utf-8")


async def test_pg_downgrade_refuses_never_reserved_history(unreserved_pg):
    api, factory = unreserved_pg
    async with factory() as session:
        await exercise_cancellation(api, session, False)
    async with factory() as session:
        before = (await session.execute(text(
            "SELECT id,digest,snapshot::text,release_id FROM sales.invoice_cancellation_receipt"))).all()
        with pytest.raises(DBAPIError, match="No-stock cancellation history prevents downgrade"):
            await session.execute(text(draft_sql("downgrade").replace(":", r"\:")))
        await session.rollback()
        assert (await session.execute(text(
            "SELECT id,digest,snapshot::text,release_id FROM sales.invoice_cancellation_receipt"))).all() == before


async def test_pg_downgrade_preserves_old_reserved_history_and_upgrade_restores_guard(unreserved_pg):
    api, factory = unreserved_pg
    async with factory() as session:
        await exercise_reserved_cancellation(api, session, False)
    async with factory() as session:
        read_history = text("SELECT id,document_id,digest,release_id,snapshot::text FROM sales.invoice_cancellation_receipt")
        before = (await session.execute(read_history)).all()
        await session.execute(text(draft_sql("downgrade").replace(":", r"\:")))
        await session.commit()
        assert (await session.execute(read_history)).all() == before
        assert not await session.scalar(text("SELECT EXISTS(SELECT 1 FROM information_schema.columns "
            "WHERE table_schema='sales' AND table_name='invoice_cancellation_receipt' AND column_name='reservation_state')"))
        original = draft_sql("unreserved-cancellation-guard-before.sql").split("$$")[1]
        assert await session.scalar(text("SELECT prosrc FROM pg_proc WHERE oid='sales.check_cancellation_package()'::regprocedure")) == original
        loss_original = draft_sql("unreserved-loss-guard-before.sql").split("$$")[1]
        assert await session.scalar(text("SELECT prosrc FROM pg_proc WHERE oid='sales.check_loss_cancelled_invoice(text)'::regprocedure")) == loss_original
        await session.execute(text(draft_sql("upgrade").replace(":", r"\:")))
        await session.commit()
        assert (await session.execute(read_history)).all() == before
        assert await session.scalar(text("SELECT count(*) FROM sales.invoice_cancellation_receipt "
            "WHERE release_id IS NOT NULL")) == 1
