from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.sales import ai, kpi_facts


class Gateway:
    def __init__(self):
        self.complete = AsyncMock(return_value="answer")


class Result:
    def __init__(self, scalar=None, one=None):
        self.scalar = scalar
        self.one_value = one

    def scalar_one(self):
        return self.scalar

    def one(self):
        return self.one_value


class Session:
    def __init__(self, *results):
        self.results = list(results)

    async def execute(self, _statement):
        return self.results.pop(0)


@pytest.mark.asyncio
async def test_ai_prompts_and_deterministic_call_playbook():
    gateway = Gateway()
    deal = SimpleNamespace(number="D-1", counterparty="ACME", stage="qual", amount="100")
    inbound = SimpleNamespace(direction="in", text="Нужна цена")
    await ai.draft_reply(gateway, deal, [SimpleNamespace(direction="out", text="old"), inbound])
    await ai.draft_reply(gateway, deal, [])
    await ai.summarize(gateway, deal, "есть риск срока")
    await ai.next_step(gateway, deal, "клиент думает")
    assert gateway.complete.await_count == 4
    assert gateway.complete.call_args.kwargs["kind"] == "next_step"

    assert ai.static_call_script("unknown") == ai.STAGE_PLAYBOOK["new"]
    assert ai.static_call_script("won")["target_action"]
    assert ai.classify_objection("У конкурента дешевле")[0] == "competitor"
    assert ai.classify_objection("дорого, нужна скидка")[0] == "price"
    assert ai.classify_objection("когда будет в наличии?")[0] == "stock"
    assert ai.classify_objection("подумаем позже")[0] == "think"
    assert ai.classify_objection("есть вопрос")[0] == "other"
    await ai.call_script_hint(gateway, deal, ai.static_call_script("new"))
    await ai.objection_hint(gateway, "дорого", None)
    assert gateway.complete.await_count == 6


@pytest.mark.asyncio
async def test_operational_kpi_facts_use_calendar_bounds():
    session = Session(
        Result(scalar="1000"),
        Result(scalar=4),
        Result(scalar=2),
        Result(scalar=3),
        Result(one=(2, "500")),
    )
    facts = await kpi_facts.compute_operational_kpi_facts(session, date(2026, 9, 1), date(2026, 9, 30))
    assert facts == {
        "ship_plan": 1000.0, "payments_vat": 1000.0, "calls_all": 4.0,
        "calls_cold": 2.0, "new_deals_count": 3.0, "won_count": 2.0,
        "won_sum": 500.0, "avg_deal": 250.0, "gross_profit": 0.0,
        "invoice_payment_conv": 0.0,
    }
    start, end = kpi_facts._bounds(date(2026, 9, 1), date(2026, 9, 30))
    assert start == datetime(2026, 9, 1)
    assert end == datetime(2026, 10, 1)

    zero = await kpi_facts.compute_operational_kpi_facts(
        Session(Result(scalar=0), Result(scalar=0), Result(scalar=0), Result(scalar=0), Result(one=(0, 0))),
        date(2026, 9, 1), date(2026, 9, 1),
    )
    assert zero["avg_deal"] == 0.0
