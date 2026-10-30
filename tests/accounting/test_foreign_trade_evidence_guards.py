"""Trade review must bind exact source facts and an immutable replay payload."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from modules.accounting import foreign_trade_register as trade
from modules.accounting import models, service
from tests.accounting.test_foreign_trade_register import eaeu_command


def command(**changes):
    base = eaeu_command(SimpleNamespace(id=1, digest="a" * 64), SimpleNamespace(id=2))
    base.update(changes)
    return base


def export_command(**changes):
    return command(trade_mode="export", customs_reference="SYNTHETIC-EXPORT",
                   export_evidence="Synthetic transport review", import_vat="0.00", **changes)


def fx_command(**changes):
    return command(currency="USD", original_amount="10.00", rate="3.000000",
                   rate_scale=1, rate_date="2026-09-01", rate_source="Synthetic rate", **changes)


@pytest.mark.parametrize(("field", "value"), [
    ("contract_reference", "CHANGED-CONTRACT"), ("invoice_reference", "CHANGED-INVOICE"),
    ("partner_country", "RU"), ("eaeu_reference", "CHANGED-DOCUMENT"),
    ("incoterms", "FOB"), ("import_vat", "19.00"),
    ("evidence", "Different synthetic reviewed evidence"),
])
async def test_replay_key_rejects_changed_review_payload(db, book, posting, field, value):
    entry = await service.post(db, book[0], posting("synthetic-trade-replay"), "tester")
    line = await db.scalar(select(models.Line).where(models.Line.entry_id == entry.id, models.Line.side == "debit"))
    body = eaeu_command(entry, line)
    prepared = await trade.prepare_register(db, book[0], trade.ForeignTradeRegisterInput.model_validate(body))
    original = {**body, "digest": prepared["digest"]}
    row = await trade.confirm_register(db, book[0], trade.ForeignTradeRegisterConfirmInput.model_validate(original), "tester")
    await db.commit()
    before = dict(row.command)
    changed = trade.ForeignTradeRegisterConfirmInput.model_validate({**original, field: value})
    with pytest.raises(service.AccountingError, match="reused with different content"):
        await trade.confirm_register(db, book[0], changed, "tester")
    assert row.command == before
    assert await db.scalar(select(func.count()).select_from(models.ForeignTradeRegisterEntry)) == 1
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == 1
    replay = await trade.confirm_register(db, book[0], trade.ForeignTradeRegisterConfirmInput.model_validate(original), "tester")
    assert replay.id == row.id and replay.command == before


@pytest.mark.parametrize("changed", [False, True])
async def test_new_key_cannot_reuse_another_keys_digest(db, book, posting, changed):
    entry = await service.post(db, book[0], posting("synthetic-trade-line-replay"), "tester")
    line = await db.scalar(select(models.Line).where(models.Line.entry_id == entry.id, models.Line.side == "debit"))
    original = eaeu_command(entry, line)
    preview = await trade.prepare_register(db, book[0], trade.ForeignTradeRegisterInput.model_validate(original))
    original["digest"] = preview["digest"]
    row = await trade.confirm_register(db, book[0], trade.ForeignTradeRegisterConfirmInput.model_validate(original), "tester")
    await db.commit()
    repeated = {**original, "request_key": str(uuid4())}
    if changed:
        repeated["contract_reference"] = "Different synthetic contract"
    with pytest.raises(service.AccountingError, match="already registered with different content"):
        await trade.confirm_register(db, book[0], trade.ForeignTradeRegisterConfirmInput.model_validate(repeated), "tester")
    assert row.command == trade.ForeignTradeRegisterConfirmInput.model_validate(original).model_dump(mode="json")
    assert await db.scalar(select(func.count()).select_from(models.ForeignTradeRegisterEntry)) == 1
    assert await trade.register_result(db, book[0], repeated["request_key"]) is None


@pytest.mark.parametrize(("changes", "message"), [
    ({"incoterms": None}, "Incoterms"),
    ({"eaeu_reference": None}, "accompanying"),
    ({"trade_mode": "third_country_import", "customs_reference": None}, "customs"),
    ({"trade_mode": "export", "customs_reference": "DECL", "export_evidence": None}, "transport"),
    ({"trade_mode": "export", "customs_reference": "DECL", "export_evidence": "Evidence", "import_vat": "1.00"}, "not valid"),
])
def test_missing_lane_evidence_is_not_inferred(changes, message):
    with pytest.raises(ValueError, match=message):
        trade.ForeignTradeRegisterInput.model_validate(command(**changes))


FX_FIELDS = {"original_amount": "10.00", "rate": "3.000000", "rate_scale": 1,
             "rate_date": "2026-09-01", "rate_source": "Synthetic rate"}


@pytest.mark.parametrize("field", list(FX_FIELDS))
def test_byn_cannot_borrow_foreign_exchange_metadata(field):
    with pytest.raises(ValueError, match="BYN trade evidence"):
        trade.ForeignTradeRegisterInput.model_validate(command(**{field: FX_FIELDS[field]}))


@pytest.mark.parametrize("field", list(FX_FIELDS))
def test_fx_requires_every_explicit_fact(field):
    body = fx_command()
    body[field] = None
    with pytest.raises(ValueError, match="Foreign-currency"):
        trade.ForeignTradeRegisterInput.model_validate(body)


@pytest.mark.parametrize("value", ["2026-13", "2026-1", "0000-09"])
def test_period_is_a_real_canonical_month(value):
    with pytest.raises(service.AccountingError, match="YYYY-MM"):
        trade._period(value)


@pytest.mark.parametrize("failure", [
    "missing_entry", "missing_line", "stale_digest", "wrong_currency", "export_debit", "export_account",
    "import_credit", "import_account", "closed_period", *["byn_" + f for f in FX_FIELDS],
    *["fx_" + f for f in FX_FIELDS],
])
async def test_source_evidence_refuses_wrong_or_changed_facts(failure):
    body = fx_command() if failure.startswith("fx_") else export_command() if failure.startswith("export_") else command()
    data = trade.ForeignTradeRegisterInput.model_validate(body)
    entry = SimpleNamespace(digest=data.expected_entry_digest)
    line = SimpleNamespace(currency=data.currency, side="credit" if failure.startswith("export_") else "debit",
                           account_code="90.1" if failure.startswith("export_") else "41",
                           **{f: getattr(data, f) for f in FX_FIELDS})
    if failure == "missing_entry":
        entry = None
    elif failure == "missing_line":
        line = None
    elif failure == "stale_digest":
        entry.digest = "b" * 64
    elif failure == "wrong_currency":
        line.currency = "EUR"
    elif failure in {"export_debit", "import_credit"}:
        line.side = "debit" if failure == "export_debit" else "credit"
    elif failure in {"export_account", "import_account"}:
        line.account_code = "51"
    elif failure.startswith("byn_"):
        setattr(line, failure[4:], FX_FIELDS[failure[4:]])
    elif failure.startswith("fx_"):
        setattr(line, failure[3:], None)
    session = AsyncMock()
    session.scalar.side_effect = [entry, line, 1 if failure == "closed_period" else None]
    with pytest.raises(service.AccountingError):
        await trade._source(session, 1, data)
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.parametrize("method", ["worksheet", "register_rows"])
async def test_reversed_report_dates_refuse_before_reading_source(method):
    session = AsyncMock()
    with pytest.raises(service.AccountingError, match="End precedes start"):
        await getattr(trade, method)(session, 1, date(2026, 9, 2), date(2026, 9, 1))
    session.execute.assert_not_awaited()
    session.scalars.assert_not_awaited()


async def test_stale_confirmation_digest_creates_no_register_row(db, book, posting):
    entry = await service.post(db, book[0], posting("synthetic-stale-trade"), "tester")
    line = await db.scalar(select(models.Line).where(models.Line.entry_id == entry.id, models.Line.side == "debit"))
    data = trade.ForeignTradeRegisterConfirmInput.model_validate({**eaeu_command(entry, line), "digest": "b" * 64})
    with pytest.raises(service.AccountingError, match="review it again"):
        await trade.confirm_register(db, book[0], data, "tester")
    assert await db.scalar(select(func.count()).select_from(models.ForeignTradeRegisterEntry)) == 0
    assert await trade.register_result(db, book[0], uuid4()) is None
