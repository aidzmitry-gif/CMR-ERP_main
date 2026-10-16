"""PostgreSQL evidence for the source-bound import/export register."""
# ruff: noqa: F811 -- pytest fixtures are imported for registration.

from __future__ import annotations

import asyncio
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from modules.accounting import foreign_trade_register, service
from modules.accounting.models import Entry, ForeignTradeRegisterEntry, Line
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401

pytestmark = pytest.mark.integration


def import_command(entry: Entry, line: Line):
    return foreign_trade_register.ForeignTradeRegisterInput.model_validate({
        "request_key": "00000000-0000-0000-0000-000000000401",
        "entry_id": entry.id, "line_id": line.id, "expected_entry_digest": entry.digest,
        "tax_period": "2026-09", "trade_mode": "eaeu_import", "partner_country": "KZ",
        "contract_reference": "EAEU-CONTRACT-1", "invoice_reference": "EAEU-INV-1",
        "customs_reference": None, "eaeu_reference": "EAEU-DOC-1", "incoterms": "DAP",
        "currency": "BYN", "customs_duty": "0.00", "import_vat": "20.00",
        "export_evidence": None, "evidence": "ЕАЭС документы сверены бухгалтером",
    })


def export_command(entry: Entry, line: Line):
    return foreign_trade_register.ForeignTradeRegisterInput.model_validate({
        "request_key": "00000000-0000-0000-0000-000000000402",
        "entry_id": entry.id, "line_id": line.id, "expected_entry_digest": entry.digest,
        "tax_period": "2026-09", "trade_mode": "export", "partner_country": "LT",
        "contract_reference": "EXPORT-CONTRACT-1", "invoice_reference": "EXPORT-INV-1",
        "customs_reference": "CUSTOMS-EXPORT-1", "eaeu_reference": None, "incoterms": None,
        "currency": "BYN", "customs_duty": "0.00", "import_vat": "0.00",
        "export_evidence": "Транспортные и таможенные подтверждения сверены бухгалтером",
        "evidence": "Экспортный пакет сверен бухгалтером",
    })


async def test_foreign_trade_register_is_concurrent_replayable_and_database_guarded(
    pg_factory, pg_book, posting,
):
    async with pg_factory() as session:
        import_entry = await service.post(
            session, pg_book[0], posting("trade:eaeu:pg", "41", "60", amount="120.00"), "tester",
        )
        export_entry = await service.post(
            session, pg_book[0], posting("trade:export:pg", "62", "90.1", amount="250.00"), "tester",
        )
        await session.commit()

    async with pg_factory() as session:
        import_entry = await session.get(Entry, import_entry.id)
        export_entry = await session.get(Entry, export_entry.id)
        import_line = await session.scalar(select(Line).where(
            Line.entry_id == import_entry.id, Line.side == "debit", Line.account_code == "41",
        ))
        export_line = await session.scalar(select(Line).where(
            Line.entry_id == export_entry.id, Line.side == "credit", Line.account_code == "90.1",
        ))
        import_data = import_command(import_entry, import_line)
        export_data = export_command(export_entry, export_line)
        import_preview = await foreign_trade_register.prepare_register(session, pg_book[0], import_data)
        export_preview = await foreign_trade_register.prepare_register(session, pg_book[0], export_data)
        import_confirmed = foreign_trade_register.ForeignTradeRegisterConfirmInput.model_validate({
            **import_data.model_dump(mode="json"), "digest": import_preview["digest"],
        })
        export_confirmed = foreign_trade_register.ForeignTradeRegisterConfirmInput.model_validate({
            **export_data.model_dump(mode="json"), "digest": export_preview["digest"],
        })

    async def confirm(data):
        async with pg_factory() as session:
            try:
                row = await foreign_trade_register.confirm_register(session, pg_book[0], data, "tester")
                await session.commit()
                return row.id
            except BaseException:
                await session.rollback()
                raise

    import_ids = await asyncio.gather(*(confirm(import_confirmed) for _ in range(2)))
    export_ids = await asyncio.gather(*(confirm(export_confirmed) for _ in range(2)))
    assert import_ids[0] == import_ids[1]
    assert export_ids[0] == export_ids[1]

    async with pg_factory() as session:
        import_row = await session.get(ForeignTradeRegisterEntry, import_ids[0])
        export_row = await session.get(ForeignTradeRegisterEntry, export_ids[0])
        assert import_row is not None and import_row.trade_mode == "eaeu_import"
        assert export_row is not None and export_row.trade_mode == "export"
        assert await session.scalar(select(func.count()).select_from(ForeignTradeRegisterEntry)) == 2
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(text(
                "UPDATE accounting.foreign_trade_register_entry SET actor='forged' WHERE id=:id"
            ), {"id": import_ids[0]})
        await session.rollback()
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(text(
                "DELETE FROM accounting.foreign_trade_register_entry WHERE id=:id"
            ), {"id": export_ids[0]})
        await session.rollback()

    async with pg_factory() as session:
        import_entry = await session.get(Entry, import_entry.id)
        credit_line = await session.scalar(select(Line).where(
            Line.entry_id == import_entry.id, Line.side == "credit",
        ))
        forged_request = str(uuid4())
        forged = ForeignTradeRegisterEntry(
            organization_id=pg_book[0], request_key=forged_request, entry_id=import_entry.id,
            line_id=credit_line.id, source=import_entry.source, source_version=import_entry.source_version,
            entry_digest=import_entry.digest, posting_date=date(2026, 9, 1), tax_period="2026-09",
            trade_mode="eaeu_import", partner_country="KZ", contract_reference="FORGED",
            invoice_reference="FORGED", customs_reference=None, eaeu_reference="FORGED-EAEU",
            incoterms="DAP", amount="120.00", currency="BYN", original_amount=None, rate=None,
            rate_scale=None, rate_date=None, rate_source=None, customs_duty="0.00", import_vat="20.00",
            export_evidence=None, evidence="Поддельный пакет должен быть отклонён guard",
            command={"request_key": forged_request, "entry_id": import_entry.id,
                     "line_id": credit_line.id, "expected_entry_digest": import_entry.digest,
                     "trade_mode": "eaeu_import", "tax_period": "2026-09"},
            digest="0" * 64, actor="tester",
        )
        session.add(forged)
        with pytest.raises(DBAPIError, match="Import evidence"):
            await session.commit()
        await session.rollback()
