from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from core.domain.models import User
from core.services.auth import CurrentUser, get_current_user
from modules.accounting import service
from modules.accounting.models import Account, Inbox
from modules.accounting.module import AccountingModule, get_module, on_posting_requested
from modules.accounting.schemas import CloseInput, PostingInput


async def test_organization_setup_accounts_policy_and_permissions(client, db, book):
    created = await client.post("/accounting/organizations", json={"name": "Pilot", "unp": "123456789"})
    assert created.status_code == 201, created.text
    org = created.json()["id"]
    prefix = f"/accounting/organizations/{org}"
    assert len((await client.get("/accounting/organizations")).json()) == 2
    account = dict(code="51", title="Банк", category="asset", valid_from="2026-01-01",
                   cash=True, normative_ref="test")
    assert (await client.post(prefix + "/accounts", json=account)).status_code == 201
    assert (await client.post(prefix + "/accounts", json=account)).status_code == 409
    assert len((await client.get(prefix + "/accounts?on=2026-09-01")).json()) == 1
    policy = dict(effective_from="2026-01-01", reference="test", inventory_method="fifo",
                  allocation_basis="direct_cost", depreciation_method="straight_line",
                  normative_reference="test", normative_verified=False)
    assert (await client.post(prefix + "/policies", json=policy)).status_code == 201
    assert len((await client.get(prefix + "/policies")).json()) == 1
    assert (await client.put(prefix + "/members", json={"subject": "tester", "role": "reader"})).status_code == 422
    assert (await client.put(prefix + "/members", json={"subject": "reader", "role": "reader"})).status_code == 200
    assert (await client.put(prefix + "/members", json={"subject": "reader", "role": "accountant"})).status_code == 200
    assert (await client.put(prefix + "/members", json={"subject": "reader", "role": "reader"})).status_code == 200
    db.add(User(username="reader", full_name="Synthetic reader", role="finance", status="active"))
    await db.commit()
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("reader", ["finance"])
    assert (await client.get(prefix + "/accounts?on=2026-09-01")).status_code == 200
    assert (await client.post(prefix + "/accounts", json=account)).status_code == 403
    assert (await client.post("/accounting/organizations", json={"name": "No", "unp": "111111111"})).status_code == 403
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("anonymous", ["director"])
    assert (await client.get("/accounting/organizations")).status_code == 403
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("tester", ["Гость"])
    assert (await client.get("/accounting/organizations")).status_code == 403


async def test_preview_import_inbox_closing_and_reopening(client, db, book, posting, opening_package):
    prefix = f"/accounting/organizations/{book[0]}"
    batch = opening_package([posting("opening", "51", "80", opening=True)], batch="opening-1")
    assert (await client.post(prefix + "/imports/preview", json=batch)).status_code == 200
    result = await client.post(prefix + "/imports/confirm", json=batch)
    assert result.status_code == 200, result.text
    assert (await client.post(prefix + "/imports/confirm", json=batch)).json()["entry_ids"] == result.json()["entry_ids"]
    data = posting("event").model_dump(mode="json")
    assert (await client.post(prefix + "/preview", json=data)).status_code == 200
    row = await service.receive(db, book[0], "event-key", "2026-09", data)
    row_id = row.id
    assert (await service.receive(db, book[0], "event-key", "2026-09", data)).id == row_id
    with pytest.raises(service.AccountingError, match="conflict"):
        await service.receive(db, book[0], "event-key", "2026-10", data)
    await db.commit()
    assert len((await client.get(prefix + "/inbox")).json()) == 1
    assert (await client.post(prefix + f"/inbox/{row_id}/confirm")).status_code == 200
    assert (await client.get(prefix + "/inbox")).json() == []
    assert (await client.post(prefix + "/inbox/99999/confirm")).status_code == 422
    entries = await client.get(prefix + "/entries?start=2026-09-01&end=2026-09-30")
    assert len(entries.json()) == 2
    assert (await client.get(prefix + "/entries/99999")).status_code == 404
    periods = (await client.get(prefix + "/periods")).json()
    closing = dict(expected_generation=periods[0]["generation"],
                   evidence={k: "checked" for k in service.CLOSE_STEPS})
    assert (await client.post(prefix + "/periods/2026-13/close", json=closing)).status_code == 422
    assert (await client.post(prefix + "/periods/2026-09/close", json=closing)).status_code == 200
    assert (await client.post(prefix + "/periods/2026-09/close", json=closing)).status_code == 422
    report = await client.get(prefix + "/reports?start=2026-09-01&end=2026-09-30")
    assert report.json()["status"] == "closed_periods"
    assert (await client.get(prefix + "/reports?start=2026-09-01&end=2026-10-31")).json()["status"] == "preliminary"
    assert (await client.post(prefix + "/periods/2026-09/reopen", json={"reason": "Control correction"})).status_code == 200
    assert (await client.get(prefix + "/reports?start=2026-09-30&end=2026-09-01")).status_code == 422


async def test_closed_report_stays_preliminary_when_vat_evidence_is_unresolved(client, db, book, posting):
    prefix = f"/accounting/organizations/{book[0]}"
    db.add(Account(organization_id=book[0], code="18", title="Входной НДС", category="asset",
                   valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
                   quantity_tracking=False, cash=False, normative_ref="synthetic"))
    await db.flush()
    payload = posting("unregistered-vat", debit="18", credit="60", amount="10.00",
                      posting_date="2026-09-01", document_date="2026-09-01", operation_date="2026-09-01")
    await service.post(db, book[0], payload, "tester")
    await db.commit()
    periods = (await client.get(prefix + "/periods")).json()
    close = {"expected_generation": periods[0]["generation"],
             "evidence": {step: "Synthetic reviewed control" for step in service.CLOSE_STEPS}}
    assert (await client.post(prefix + "/periods/2026-09/close", json=close)).status_code == 200
    report = (await client.get(prefix + "/reports?start=2026-09-01&end=2026-09-30")).json()
    assert report["status"] == "preliminary"
    assert any(item["code"] == "input_vat_register" for item in report["review_items"])


async def test_fail_closed_policy_periods_and_sources(db, book, posting):
    with pytest.raises(service.AccountingError, match="not found"):
        await service.lock_organization(db, 99999)
    with pytest.raises(service.AccountingError, match="policy"):
        await service.post(db, book[0], posting(policy_id=99999), "tester")
    with pytest.raises(service.AccountingError, match="precede"):
        await service.post(db, book[0], posting(document_date="2026-10-01"), "tester")
    await service.post(db, book[0], posting(), "tester")
    with pytest.raises(service.AccountingError, match="latest"):
        await service.post(db, book[0], posting(source_version=2), "tester")
    with pytest.raises(service.AccountingError, match="reference"):
        await service.post(db, book[0], posting("correction", correction_of=99999), "tester")
    with pytest.raises(service.AccountingError, match="Opening"):
        await service.post(db, book[0], posting("opening", opening=True), "tester")
    with pytest.raises(service.AccountingError, match="changed"):
        await service.close_period(db, book[0], "2026-09", CloseInput(expected_generation=0, evidence={}), "tester")
    with pytest.raises(service.AccountingError, match="Evidence"):
        await service.close_period(db, book[0], "2026-09", CloseInput(expected_generation=1, evidence={}), "tester")
    await service.receive(db, book[0], "pending", "2026-09", posting("pending").model_dump(mode="json"))
    with pytest.raises(service.AccountingError, match="Unposted"):
        await service.close_period(db, book[0], "2026-09", CloseInput(
            expected_generation=1, evidence={k: "test" for k in service.CLOSE_STEPS}), "tester")
    await db.rollback()


async def test_analytics_and_tracking_validation(db, book, posting):
    db.add(Account(organization_id=book[0], code="10", title="Материалы", category="asset",
                   valid_from=date(2026, 1, 1), required_dimensions=["sku"], currency_tracking=False,
                   quantity_tracking=True, cash=False, normative_ref="test"))
    await db.flush()
    item = posting(debit="10").model_dump(mode="json")
    with pytest.raises(service.AccountingError, match="analytics"):
        await service.post(db, book[0], PostingInput.model_validate(item), "tester")
    item["lines"][0]["dimensions"] = {"sku": "test"}
    with pytest.raises(service.AccountingError, match="quantity"):
        await service.post(db, book[0], PostingInput.model_validate(item), "tester")
    item["lines"][0]["quantity"] = "1.25"
    await service.post(db, book[0], PostingInput.model_validate(item), "tester")


async def test_event_adapter_and_registration(db, book, posting):
    from modules.accounting import expense_routes, routes

    registered = []
    routers = []

    def include_router(router, *, prefix):
        routers.append((router, prefix))
        registered.append("router")

    core = SimpleNamespace(services=SimpleNamespace(), include_router=include_router,
                           subscribe=lambda *a: registered.append("event"),
                           register_widget=lambda *a: registered.append("widget"),
                           register_reference=lambda *a: registered.append("reference"))
    module = get_module()
    assert isinstance(module, AccountingModule)
    module.register(core)
    assert registered == ["router", "router", "event", "widget", "reference"]
    assert routers == [(routes.router, "/accounting"), (expense_routes.router, "/accounting")]
    ctx = SimpleNamespace(session=db)
    with pytest.raises(service.AccountingError, match="organization"):
        await on_posting_requested({"organization_id": None}, ctx)
    await on_posting_requested(dict(organization_id=book[0], event_key="evt", month="2026-09",
                                   posting=posting().model_dump(mode="json")), ctx)
    assert await db.scalar(select(Inbox.id)) is not None


async def test_chart_catalogue_is_read_only_and_does_not_certify_current_law(client):
    catalog = (await client.get("/accounting/catalog")).json()
    assert catalog["current_normative_verified"] is False
    assert catalog["version"] == "BY-MF50-2026-01-01-review-required"
    assert catalog["current_revision_reference"] == "2025-10-31"
    assert catalog["verified_through"] == "2025-08-25 для перечня счетов; 2025-10-31 частично"
    review = catalog["normative_review"]
    assert review["status"] == "requires_primary_edition_review"
    assert review["checked_at"] == "2026-09-20"
    assert review["verified_through"] == "2025-08-25 (полный текст); 2025-10-31 (опубликованная область)"
    assert review["source_access"] == "official_2022_pdf_and_2025_legal_database_review"
    assert review["evidence"][1] == {
        "document": "Постановление Минфина № 73",
        "url": "https://base2.spinform.ru/show_doc.fwx?rgn=171243",
        "source_kind": "legal_database_full_text",
        "coverage": "Полный опубликованный текст: пункт 1.7 меняет преамбулу и Инструкцию, но не приложение 1 с номерами счетов и субсчетами.",
        "full_text_verified": True,
    }
    assert review["evidence"][2]["full_text_verified"] is False
    assert "Полный первичный текст" in review["blocking_reasons"][1]
    amendments = catalog["known_amendments"]
    assert [(item["document"], item["impact_on_chart"], item["full_text_verified"]) for item in amendments] == [
        ("Постановление Минфина № 73", "no_chart_code_change", True),
        ("Постановление Минфина № 126", "instruction_scope_only", False),
    ]
    assert amendments[0]["source_kind"] == "legal_database_full_text"
    assert amendments[1]["source_kind"] == "legal_database_published_scope"
    accounts = (await client.get("/accounting/catalog/accounts")).json()
    assert len(accounts) == len(catalog["accounts"])
    assert len({row["code"] for row in accounts}) == len(accounts)
    assert next(row for row in accounts if row["code"] == "90.4")["parent"] == "90"
    assert next(row for row in accounts if row["code"] == "003")["off_balance"] is True
    assert (await client.post("/accounting/catalog/accounts", json={})).status_code == 405
