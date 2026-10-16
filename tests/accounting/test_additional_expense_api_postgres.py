# ruff: noqa: F811 -- imported pytest fixtures
import asyncio
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.reference import Currency
from modules.accounting import inventory_issues, late_cost_preview, reports, sales, service
from modules.accounting.late_cost_commands import confirm as confirm_late_cost
from modules.accounting.late_cost_posting import ExpenseAccounts, candidate
from modules.accounting.late_cost_receipts import LateCostCommand
from modules.accounting.late_cost_receipts import verify_receipt as verify_late_cost_receipt
from modules.accounting.late_cost_sources import expense_basis, expense_history
from modules.accounting.models import (
    AccessGrant,
    Entry,
    InventoryIssueReceipt,
    InventorySaleReceipt,
    Line,
    SourceControl,
)
from modules.accounting.schemas import InventoryIssueDocument, LateCostPreviewInput, PostingInput
from modules.accounting.service import AccountingError
from modules.procurement.additional_expenses import (
    AdditionalExpenseDocument,
    AdditionalExpenseRevision,
)
from modules.procurement.source_gateway import ProcurementSourceService
from tests.accounting.test_additional_expense_sources import expense
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_procurement_receipt_drafts import source_options
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401


@pytest.mark.parametrize("quantity,disposition", [("2.000001", "issue"), ("10", "issue"), ("10", "sale"), ("10", "sale_gateway")])
async def test_expense_api_atomic_versioned_scoped_documents(issuance_pg, pg_book, monkeypatch, quantity, disposition):
    api, factory = issuance_pg
    api.headers["X-User"] = "tester"
    async with factory() as session:
        await session.execute(text("SELECT setval(pg_get_serial_sequence('accounting.account', 'id'), (SELECT max(id) FROM accounting.account))"))
        path, options = await source_options(api, session, pg_book)
    if quantity == "10":
        draft = (await api.get(path.rsplit("/", 1)[0])).json()[0]
        source_document = draft["revisions"][-1]["document"]
        source_document["items"][0]["quantity"] = quantity
        revised = await api.put(path, json={"expected_version": 1, "document": source_document})
        assert revised.status_code == 200, revised.text
        options["expected_version"] = 2
    preview = await api.post(path + "/preview", json=options)
    assert preview.status_code == 200, preview.text
    posted = await api.post(path + "/confirm", json={**options, "digest": preview.json()["digest"]})
    assert posted.status_code == 201, posted.text
    base = f"/procurement/organizations/{pg_book[0]}/additional-expenses"
    command = {"key": "transport-api", "document": expense(int(path.rsplit("/", 1)[1]))}
    command["document"]["receipt_lines"][0]["version"] = options["expected_version"]
    principal = {"X-Expected-Principal": "tester"}
    assert (await api.post(base, json=command)).status_code == 422
    assert (await api.post(base, json=command, headers={"X-Expected-Principal": "other"})).status_code == 409
    first, duplicate = await asyncio.gather(*[api.post(base, json=command, headers=principal) for _ in range(2)])
    assert first.status_code == duplicate.status_code == 201, [first.text, duplicate.text]
    assert first.json() == duplicate.json()
    assert first.headers["cache-control"] == "private, no-store"
    item = first.json()
    assert item["status"] == "draft" and not item["posted"] and item["version"] == 1
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(AdditionalExpenseDocument)) == 1
        assert await session.scalar(select(func.count()).select_from(AdditionalExpenseRevision)) == 1
    detail = base + f"/{item['id']}"
    assert (await api.get(detail)).json() == item
    assert (await api.get(base)).json() == [item]
    changed = {**command["document"], "amount": "123.45"}
    conflict = await api.post(base, json={**command, "document": changed}, headers=principal)
    assert conflict.status_code == 409
    edit = await api.put(detail, json={"expected_version": 1, "document": changed}, headers=principal)
    assert edit.status_code == 200 and edit.json()["version"] == 2, edit.text
    assert edit.json()["revisions"][0]["document"]["amount"] == "100.00"
    replay = await api.put(detail, json={"expected_version": 1, "document": changed}, headers=principal)
    assert replay.status_code == 200 and replay.json() == edit.json()
    assert (await api.put(detail, json={"expected_version": 1, "document": command["document"]}, headers=principal)).status_code == 409
    assert (await api.get(f"/procurement/organizations/{pg_book[0]+999}/additional-expenses/{item['id']}")).status_code == 403

    async with factory() as session:
        await session.execute(text("SELECT setval(pg_get_serial_sequence('accounting.access_grant', 'id'), (SELECT max(id) FROM accounting.access_grant))"))
        session.add(AccessGrant(organization_id=pg_book[0], subject="expense-reader", role="reader"))
        session.add(AccessGrant(organization_id=pg_book[0], subject="expense-accountant", role="accountant"))
        await session.commit()
    reader_headers = {"X-User": "expense-reader", "X-Expected-Principal": "expense-reader"}
    assert (await api.get(detail, headers=reader_headers)).status_code == 200
    assert (await api.post(base, json={**command, "key": "reader-create"}, headers=reader_headers)).status_code == 403
    can_read = await api.get(base.removesuffix("s") + "-context", headers=reader_headers)
    assert can_read.status_code == 200 and can_read.json()["can_write"] is False
    accountant_headers = {"X-User": "expense-accountant", "X-Expected-Principal": "expense-accountant"}
    assert (await api.put(detail, json={"expected_version": 2, "document": changed}, headers=accountant_headers)).status_code == 200

    original_commit = AsyncSession.commit
    async def failing_commit(session):
        if await session.scalar(select(AdditionalExpenseDocument.id).where(AdditionalExpenseDocument.source_key == "commit-failure")):
            raise ValueError("Synthetic commit failure")
        return await original_commit(session)
    failed_command = {**command, "key": "commit-failure"}
    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", failing_commit)
        failed = await api.post(base, json=failed_command, headers=principal)
        assert failed.status_code == 422, failed.text
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(AdditionalExpenseDocument)) == 1
        assert await session.scalar(select(func.count()).select_from(SourceControl).where(
            SourceControl.source.like("procurement:additional-expense:%"))) == 1
    retried = await api.post(base, json=failed_command, headers=principal)
    assert retried.status_code == 201, retried.text
    async with factory() as session:
        gateway = ProcurementSourceService()
        verified = await expense_basis(session, pg_book[0], item["id"], 3, gateway)
        assert verified["acquisitions_verified"] and not verified["disposals_verified"]
        assert verified["receipt_sources"][0]["entry_id"] == posted.json()["entry_id"]
        assert verified["receipt_sources"][0]["acquisition_line"] == 1
        with pytest.raises(ValueError, match="version changed"):
            await expense_basis(session, pg_book[0], item["id"], 1, gateway)
        with pytest.raises(ValueError, match="not found"):
            await gateway.additional_expense_source(session, pg_book[0] + 999, item["id"], 3)
        original_basis = gateway.posted_receipt_basis
        async def corrupt_basis(*args):
            return {**await original_basis(*args), "digest": "0" * 64}
        with monkeypatch.context() as patch:
            patch.setattr(gateway, "posted_receipt_basis", corrupt_basis)
            with pytest.raises(AccountingError, match="actual accounting package"):
                await expense_basis(session, pg_book[0], item["id"], 3, gateway)
        history = await expense_history(session, pg_book[0], item["id"], 3, date(2026, 9, 11), gateway)
        assert history["disposals_verified"] and not history["final_cost_certified"]
        assert history["lots"][0]["remaining_quantity"] == format(Decimal(quantity), ".6f")
        assert history["lots"][0]["disposed_quantity"] == "0.000000"
        repeated = await expense_history(session, pg_book[0], item["id"], 3, date(2026, 9, 11), gateway)
        assert repeated["basis_digest"] == history["basis_digest"]
        with pytest.raises(AccountingError, match="Later lot movements"):
            await expense_history(session, pg_book[0], item["id"], 3, date(2026, 8, 31), gateway)
        link = history["receipt_sources"][0]
        issue = InventoryIssueDocument(source="late-cost-issue", source_version=1, policy_id=pg_book[1],
            document_date="2026-09-11", operation_date="2026-09-11", posting_date="2026-09-11",
            account=link["account"], warehouse=link["warehouse"], sku=link["item"]["sku"], lot=link["item"]["lot"],
            quantity="0.5", expense_account="90.4", explanation="Synthetic ordinary issue")
        cost, posting = await inventory_issues.prepare(session, pg_book[0], issue)
        issue_entry = await inventory_issues.confirm(session, pg_book[0], issue, cost["basis_digest"], service.digest(posting), "tester")
        issue_id = issue_entry.id
        await session.commit()
        issue_receipt = await session.get(InventoryIssueReceipt, issue_id)
        assert issue_receipt.command == issue.model_dump(mode="json")
        assert issue_receipt.cost["basis_digest"] == cost["basis_digest"]
        assert issue_receipt.digest == service.digest(posting)
        repeated_issue = await inventory_issues.confirm(session, pg_book[0], issue, cost["basis_digest"], service.digest(posting), "tester")
        assert repeated_issue.id == issue_id
        assert await session.scalar(select(func.count()).select_from(InventoryIssueReceipt)) == 1
        after_issue = await expense_history(session, pg_book[0], item["id"], 3, date(2026, 9, 11), gateway)
        assert after_issue["lots"][0]["disposed_quantity"] == "0.500000"
        assert after_issue["lots"][0]["remaining_quantity"] == format(Decimal(quantity) - Decimal("0.5"), ".6f")
        assert after_issue["basis_digest"] != history["basis_digest"]
        original_get = session.get
        corrupt_receipt = SimpleNamespace(**{field: getattr(issue_receipt, field) for field in
            ("organization_id", "command", "posting", "digest", "actor")},
            cost={**issue_receipt.cost, "issue_cost_byn": "999.99"})
        async def changed_receipt(model, identity, *args, **kwargs):
            if model is InventoryIssueReceipt and identity == issue_id:
                return corrupt_receipt
            return await original_get(model, identity, *args, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(session, "get", changed_receipt)
            with pytest.raises(AccountingError, match="calculation or ledger package changed"):
                await inventory_issues.verify_receipt(session, pg_book[0], issue_id)
    for statement in ("UPDATE accounting.inventory_issue_receipt SET actor='changed'",
                      "DELETE FROM accounting.inventory_issue_receipt", "TRUNCATE accounting.inventory_issue_receipt"):
        async with factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(text(statement))
            await session.rollback()
    allocation = {"expected_version": 3, "policy_id": pg_book[1], "posting_date": "2026-09-12",
                  "capitalizable_amount_byn": "100.00", "excluded_amount_byn": "23.45",
                  "classification_evidence": "Synthetic explicit cost classification"}
    async with factory() as session:
        with pytest.raises(AccountingError, match="not configured"):
            await late_cost_preview.preview(session, pg_book[0], item["id"], LateCostPreviewInput(**allocation), ProcurementSourceService())
        await session.rollback()
        await session.execute(text("SELECT setval(pg_get_serial_sequence('accounting.policy', 'id'), (SELECT max(id) FROM accounting.policy))"))
        await session.commit()
    policy = await api.post(f"/accounting/organizations/{pg_book[0]}/policies", json={
        "effective_from": "2026-09-12", "reference": "Synthetic late-cost policy",
        "inventory_method": "specific", "allocation_basis": "direct_cost", "depreciation_method": "straight_line",
        "normative_reference": "Synthetic only", "normative_verified": False,
        "late_cost_allocation": {"basis": "quantity", "rounding": "largest_remainder_cent"}})
    assert policy.status_code == 201, policy.text
    allocation["policy_id"] = policy.json()["id"]
    async with factory() as session:
        calculated = await late_cost_preview.preview(session, pg_book[0], item["id"], LateCostPreviewInput(**allocation), ProcurementSourceService())
        assert calculated["source_movements_verified"] and not calculated["confirmation_available"]
        assert calculated["amount_byn"] == "100.00" and calculated["excluded_amount_byn"] == "23.45"
        if quantity == "10":
            assert calculated["totals_byn"] == {"remaining": "95.00", "disposed": "5.00", "production": "0.00"}
            disposed = next(share for share in calculated["shares"] if share["destination"] == "disposed")
            assert len(disposed["expense_destinations"]) == 1
            assert disposed["expense_destinations"][0]["amount_byn"] == "5.00"
            assert disposed["expense_destinations"][0]["quantity"] == "0.5"
            proposed = candidate(calculated, ExpenseAccounts(settlement_account="60", excluded_costs=[
                {"account": "18", "amount_byn": "23.45", "dimensions": {"counterparty": "carrier"}}]))
            assert [line.amount for line in proposed.lines] == [Decimal("95.00"), Decimal("5.00"),
                                                                Decimal("23.45"), Decimal("123.45")]
            assert all(line.quantity is None for line in proposed.lines)
            assert proposed.lines[0].dimensions == calculated["history"]["receipt_sources"][0]["inventory_dimensions"]
            assert proposed.lines[-1].dimensions["counterparty"] == calculated["history"]["document"]["supplier"]
            with pytest.raises(AccountingError, match="Excluded amount"):
                candidate(calculated, ExpenseAccounts(settlement_account="60"))
            with pytest.raises(AccountingError, match="cost-layer confirmation"):
                await service.validate_posting(session, pg_book[0], proposed)
            with pytest.raises(AccountingError, match="Historical cost boundary"):
                await expense_history(session, pg_book[0], item["id"], calculated["source_version"],
                    date.fromisoformat(calculated["posting_date"]), ProcurementSourceService(),
                    before_entry_id=calculated["history"]["receipt_sources"][0]["entry_id"])
            with pytest.raises(AccountingError, match="no matching source receipt"):
                await verify_late_cost_receipt(session, pg_book[0], 999999, ProcurementSourceService())
        with pytest.raises(AccountingError, match="cover the source amount"):
            await late_cost_preview.preview(session, pg_book[0], item["id"],
                LateCostPreviewInput(**{**allocation, "excluded_amount_byn": "0"}), ProcurementSourceService())
        count_before = await session.scalar(select(func.count()).select_from(Entry))
    preview_url = f"/accounting/organizations/{pg_book[0]}/additional-expenses/{item['id']}/preview"
    public = await api.post(preview_url, json=allocation)
    assert public.status_code == 200, public.text
    assert public.json()["basis_digest"] == calculated["basis_digest"]
    assert public.headers["cache-control"] == "private, no-store"
    assert public.json()["posted"] is False and public.json()["confirmation_available"] is False
    assert (await api.post(preview_url, json={**allocation, "expected_version": 1})).status_code == 422
    assert (await api.post(preview_url.replace(f"/{pg_book[0]}/", f"/{pg_book[0]+999}/"), json=allocation)).status_code == 403
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Entry)) == count_before
    if quantity == "10":
        command = LateCostCommand(allocation=allocation, accounts={"settlement_account": "60", "excluded_costs": [
            {"account": "90.4", "amount_byn": "23.45", "dimensions": {}}]})
        expected = candidate(calculated, command.accounts)
        request_key = uuid4()
        async def fail_after_write(*args, **kwargs):
            raise AccountingError("injected post-write failure")
        with monkeypatch.context() as patch:
            patch.setattr("modules.accounting.late_cost_commands.verify_receipt", fail_after_write)
            async with factory() as session:
                with pytest.raises(AccountingError, match="injected"):
                    await confirm_late_cost(session, pg_book[0], item["id"], command, request_key,
                        calculated["basis_digest"], service.digest(expected), "tester", ProcurementSourceService())
                await session.rollback()
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(Entry)) == count_before
        async with factory() as session:
            trial = await confirm_late_cost(session, pg_book[0], item["id"], command, request_key,
                calculated["basis_digest"], service.digest(expected), "tester", ProcurementSourceService())
            with pytest.raises(DBAPIError, match="Late cost posting lines"):
                await session.execute(text("INSERT INTO accounting.line SELECT "
                    "(jsonb_populate_record(NULL::accounting.line, to_jsonb(l) || jsonb_build_object('id', "
                    "nextval(pg_get_serial_sequence('accounting.line','id'))))).* "
                    "FROM accounting.line l WHERE entry_id=:id"), {"id": trial.entry_id})
                await session.commit()
            await session.rollback()
        async with factory() as session:
            saved = await confirm_late_cost(session, pg_book[0], item["id"], command, request_key,
                calculated["basis_digest"], service.digest(expected), "tester", ProcurementSourceService())
            entry_id = saved.entry_id
            await session.commit()
        async with factory() as session:
            repeated = await confirm_late_cost(session, pg_book[0], item["id"], command, request_key,
                calculated["basis_digest"], service.digest(expected), "tester", ProcurementSourceService())
            assert repeated.entry_id == entry_id
            assert await session.scalar(select(func.count()).select_from(Entry)) == count_before + 1
            assert (await verify_late_cost_receipt(session, pg_book[0], entry_id, ProcurementSourceService())).model_dump() == expected.model_dump()
            with pytest.raises(AccountingError, match="conflicts"):
                await confirm_late_cost(session, pg_book[0], item["id"], command, uuid4(),
                    calculated["basis_digest"], service.digest(expected), "tester", ProcurementSourceService())
            await session.commit()
        async with factory() as session:
            with pytest.raises(DBAPIError, match="Posted late expense"):
                await session.execute(text("INSERT INTO procurement.additional_expense_revision "
                    "(expense_id, version, document, receipt_sources, actor) "
                    "SELECT expense_id, version+1, document, receipt_sources, actor "
                    "FROM procurement.additional_expense_revision WHERE expense_id=:id AND version=:version"),
                    {"id": item["id"], "version": calculated["source_version"]})
            await session.rollback()
        # Consume the whole remaining lot through the public issue workflow.
        async with factory() as session:
            await session.execute(text("SELECT accounting.verify_late_cost_lines(:id)"), {"id": entry_id})
            with pytest.raises(DBAPIError, match="Cannot append lines to a committed entry"):
                await session.execute(text("INSERT INTO accounting.line SELECT "
                    "(jsonb_populate_record(NULL::accounting.line, to_jsonb(l) || jsonb_build_object('id', "
                    "nextval(pg_get_serial_sequence('accounting.line','id'))))).* "
                    "FROM accounting.line l WHERE entry_id=:id"), {"id": entry_id})
                await session.commit()
            await session.rollback()
        second_source = expense(int(path.rsplit("/", 1)[1]), amount="20.00",
            receipt_lines=[{"receipt_id": int(path.rsplit("/", 1)[1]), "version": options["expected_version"], "line_number": 1}])
        second = await api.post(base, json={"key": "broker-after-transport", "document": second_source}, headers=principal)
        assert second.status_code == 201, second.text
        second_url = f"/accounting/organizations/{pg_book[0]}/additional-expenses/{second.json()['id']}"
        second_command = {"allocation": {**allocation, "expected_version": 1,
            "capitalizable_amount_byn": "20.00", "excluded_amount_byn": "0.00"}, "accounts": {"settlement_account": "60"}}
        second_preview = await api.post(second_url + "/posting-preview", json=second_command)
        assert second_preview.status_code == 200, second_preview.text
        assert second_preview.json()["calculation"]["totals_byn"] == {"remaining": "19.00", "disposed": "1.00", "production": "0.00"}
        second_posted = await api.post(second_url + "/confirm", json={**second_command, "request_key": str(uuid4()),
            "expected_digest": second_preview.json()["digest"], "expected_basis_digest": second_preview.json()["basis_digest"]}, headers=principal)
        assert second_posted.status_code == 201, second_posted.text
        next_issue = {**issue.model_dump(mode="json"), "source": "after-late-cost",
                      "policy_id": allocation["policy_id"], "posting_date": allocation["posting_date"],
                      "quantity": "9.5"}
        issue_url = f"/accounting/organizations/{pg_book[0]}/inventory/issues"
        sale = {**next_issue, "source": "sale-after-late-cost", "net_amount": "1000.00", "vat_rate": "0",
                "vat_basis": "Synthetic zero VAT example", "buyer_account": "62", "revenue_account": "90.1",
                "vat_revenue_account": "90.2", "vat_payable_account": "68.2",
                "buyer_dimensions": {"counterparty": "buyer", "contract": "contract", "settlement_document": "sale"}}
        sale_preview = await api.post(f"/accounting/organizations/{pg_book[0]}/sales/posting-preview", json=sale)
        assert sale_preview.status_code == 200, sale_preview.text
        next_preview = await api.post(issue_url + "/posting-preview", json=next_issue)
        assert next_preview.status_code == 200, next_preview.text
        next_calculated = next_preview.json()
        assert next_calculated["cost"]["book_quantity"] == "9.500000"
        expected_remaining = Decimal(calculated["history"]["lots"][0]["received_value_byn"]) - Decimal(cost["issue_cost_byn"]) + Decimal("114.00")
        assert Decimal(next_calculated["cost"]["issue_cost_byn"]) == expected_remaining
        assert Decimal(sale_preview.json()["cost"]["issue_cost_byn"]) == expected_remaining
        final_preview = sale_preview.json() if disposition.startswith("sale") else next_calculated
        final_document = sale if disposition.startswith("sale") else next_issue
        final_url = f"/accounting/organizations/{pg_book[0]}/sales" if disposition.startswith("sale") else issue_url
        final_command = {**final_document, "basis_digest": final_preview["cost"]["basis_digest"], "digest": final_preview["digest"]}
        if disposition == "sale":
            async with factory() as session:
                await service.post(session, pg_book[0], PostingInput.model_validate(final_preview["posting"]), "tester", inventory_sale=True)
                with pytest.raises(DBAPIError, match="Inventory sale requires its complete receipt"):
                    await session.commit()
                await session.rollback()
            async with factory() as session:
                trial = await sales.confirm(session, pg_book[0], sales.SaleDocument.model_validate(sale),
                    final_preview["cost"]["basis_digest"], final_preview["digest"], "tester", procurement=ProcurementSourceService())
                await session.execute(text("INSERT INTO accounting.line SELECT "
                    "(jsonb_populate_record(NULL::accounting.line, to_jsonb(l) || jsonb_build_object('id', "
                    "nextval(pg_get_serial_sequence('accounting.line','id'))))).* "
                    "FROM accounting.line l WHERE entry_id=:id"), {"id": trial.id})
                with pytest.raises(DBAPIError, match="Inventory sale posting lines differ"):
                    await session.commit()
                await session.rollback()
        if disposition == "sale_gateway":
            from fastapi.encoders import jsonable_encoder

            from core.services.auth import CurrentUser
            from modules.accounting.gateway import AccountingService

            services = SimpleNamespace(procurement_source=None)
            gateway, user = AccountingService(services), CurrentUser("tester", ["director"])
            # Registration order must not freeze a missing dependency.
            services.procurement_source = ProcurementSourceService()
            async with factory() as session:
                await gateway.source_changed(session, pg_book[0], user, sale["source"], sale["source_version"], sale["posting_date"])
                prepared = await gateway.sale_posting(session, pg_book[0], user, sale, confirm_digest=None)
                assert jsonable_encoder(prepared) == sale_preview.json()
                first = await gateway.sale_posting(session, pg_book[0], user, sale,
                    confirm_digest=prepared["digest"], basis_digest=prepared["cost"]["basis_digest"])
                final_entry_id = first["entry_id"]
                await session.commit()
            async with factory() as session:
                replay = await gateway.sale_posting(session, pg_book[0], user, sale,
                    confirm_digest=prepared["digest"], basis_digest=prepared["cost"]["basis_digest"])
                assert replay["entry_id"] == final_entry_id
                control = await session.scalar(select(SourceControl).where(SourceControl.organization_id == pg_book[0], SourceControl.source == sale["source"]))
                assert control.entry_id == final_entry_id
        else:
            next_posted = await api.post(final_url + "/confirm", json=final_command)
            assert next_posted.status_code == 201, next_posted.text
            final_entry_id = next_posted.json()["id"]
            replay = await api.post(final_url + "/confirm", json=final_command)
            assert replay.status_code == 201 and replay.json()["id"] == final_entry_id, replay.text
        async with factory() as session:
            if disposition == "issue":
                await inventory_issues.verify_receipt(session, pg_book[0], final_entry_id, procurement=ProcurementSourceService())
            await verify_late_cost_receipt(session, pg_book[0], entry_id, ProcurementSourceService())
            await verify_late_cost_receipt(session, pg_book[0], second_posted.json()["entry_id"], ProcurementSourceService())
            assert await session.scalar(select(func.count()).select_from(Entry)) == count_before + 3
            lines = (await session.scalars(select(Line).where(Line.entry_id == final_entry_id,
                Line.account_code == link["account"]))).all()
            assert len(lines) == 1 and lines[0].side == "credit"
            assert lines[0].quantity == Decimal("9.5") and lines[0].amount == expected_remaining
            if disposition.startswith("sale"):
                original_sale = await sales.verify_receipt(session, pg_book[0], final_entry_id, procurement=ProcurementSourceService())
                saved_sale = await session.get(InventorySaleReceipt, final_entry_id)
                assert saved_sale.command == sales.SaleDocument.model_validate(final_document).model_dump(mode="json")
                assert saved_sale.digest == final_preview["digest"]
                assert saved_sale.cost["basis_digest"] == final_preview["cost"]["basis_digest"]
                assert await session.scalar(select(func.count()).select_from(InventorySaleReceipt)) == 1
                with pytest.raises(DBAPIError, match="Inventory sale receipt is immutable"):
                    await session.execute(text("UPDATE accounting.inventory_sale_receipt SET actor='changed' WHERE entry_id=:id"),
                        {"id": final_entry_id})
                await session.rollback()
        if disposition.startswith("sale"):
            async with factory() as session:
                report_before = await reports.report(session, pg_book[0], date(2026, 9, 1), date(2026, 9, 30))
            third = await api.post(base, json={"key": "after-sale", "document": second_source}, headers=principal)
            assert third.status_code == 201, third.text
            third_url = f"/accounting/organizations/{pg_book[0]}/additional-expenses/{third.json()['id']}"
            third_preview = await api.post(third_url + "/posting-preview", json=second_command)
            assert third_preview.status_code == 200, third_preview.text
            assert third_preview.json()["calculation"]["totals_byn"] == {"remaining": "0.00", "disposed": "20.00", "production": "0.00"}
            third_posted = await api.post(third_url + "/confirm", json={**second_command, "request_key": str(uuid4()),
                "expected_digest": third_preview.json()["digest"], "expected_basis_digest": third_preview.json()["basis_digest"]}, headers=principal)
            assert third_posted.status_code == 201, third_posted.text
            async with factory() as session:
                assert (await sales.verify_receipt(session, pg_book[0], final_entry_id, procurement=ProcurementSourceService())).model_dump() == original_sale.model_dump()
                await verify_late_cost_receipt(session, pg_book[0], third_posted.json()["entry_id"], ProcurementSourceService())
                assert await session.scalar(select(func.count()).select_from(Entry)) == count_before + 4
                assert await session.scalar(select(func.count()).select_from(Line).where(
                    Line.entry_id == third_posted.json()["entry_id"], Line.account_code == link["account"])) == 0
                report_after = await reports.report(session, pg_book[0], date(2026, 9, 1), date(2026, 9, 30))
                assert report_after["pnl"]["income"] == report_before["pnl"]["income"] == "1000.00"
                total_expense = Decimal(calculated["history"]["lots"][0]["received_value_byn"]) + Decimal("163.45")
                assert Decimal(report_after["pnl"]["expenses"]) == total_expense
                assert Decimal(report_after["pnl"]["expenses"]) - Decimal(report_before["pnl"]["expenses"]) == Decimal("20.00")
                assert Decimal(report_after["pnl"]["profit"]) == Decimal("1000.00") - total_expense
                assert report_after["balance"]["difference"] == "0.00"
                assert report_after["balance"]["equity"] == report_before["balance"]["equity"]
                assert report_after["cashflow"] == report_before["cashflow"]
                stock_rows = [row for row in report_after["trial_balance"] if row["account"] == link["account"]]
                assert sum(Decimal(row["closing"]) for row in stock_rows) == 0
                assert sum(Decimal(row["quantity_closing"]) for row in stock_rows) == 0
                assert sum(Decimal(row["debit"]) for row in report_after["trial_balance"]) == sum(Decimal(row["credit"]) for row in report_after["trial_balance"])
                assert {row["entry_id"] for row in report_after["movements"]} >= {entry_id, second_posted.json()["entry_id"], final_entry_id, third_posted.json()["entry_id"]}
                assert report_after["status"] == "preliminary" and not report_after["statutory_certified"]
            late_replay = await api.post(final_url + "/confirm", json=final_command)
            assert late_replay.status_code == 201 and late_replay.json()["id"] == final_entry_id, late_replay.text


async def test_foreign_late_cost_requires_rate_evidence_and_posts_byn_package(issuance_pg, pg_book):
    api, factory = issuance_pg
    api.headers["X-User"] = "tester"
    async with factory() as session:
        await session.execute(text("SELECT setval(pg_get_serial_sequence('accounting.account', 'id'), (SELECT max(id) FROM accounting.account))"))
        path, options = await source_options(api, session, pg_book)
    source_preview = await api.post(path + "/preview", json=options)
    assert source_preview.status_code == 200, source_preview.text
    source_confirm = await api.post(path + "/confirm", json={**options, "digest": source_preview.json()["digest"]})
    assert source_confirm.status_code == 201, source_confirm.text
    receipt_id = int(path.rsplit("/", 1)[1])
    base = f"/procurement/organizations/{pg_book[0]}/additional-expenses"
    document = expense(receipt_id, currency="USD", amount="100.00")
    created = await api.post(base, json={"key": "foreign-fx-evidence", "document": document},
                              headers={"X-Expected-Principal": "tester"})
    assert created.status_code == 201, created.text
    from modules.accounting.models import Policy

    async with factory() as session:
        session.add(Currency(code="USD", title="Synthetic USD"))
        await session.execute(text("SELECT setval(pg_get_serial_sequence('accounting.policy', 'id'), (SELECT max(id) FROM accounting.policy))"))
        policy_row = Policy(organization_id=pg_book[0], effective_from=date(2026, 9, 12),
            reference="Synthetic foreign late-cost policy", inventory_method="specific",
            allocation_basis="direct_cost", depreciation_method="straight_line",
            normative_reference="Synthetic only", normative_verified=False,
            late_cost_allocation={"basis": "quantity", "rounding": "largest_remainder_cent"},
            approved_by="tester")
        session.add(policy_row)
        await session.commit()
        policy_id = policy_row.id
    allocation = {"expected_version": 1, "policy_id": policy_id, "posting_date": "2026-09-12",
        "capitalizable_amount_byn": "320.00", "excluded_amount_byn": "0.00",
        "classification_evidence": "Synthetic explicit foreign cost classification",
        "conversion": {"currency": "USD", "rate": "3.2", "rate_scale": 1,
                       "rate_date": "2026-09-10", "rate_source": "Synthetic official rate evidence"}}
    url = f"/accounting/organizations/{pg_book[0]}/additional-expenses/{created.json()['id']}"
    preview = await api.post(url + "/preview", json=allocation)
    assert preview.status_code == 200, preview.text
    calculation = preview.json()
    assert calculation["source_amount_byn"] == "320.00"
    prepared = await api.post(url + "/posting-preview", json={"allocation": allocation,
        "accounts": {"settlement_account": "60", "excluded_costs": []}})
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["posting"]["rule_version"] == "late-cost-fx-v1"
    assert prepared.json()["posting"]["lines"][-1]["amount"] == "320.00"
    confirmed = await api.post(url + "/confirm", json={"allocation": allocation,
        "accounts": {"settlement_account": "60", "excluded_costs": []}, "request_key": str(uuid4()),
        "expected_basis_digest": prepared.json()["basis_digest"], "expected_digest": prepared.json()["digest"]},
        headers={"X-Expected-Principal": "tester"})
    assert confirmed.status_code == 201, confirmed.text
    async with factory() as session:
        saved = await verify_late_cost_receipt(session, pg_book[0], confirmed.json()["entry_id"], ProcurementSourceService())
        assert saved.lines[-1].amount == Decimal("320.00")
