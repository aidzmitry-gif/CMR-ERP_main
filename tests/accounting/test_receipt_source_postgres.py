"""Actual module wiring and role middleware for the accountant source viewer."""
# ruff: noqa: F811
import asyncio

from sqlalchemy import func, select, text, update

from modules.accounting import service
from modules.accounting.models import AccessGrant, Entry, Period
from modules.procurement.receipt_documents import ReceiptDocument, ReceiptPosting, ReceiptRevision
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_procurement_receipt_drafts import document, source_options
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401


async def test_finance_reads_posted_primary_without_procurement_access(issuance_pg, pg_book):
    api, factory = issuance_pg
    api.headers["X-User"] = "tester"
    async with factory() as session:
        # pg_book copies explicit IDs from SQLite; advance only this test DB sequence.
        await session.execute(text("SELECT setval(pg_get_serial_sequence('accounting.account', 'id'), (SELECT max(id) FROM accounting.account))"))
        path, options = await source_options(api, session, pg_book, unit="кг")
    receipt_id = int(path.rsplit("/", 1)[1])
    preview = await api.post(path + "/preview", json=options)
    assert preview.status_code == 200, preview.text
    api.headers["X-User-Roles"] = "finance"
    preview_url = f"/accounting/organizations/{pg_book[0]}/receipts/{receipt_id}/preview"
    prepared = await api.post(preview_url, json=options)
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["lines"] == preview.json()["lines"]
    assert prepared.json()["digest"] == preview.json()["digest"]
    assert prepared.json()["posted"] is False
    assert prepared.json()["source_version"] == options["expected_version"]
    assert (await api.post(preview_url, json={**options, "expected_version": 999})).status_code == 409
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Entry)) == 0
        assert await session.scalar(select(func.count()).select_from(ReceiptPosting)) == 0
    confirmation_url = preview_url.removesuffix("/preview") + "/confirm"
    command = {**options, "digest": preview.json()["digest"]}
    rejected = await api.post(confirmation_url, json={**command, "digest": "0" * 64})
    assert rejected.status_code == 409
    async with factory() as session:
        period = await session.scalar(select(Period).where(Period.organization_id == pg_book[0], Period.month == "2026-09"))
        generation_before = period.generation
    close_url = f"/accounting/organizations/{pg_book[0]}/periods/2026-09/close"
    closing = {"expected_generation": generation_before, "evidence": {key: "Synthetic checks only" for key in service.CLOSE_STEPS}}
    blocked_close = await api.post(close_url, json=closing)
    assert blocked_close.status_code == 422 and "Unposted primary documents" in blocked_close.text
    confirmed, concurrent, racing_close = await asyncio.gather(
        api.post(confirmation_url, json=command), api.post(confirmation_url, json=command), api.post(close_url, json=closing))
    assert confirmed.status_code == 201, confirmed.text
    assert concurrent.status_code == 201, concurrent.text
    assert concurrent.json() == confirmed.json()
    assert racing_close.status_code == 422
    assert "Unposted primary documents" in racing_close.text or "Data changed after review" in racing_close.text
    assert (await api.post(confirmation_url, json=command)).json() == confirmed.json()
    assert (await api.post(confirmation_url, json={**command, "posting_date": "2026-09-04"})).status_code == 409
    entry_id = confirmed.json()["entry_id"]
    source_url = f"/accounting/organizations/{pg_book[0]}/receipts/{receipt_id}/source"
    posted_source = await api.get(source_url)
    assert posted_source.status_code == 200, posted_source.text
    assert posted_source.json()["document"]["items"][0]["unit"] == "кг"
    assert posted_source.json()["document"]["items"][0]["quantity"] == "2.000001"
    async with factory() as session:
        period = await session.scalar(select(Period).where(Period.organization_id == pg_book[0], Period.month == "2026-09"))
        assert not period.closed and period.generation > generation_before
        closing["expected_generation"] = period.generation
    closed = await api.post(close_url, json=closing)
    assert closed.status_code == 200, closed.text
    # A new primary cannot enter an already closed month; historical source stays readable.
    api.headers["X-User-Roles"] = "director"
    late = await api.post(path.rsplit("/", 1)[0], json={"key": "late-closed-month", "document": document()})
    assert late.status_code in {409, 422}, late.text
    assert "closed" in late.text.lower()

    async with factory() as session:
        await session.execute(update(AccessGrant).where(AccessGrant.organization_id == pg_book[0]).values(role="accountant"))
        await session.commit()
        counts = [await session.scalar(select(func.count()).select_from(model))
                  for model in (Entry, ReceiptDocument, ReceiptRevision, ReceiptPosting)]
        assert counts == [1, 1, 1, 1]
        revision = await session.scalar(select(ReceiptRevision).where(ReceiptRevision.receipt_id == receipt_id))
        expected_document = revision.document

    api.headers["X-User-Roles"] = "finance"
    assert (await api.get(path.rsplit("/", 1)[0])).status_code == 403
    response = await api.get(source_url)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["document"] == expected_document
    assert response.json()["status"] == "posted"
    assert response.json()["entry_id"] == entry_id
    assert (await api.get(source_url.replace(f"/organizations/{pg_book[0]}/", "/organizations/999999/"))).status_code == 403
    assert (await api.get(source_url.replace(f"/receipts/{receipt_id}/", "/receipts/999999/"))).status_code == 404

    async with factory() as session:
        await session.execute(update(AccessGrant).where(AccessGrant.organization_id == pg_book[0]).values(role="reader"))
        await session.commit()
    assert (await api.get(source_url)).status_code == 200
    assert (await api.post(preview_url, json=options)).status_code == 403
    assert (await api.post(confirmation_url, json=command)).status_code == 403
    assert (await api.post(f"/accounting/organizations/{pg_book[0]}/entries", json={})).status_code == 403
    api.headers["X-User"] = "unassigned"
    assert (await api.get(source_url)).status_code == 403
    async with factory() as session:
        assert [await session.scalar(select(func.count()).select_from(model))
                for model in (Entry, ReceiptDocument, ReceiptRevision, ReceiptPosting)] == counts
