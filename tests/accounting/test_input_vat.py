from datetime import date
from uuid import uuid4

from sqlalchemy import select

from modules.accounting import models, service


async def test_input_vat_worksheet_uses_posted_snapshots_and_separates_openings(client, db, book, posting):
    for code in ["18", "18.1", "180"]:
        db.add(models.Account(organization_id=book[0], code=code, title="Original VAT title", category="asset", valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False, quantity_tracking=False, cash=False, normative_ref="Synthetic"))
    await db.commit()
    await service.post(db, book[0], posting("opening", "18", "80", amount="7", opening=True), "tester")
    good = posting("vat-source", "18.1", "60", amount="20")
    good.lines[0].dimensions = {"vat_rate": "20", "vat_basis": "Synthetic invoice", "counterparty": "Supplier"}
    entry = await service.post(db, book[0], good, "tester")
    await service.post(db, book[0], posting("vat-credit", "60", "18", amount="5"), "tester")
    await service.post(db, book[0], posting("not-vat", "180", "60", amount="99"), "tester")
    await service.post(db, book[0], posting("future", "18", "60", amount="11", posting_date="2026-10-01"), "tester")
    await db.commit()
    response = await client.get(f"/accounting/organizations/{book[0]}/input-vat-lines", params={"start": "2026-09-01", "end": "2026-09-30"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["rows"]) == 3
    assert result["totals"] == {"debit": "20.00", "credit": "5.00", "opening_debit": "7.00", "opening_credit": "0.00"}
    row = next(row for row in result["rows"] if row["entry_id"] == entry.id)
    assert row["review_issues"] == [] and row["source"] == "vat-source"
    assert row["account_title"] == "Original VAT title"
    assert row["operation"] == good.operation
    assert result["rows_needing_metadata_review"] == 2
    assert not result["deduction_assessed"] and not result["statutory_certified"]
    assert (await client.get("/accounting/organizations/999/input-vat-lines", params={"start": "2026-09-01", "end": "2026-09-30"})).status_code == 403
    assert (await client.get(f"/accounting/organizations/{book[0]}/input-vat-lines", params={"start": "2026-10-01", "end": "2026-09-30"})).status_code == 422


async def test_input_vat_register_requires_explicit_evidence_and_is_idempotent(client, db, book, posting):
    db.add(models.Account(organization_id=book[0], code="18.1", title="Input VAT", category="asset",
                          valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
                          quantity_tracking=False, cash=False, normative_ref="Synthetic"))
    await db.commit()
    source = posting("vat-register-source", "18.1", "60", amount="20")
    source.lines[0].dimensions = {"vat_rate": "20", "vat_basis": "Invoice and ЭСЧФ", "counterparty": "Supplier"}
    entry = await service.post(db, book[0], source, "tester")
    line = await db.scalar(select(models.Line).where(models.Line.entry_id == entry.id, models.Line.side == "debit"))
    request_key = str(uuid4())
    command = {
        "request_key": request_key, "entry_id": entry.id, "line_id": line.id,
        "expected_entry_digest": entry.digest, "tax_period": "2026-09",
        "invoice_reference": "INV-18", "eschf_identifier": "ЭСЧФ-18",
        "deduction_status": "eligible", "eschf_status": "provided",
        "right_basis": "Проверены первичный документ и право на вычет по политике",
        "evidence": "Счёт-фактура и ЭСЧФ сверены бухгалтером",
    }
    preview = await client.post(f"/accounting/organizations/{book[0]}/input-vat-register/preview", json=command)
    assert preview.status_code == 200, preview.text
    prepared = preview.json()
    assert prepared["status"] == "reviewed_input_vat"
    assert prepared["register_available"] is True
    assert prepared["statutory_certified"] is False
    assert prepared["deduction_assessed"] is False
    assert await db.scalar(select(models.InputVatRegisterEntry.id)) is None
    confirm = await client.post(
        f"/accounting/organizations/{book[0]}/input-vat-register/confirm",
        headers={"X-Expected-Principal": "tester"}, json={**command, "digest": prepared["digest"]},
    )
    assert confirm.status_code == 201, confirm.text
    assert confirm.json()["posted"] is False
    assert confirm.json()["deduction_status"] == "eligible"
    replay = await client.post(
        f"/accounting/organizations/{book[0]}/input-vat-register/confirm",
        headers={"X-Expected-Principal": "tester"}, json={**command, "digest": prepared["digest"]},
    )
    assert replay.status_code == 201 and replay.json()["id"] == confirm.json()["id"]
    period = await db.scalar(select(models.Period).where(models.Period.organization_id == book[0], models.Period.month == "2026-09"))
    period.closed = True
    period.generation += 1
    await db.commit()
    closed_replay = await client.post(
        f"/accounting/organizations/{book[0]}/input-vat-register/confirm",
        headers={"X-Expected-Principal": "tester"}, json={**command, "digest": prepared["digest"]},
    )
    assert closed_replay.status_code == 201 and closed_replay.json()["id"] == confirm.json()["id"]
    status = await client.get(f"/accounting/organizations/{book[0]}/input-vat-register/{request_key}")
    assert status.status_code == 200 and status.json()["entry_id"] == entry.id
    worksheet = await client.get(f"/accounting/organizations/{book[0]}/input-vat-lines",
                                 params={"start": "2026-09-01", "end": "2026-09-30"})
    row = next(row for row in worksheet.json()["rows"] if row["line_id"] == line.id)
    assert row["registered"] is True and row["register_eschf_status"] == "provided"
    assert worksheet.json()["rows_needing_register_review"] == 0


async def test_input_vat_register_never_marks_credit_line_eligible(client, db, book, posting):
    db.add(models.Account(organization_id=book[0], code="18.1", title="Input VAT", category="asset",
                          valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
                          quantity_tracking=False, cash=False, normative_ref="Synthetic"))
    await db.commit()
    source = posting("vat-credit-register-source", "60", "18.1", amount="5")
    entry = await service.post(db, book[0], source, "tester")
    line = await db.scalar(select(models.Line).where(models.Line.entry_id == entry.id, models.Line.side == "credit"))
    body = {
        "request_key": str(uuid4()), "entry_id": entry.id, "line_id": line.id,
        "expected_entry_digest": entry.digest, "tax_period": "2026-09", "invoice_reference": "REV-18",
        "deduction_status": "eligible", "eschf_status": "not_required",
        "right_basis": "Недопустимая классификация кредитовой строки",
        "evidence": "Проверка возврата входного НДС бухгалтером",
    }
    response = await client.post(f"/accounting/organizations/{book[0]}/input-vat-register/preview", json=body)
    assert response.status_code == 422 and "credit" in response.json()["detail"].lower()
