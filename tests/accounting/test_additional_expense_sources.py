# ruff: noqa: F811 -- pytest fixtures imported from existing PostgreSQL harness
import asyncio
import copy
import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from core.services.auth import CurrentUser
from modules.accounting import service
from modules.accounting.gateway import AccountingService
from modules.accounting.models import Period, SourceControl
from modules.procurement.additional_expenses import (
    AdditionalExpenseContent,
    AdditionalExpenseCreate,
    AdditionalExpenseEdit,
    AdditionalExpenseRevision,
    resolve_receipt_lines,
    save_document,
)
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_procurement_receipt_drafts import source_options
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401


def expense(receipt_id=1, **changes):
    return {"invoice_reference": "TRANSPORT-1", "document_date": "2026-09-10",
            "operation_date": "2026-09-10", "supplier": "carrier", "contract": "carrier-contract",
            "currency": "BYN", "amount": "100.00", "explanation": "Synthetic transport expense",
            "receipt_lines": [{"receipt_id": receipt_id, "version": 1, "line_number": 1}], **changes}


@pytest.mark.parametrize("amount", [None, True, 1.2, "NaN", "Infinity", "-1", "0", "1.001"])
def test_expense_rejects_inexact_or_nonpositive_amount(amount):
    with pytest.raises(ValidationError):
        AdditionalExpenseContent.model_validate(expense(amount=amount))


@pytest.mark.parametrize("changes", [
    {"receipt_lines": []}, {"supplier": " "}, {"currency": "byn"},
    {"receipt_lines": [{"receipt_id": True, "version": 1, "line_number": 1}]},
    {"receipt_lines": [{"receipt_id": 1, "version": 1, "line_number": 0}]},
    {"receipt_lines": [{"receipt_id": 1, "version": 1, "line_number": 1}] * 2},
])
def test_expense_rejects_ambiguous_source(changes):
    with pytest.raises(ValidationError):
        AdditionalExpenseContent.model_validate(expense(**changes))


async def test_expense_source_requires_exact_posted_receipt_in_book(issuance_pg, pg_book):
    api, factory = issuance_pg
    api.headers["X-User"] = "tester"
    async with factory() as session:
        await session.execute(text("SELECT setval(pg_get_serial_sequence('accounting.account', 'id'), (SELECT max(id) FROM accounting.account))"))
        path, options = await source_options(api, session, pg_book, unit="kg")
    receipt_id = int(path.rsplit("/", 1)[1])
    document = AdditionalExpenseContent.model_validate(expense(receipt_id))
    async with factory() as session:
        with pytest.raises(ValueError, match="Every receipt must be posted"):
            await resolve_receipt_lines(session, pg_book[0], document)
    preview = await api.post(path + "/preview", json=options)
    assert preview.status_code == 200, preview.text
    confirm = await api.post(path + "/confirm", json={**options, "digest": preview.json()["digest"]})
    assert confirm.status_code == 201, confirm.text
    async with factory() as session:
        resolved = await resolve_receipt_lines(session, pg_book[0], document)
        assert len(resolved) == 1
        assert resolved[0]["entry_id"] == confirm.json()["entry_id"]
        assert resolved[0]["item"]["quantity"] == "2.000001"
        assert resolved[0]["item"]["unit"] == "kg"
        assert resolved[0]["posting_digest"] == preview.json()["digest"]
        with pytest.raises(ValueError, match="Every receipt must be posted"):
            await resolve_receipt_lines(session, pg_book[0] + 99999, document)
        for change, message in [({"version": 2}, "exact posted version"),
                                ({"line_number": 2}, "line does not exist"),
                                ({"receipt_id": receipt_id + 99999}, "Every receipt must be posted")]:
            invalid = AdditionalExpenseContent.model_validate(expense(receipt_id, receipt_lines=[
                {"receipt_id": receipt_id, "version": 1, "line_number": 1, **change}]))
            with pytest.raises(ValueError, match=message):
                await resolve_receipt_lines(session, pg_book[0], invalid)

    gateway, user = AccountingService(), CurrentUser("tester", ["director"])
    create = AdditionalExpenseCreate(key="transport-1", document=document)
    async with factory() as session:
        header, first = await save_document(session, gateway, user, pg_book[0], create)
        expense_id = header.id
        assert first.version == 1 and first.receipt_sources == resolved
        await session.commit()
    async with factory() as session:
        repeated, revision = await save_document(session, gateway, user, pg_book[0], create)
        assert repeated.id == expense_id and revision.version == 1
        assert await session.scalar(select(func.count()).select_from(AdditionalExpenseRevision)) == 1
        await session.commit()

    async def edit(amount):
        async with factory() as session:
            try:
                _, revision = await save_document(session, gateway, user, pg_book[0],
                    AdditionalExpenseEdit(expected_version=1, document=expense(receipt_id, amount=amount)),
                    expense_id=expense_id)
                await session.commit()
                return revision.version
            except HTTPException as exc:
                await session.rollback()
                return exc.status_code
    assert sorted(await asyncio.gather(edit("101.00"), edit("102.00"))) == [2, 409]
    async with factory() as session:
        control = await session.scalar(select(SourceControl).where(
            SourceControl.source == f"procurement:additional-expense:{expense_id}"))
        assert control.version == 2 and control.entry_id is None and control.month == "2026-09"
        assert await session.scalar(select(func.count()).select_from(AdditionalExpenseRevision)) == 2
        assert (await session.scalar(select(AdditionalExpenseRevision).where(
            AdditionalExpenseRevision.version == 1))).document["amount"] == "100.00"
        period = await session.scalar(select(Period).where(
            Period.organization_id == pg_book[0], Period.month == "2026-09"))
        generation = period.generation
    closed = await api.post(f"/accounting/organizations/{pg_book[0]}/periods/2026-09/close", json={
        "expected_generation": generation, "evidence": {key: "Synthetic control" for key in service.CLOSE_STEPS}})
    assert closed.status_code == 422 and "Unposted primary documents" in closed.text
    # A caller rollback must discard both source control and appended version.
    async with factory() as session:
        await save_document(session, gateway, user, pg_book[0],
            AdditionalExpenseEdit(expected_version=2, document=expense(receipt_id, amount="103.00")),
            expense_id=expense_id)
        await session.rollback()
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(AdditionalExpenseRevision)) == 2
        control = await session.scalar(select(SourceControl).where(
            SourceControl.source == f"procurement:additional-expense:{expense_id}"))
        assert control.version == 2
        period = await session.scalar(select(Period).where(
            Period.organization_id == pg_book[0], Period.month == "2026-09"))
        assert period.generation == generation and not period.closed
    for table in ("additional_expense_document", "additional_expense_revision"):
        for statement in (f"UPDATE procurement.{table} SET id=id", f"DELETE FROM procurement.{table}",
                          f"TRUNCATE procurement.{table} CASCADE"):
            async with factory() as session:
                with pytest.raises(DBAPIError, match="immutable"):
                    await session.execute(text(statement))
                await session.rollback()
    async with factory() as session:
        with pytest.raises(DBAPIError, match="chain is incomplete"):
            await session.execute(text("INSERT INTO procurement.additional_expense_document "
                "(organization_id, source_key, created_by) VALUES (:org, 'orphan', 'tester')"), {"org": pg_book[0]})
            await session.commit()
        await session.rollback()
    for version, tamper, message in [
        (4, "none", "append the next version"),
        (3, "quantity", "snapshot differs"),
        (3, "empty", "snapshots are incomplete"),
        (3, "missing_line", "exact positive identifiers"),
        (3, "none", "completeness registration"),
    ]:
        snapshots, payload = copy.deepcopy(resolved), document.model_dump(mode="json")
        if tamper == "quantity":
            snapshots[0]["item"]["quantity"] = "9000"
        if tamper == "empty":
            snapshots = []
        if tamper == "missing_line":
            del payload["receipt_lines"][0]["line_number"]
        async with factory() as session:
            with pytest.raises(DBAPIError, match=message):
                await session.execute(text("INSERT INTO procurement.additional_expense_revision "
                    "(expense_id, version, document, receipt_sources, actor) "
                    "VALUES (:id, :version, CAST(:doc AS json), CAST(:sources AS json), 'tester')"),
                    {"id": expense_id, "version": version, "doc": json.dumps(payload), "sources": json.dumps(snapshots)})
                await session.commit()
            await session.rollback()
    async with factory() as session:
        with pytest.raises(DBAPIError, match="cannot be truncated"):
            await session.execute(text("TRUNCATE accounting.source_control"))
        await session.rollback()
