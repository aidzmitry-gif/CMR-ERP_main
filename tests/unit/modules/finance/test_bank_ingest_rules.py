from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.finance import bank_ingest


class Result:
    def __init__(self, rows=(), scalar=None):
        self.rows = list(rows)
        self.scalar = scalar

    def all(self):
        return self.rows

    def scalars(self):
        return self

    def scalar_one_or_none(self):
        return self.scalar


class Session:
    def __init__(self, *results):
        self.results = list(results)
        self.added = []

    async def execute(self, _statement):
        return self.results.pop(0)

    def add(self, value):
        self.added.append(value)


def payment(ref, amount="10", counterparty_ref=None, ident=1):
    return SimpleNamespace(
        id=ident, ref=ref, amount=amount, counterparty_ref=counterparty_ref,
        status="pending", kind="receivable",
    )


def test_bank_parsers_are_fail_soft_and_conservative():
    assert bank_ingest._to_decimal("1 000,50") is None
    assert bank_ingest._to_decimal("10.50") == Decimal("10.50")
    assert bank_ingest._to_decimal(float("inf")) is None
    assert bank_ingest._to_decimal(None) is None
    assert bank_ingest._digits("УНП-191 234 567") == "191234567"
    assert bank_ingest._ref_in_purpose("СЧ-100", "ОПЛАТА СЧ100") is True
    assert bank_ingest._ref_in_purpose("12", "12") is False
    assert bank_ingest._parse_date("2026-09-17T10:00:00") is not None
    assert bank_ingest._parse_date("bad") is None


@pytest.mark.asyncio
async def test_resolve_unp_and_match_candidate_rejects_ambiguous_money(monkeypatch):
    direct = payment("СЧ-100", counterparty_ref="УНП-191234567")
    assert await bank_ingest._resolve_payment_unp(Session(), direct) == "191234567"
    named = payment("СЧ-101", counterparty_ref="Alpha")
    assert await bank_ingest._resolve_payment_unp(Session(Result(scalar=SimpleNamespace(unp="222"))), named) == "222"
    assert await bank_ingest._resolve_payment_unp(Session(), payment("СЧ-102", counterparty_ref=None)) is None

    monkeypatch.setattr(bank_ingest, "sum_allocations", AsyncMock(return_value=Decimal("0")))
    monkeypatch.setattr(bank_ingest, "_resolve_payment_unp", AsyncMock(return_value=None))
    candidate = payment("СЧ-100", amount="10", ident=10)
    matched, reason = await bank_ingest._match_candidate(
        Session(Result([candidate])), {"purpose": "оплата СЧ-100"}, Decimal("7")
    )
    assert matched is candidate and reason == "matched"

    too_large, reason = await bank_ingest._match_candidate(
        Session(Result([candidate])), {"purpose": "оплата СЧ-100"}, Decimal("11")
    )
    assert too_large is None and "больше остатка" in reason
    missing, reason = await bank_ingest._match_candidate(Session(Result([])), {"purpose": "нет"}, Decimal("1"))
    assert missing is None and "не найден" in reason
    empty, reason = await bank_ingest._match_candidate(Session(Result([])), {"purpose": ""}, Decimal("1"))
    assert empty is None and "пустое" in reason

    two = [payment("СЧ-100", ident=1), payment("СЧ-100", ident=2)]
    many, reason = await bank_ingest._match_candidate(Session(Result(two)), {"purpose": "СЧ100"}, Decimal("1"))
    assert many is None and "несколько" in reason

    monkeypatch.setattr(bank_ingest, "_resolve_payment_unp", AsyncMock(return_value="999"))
    rejected, reason = await bank_ingest._match_candidate(
        Session(Result([candidate])), {"purpose": "СЧ100", "payer_unp": "111"}, Decimal("1")
    )
    assert rejected is None and "УНП" in reason


@pytest.mark.asyncio
async def test_sync_incoming_is_idempotent_and_queues_unmatched(monkeypatch):
    assert await bank_ingest.sync_incoming(Session(), None, None) == {
        "source_available": False, "fetched": 0, "new": 0, "matched": 0, "unmatched": 0
    }
    gateway = SimpleNamespace(
        fetch_incoming=AsyncMock(return_value=[
            {"ext_id": "known", "amount": "1"},
            {"ext_id": "bad", "amount": "oops"},
            {"ext_id": "matched", "amount": "5", "currency": "BYN", "purpose": "СЧ100"},
            {"ext_id": "unmatched", "amount": "10", "purpose": "nothing"},
            {"amount": "1"},
        ])
    )
    payment_row = payment("СЧ100", ident=20)
    monkeypatch.setattr(
        bank_ingest,
        "_match_candidate",
        AsyncMock(side_effect=[(payment_row, "matched"), (None, "счёт не найден")]),
    )
    allocation = SimpleNamespace(id=99)
    apply = AsyncMock(return_value=allocation)
    monkeypatch.setattr(bank_ingest, "apply_allocation", apply)
    session = Session(Result(["known"]))

    result = await bank_ingest.sync_incoming(session, gateway, SimpleNamespace(), since="yesterday")

    assert result == {"source_available": True, "fetched": 5, "new": 3, "matched": 1, "unmatched": 2}
    assert len(session.added) == 3
    assert apply.await_count == 1
    assert session.added[0].match_status == "unmatched"
    assert session.added[1].match_status == "matched"
    assert session.added[1].payment_id == 20
    gateway.fetch_incoming.assert_awaited_once_with("yesterday")
