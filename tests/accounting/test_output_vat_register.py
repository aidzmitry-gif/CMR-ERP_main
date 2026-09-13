from datetime import date
from uuid import uuid4

from sqlalchemy import select

from modules.accounting import models, service


async def test_output_vat_register_requires_explicit_treatment_and_is_idempotent(client, db, book, posting):
    for code, title, category in [("90.2", "Output VAT", "income"), ("68.2", "VAT payable", "liability")]:
        db.add(models.Account(organization_id=book[0], code=code, title=title, category=category,
                              valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
                              quantity_tracking=False, cash=False, normative_ref="Synthetic"))
    await db.commit()
    source = posting("output-vat-register-source", "90.2", "68.2", amount="20")
    source.lines[0].dimensions = {"vat_rate": "20", "vat_basis": "Sale invoice", "counterparty": "Buyer"}
    entry = await service.post(db, book[0], source, "tester")
    line = await db.scalar(select(models.Line).where(models.Line.entry_id == entry.id, models.Line.side == "debit"))
    command = {
        "request_key": str(uuid4()), "entry_id": entry.id, "line_id": line.id,
        "expected_entry_digest": entry.digest, "tax_period": "2026-09", "invoice_reference": "SALE-18",
        "tax_treatment": "standard", "eschf_identifier": "ЭСЧФ-SALE-18", "eschf_status": "provided",
        "treatment_basis": "Ставка и основание проверены по первичному документу",
        "export_evidence": None, "evidence": "Счёт-фактура и ЭСЧФ сверены бухгалтером",
    }
    preview = await client.post(f"/accounting/organizations/{book[0]}/output-vat-register/preview", json=command)
    assert preview.status_code == 200, preview.text
    prepared = preview.json()
    assert prepared["status"] == "reviewed_output_vat" and prepared["vat_treatment_verified"] is False
    confirm = await client.post(
        f"/accounting/organizations/{book[0]}/output-vat-register/confirm",
        headers={"X-Expected-Principal": "tester"}, json={**command, "digest": prepared["digest"]},
    )
    assert confirm.status_code == 201, confirm.text
    assert confirm.json()["posted"] is False and confirm.json()["tax_treatment"] == "standard"
    replay = await client.post(
        f"/accounting/organizations/{book[0]}/output-vat-register/confirm",
        headers={"X-Expected-Principal": "tester"}, json={**command, "digest": prepared["digest"]},
    )
    assert replay.status_code == 201 and replay.json()["id"] == confirm.json()["id"]
    status = await client.get(f"/accounting/organizations/{book[0]}/output-vat-register/{command['request_key']}")
    assert status.status_code == 200 and status.json()["line_id"] == line.id
    listing = await client.get(f"/accounting/organizations/{book[0]}/output-vat-register",
                               params={"start": "2026-09-01", "end": "2026-09-30"})
    assert listing.status_code == 200 and listing.json()["totals_by_treatment"] == {"standard": "20.00"}


async def test_output_vat_register_requires_export_evidence(client, db, book, posting):
    db.add(models.Account(organization_id=book[0], code="90.2", title="Output VAT", category="income",
                          valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
                          quantity_tracking=False, cash=False, normative_ref="Synthetic"))
    db.add(models.Account(organization_id=book[0], code="68.2", title="VAT payable", category="liability",
                          valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
                          quantity_tracking=False, cash=False, normative_ref="Synthetic"))
    await db.commit()
    source = posting("output-vat-export-source", "90.2", "68.2", amount="10")
    entry = await service.post(db, book[0], source, "tester")
    line = await db.scalar(select(models.Line).where(models.Line.entry_id == entry.id, models.Line.side == "debit"))
    body = {
        "request_key": str(uuid4()), "entry_id": entry.id, "line_id": line.id,
        "expected_entry_digest": entry.digest, "tax_period": "2026-09", "invoice_reference": "EXP-1",
        "tax_treatment": "zero_export", "eschf_status": "pending",
        "treatment_basis": "Экспортная ставка требует отдельной проверки",
        "evidence": "Проверка экспортной операции бухгалтером",
    }
    response = await client.post(f"/accounting/organizations/{book[0]}/output-vat-register/preview", json=body)
    assert response.status_code == 422 and "export evidence" in response.json()["detail"][0]["msg"].lower()


async def test_output_vat_worksheet_lists_candidates_and_register_state(client, db, book, posting):
    for code, title, category in [("90.2", "Output VAT", "income"), ("68.2", "VAT payable", "liability")]:
        db.add(models.Account(organization_id=book[0], code=code, title=title, category=category,
                              valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
                              quantity_tracking=False, cash=False, normative_ref="Synthetic"))
    await db.commit()
    source = posting("output-vat-worksheet-source", "90.2", "68.2", amount="12")
    source.lines[0].dimensions = {"vat_rate": "20", "vat_basis": "Sale invoice", "counterparty": "Buyer"}
    entry = await service.post(db, book[0], source, "tester")
    response = await client.get(f"/accounting/organizations/{book[0]}/output-vat-lines",
                                params={"start": "2026-09-01", "end": "2026-09-30"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["rows_needing_register_review"] == 1
    assert data["rows"][0]["entry_id"] == entry.id
    assert data["rows"][0]["tax_treatment"] == "not_assessed"
    assert data["rows"][0]["review_issues"] == []
