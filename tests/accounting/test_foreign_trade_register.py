from uuid import uuid4

import pytest
from sqlalchemy import select

from modules.accounting import models, service
from modules.accounting.foreign_trade_register import ForeignTradeRegisterInput


def eaeu_command(entry, line, *, request_key=None):
    return {
        "request_key": str(request_key or uuid4()), "entry_id": entry.id, "line_id": line.id,
        "expected_entry_digest": entry.digest, "tax_period": "2026-09", "trade_mode": "eaeu_import",
        "partner_country": "KZ", "contract_reference": "EAEU-CONTRACT-1", "invoice_reference": "EAEU-INV-1",
        "customs_reference": None, "eaeu_reference": "EAEU-DOC-1", "incoterms": "DAP",
        "currency": "BYN", "customs_duty": "0.00", "import_vat": "20.00",
        "export_evidence": None, "evidence": "Договор и товаросопроводительный документ сверены бухгалтером",
    }


async def test_foreign_trade_register_is_explicit_idempotent_and_listed(client, db, book, posting):
    entry = await service.post(db, book[0], posting("trade-eaeu-source", "41", "60", amount="120.00"), "tester")
    line = await db.scalar(select(models.Line).where(models.Line.entry_id == entry.id, models.Line.side == "debit"))
    command = eaeu_command(entry, line)
    preview = await client.post(f"/accounting/organizations/{book[0]}/foreign-trade-register/preview", json=command)
    assert preview.status_code == 200, preview.text
    prepared = preview.json()
    assert prepared["status"] == "reviewed_foreign_trade" and prepared["trade_treatment_verified"] is False
    confirm = await client.post(
        f"/accounting/organizations/{book[0]}/foreign-trade-register/confirm",
        headers={"X-Expected-Principal": "tester"}, json={**command, "digest": prepared["digest"]},
    )
    assert confirm.status_code == 201, confirm.text
    assert confirm.json()["posted"] is False and confirm.json()["trade_mode"] == "eaeu_import"
    replay = await client.post(
        f"/accounting/organizations/{book[0]}/foreign-trade-register/confirm",
        headers={"X-Expected-Principal": "tester"}, json={**command, "digest": prepared["digest"]},
    )
    assert replay.status_code == 201 and replay.json()["id"] == confirm.json()["id"]
    status = await client.get(f"/accounting/organizations/{book[0]}/foreign-trade-register/{command['request_key']}")
    assert status.status_code == 200 and status.json()["line_id"] == line.id
    listing = await client.get(f"/accounting/organizations/{book[0]}/foreign-trade-register",
                               params={"start": "2026-09-01", "end": "2026-09-30"})
    assert listing.status_code == 200 and listing.json()["totals_by_trade_mode"] == {"eaeu_import": "120.00"}


async def test_foreign_trade_register_requires_lane_documents(client, db, book, posting):
    entry = await service.post(db, book[0], posting("trade-third-country-source", "41", "60", amount="80.00"), "tester")
    line = await db.scalar(select(models.Line).where(models.Line.entry_id == entry.id, models.Line.side == "debit"))
    body = {**eaeu_command(entry, line), "trade_mode": "third_country_import", "eaeu_reference": None,
            "customs_reference": None}
    response = await client.post(f"/accounting/organizations/{book[0]}/foreign-trade-register/preview", json=body)
    assert response.status_code == 422 and "customs declaration" in response.json()["detail"][0]["msg"].lower()


async def test_foreign_trade_register_export_binds_to_revenue_line(client, db, book, posting):
    source = posting("trade-export-source", "62", "90.1", amount="250.00")
    entry = await service.post(db, book[0], source, "tester")
    line = await db.scalar(select(models.Line).where(models.Line.entry_id == entry.id, models.Line.side == "credit"))
    body = {**eaeu_command(entry, line), "trade_mode": "export", "partner_country": "LT",
            "contract_reference": "EXPORT-CONTRACT", "invoice_reference": "EXPORT-INV",
            "customs_reference": "CUSTOMS-EXPORT-1", "eaeu_reference": None, "incoterms": None,
            "import_vat": "0.00", "export_evidence": "Транспортные и таможенные подтверждения сверены бухгалтером"}
    preview = await client.post(f"/accounting/organizations/{book[0]}/foreign-trade-register/preview", json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["source"]["account_code"] == "90.1"


def test_foreign_trade_input_rejects_unbacked_fx_and_export_import_costs():
    base = {
        "request_key": str(uuid4()), "entry_id": 1, "line_id": 1, "expected_entry_digest": "a" * 64,
        "tax_period": "2026-09", "trade_mode": "third_country_import", "partner_country": "CN",
        "contract_reference": "C", "invoice_reference": "I", "customs_reference": "CD",
        "eaeu_reference": None, "incoterms": "FOB", "currency": "USD", "original_amount": "10.00",
        "rate": "3.000000", "rate_scale": 1, "rate_date": "2026-09-01", "rate_source": "NB RB",
        "customs_duty": "1.00", "import_vat": "2.00", "export_evidence": None,
        "evidence": "Валютный источник и документы проверены бухгалтером",
    }
    ForeignTradeRegisterInput.model_validate(base)
    with pytest.raises(ValueError, match="Foreign-currency"):
        ForeignTradeRegisterInput.model_validate({**base, "rate_source": None})
    with pytest.raises(ValueError, match="not valid for an export"):
        ForeignTradeRegisterInput.model_validate({**base, "trade_mode": "export", "customs_duty": "1.00",
                                                  "currency": "BYN", "original_amount": None, "rate": None,
                                                  "rate_scale": None, "rate_date": None, "rate_source": None,
                                                  "customs_reference": "CD", "export_evidence": "Экспортные документы сверены"})
