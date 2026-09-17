from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from modules.sales import routes


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return self


class Session:
    def __init__(self, *results, objects=None):
        self.results = list(results)
        self.objects = objects or {}
        self.added = []
        self.commits = 0

    async def execute(self, _statement):
        return self.results.pop(0)

    async def get(self, model, identity):
        return self.objects.get((model, identity))

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1


def test_sales_math_date_and_html_helpers():
    deal = SimpleNamespace(amount="100", probability=None, stage="qual")
    assert routes._deal_weight(deal, {"qual": 25}) == 25.0
    deal.probability = 80
    assert routes._deal_weight(deal) == 80.0
    assert routes._month_bounds("2026-02")[1].day == 28
    with pytest.raises(HTTPException, match="YYYY-MM"):
        routes._month_bounds("2026-13")
    assert routes._parse_ddmmyyyy("17.09.2026").isoformat() == "2026-09-17"
    assert routes._parse_ddmmyyyy("bad") is None

    task = SimpleNamespace(
        id=1, deal_id=2, title="Call", kind="call", assignee_id=None,
        due_at=datetime.now() - timedelta(days=1), status="open", result=None,
    )
    assert routes._task_out(task).overdue is True
    task.status = "done"
    assert routes._task_out(task).overdue is False

    assert routes._money(Decimal("1234.5")) == "1 234.50"
    assert routes._esc('<script>') == "&lt;script&gt;"
    line = routes._req_line({"name": "ACME", "unp": "123", "account": "BY", "bank": "Bank", "bik": "BIC"})
    assert "УНП 123" in line and "БИК BIC" in line
    assert routes._facsimile_sig({}) == ""
    assert routes._facsimile_stamp({}) == ""
    assert "signature" not in routes._contract_facsimile_block({})


@pytest.mark.asyncio
async def test_board_stage_price_and_counterparty_helpers():
    stage = SimpleNamespace(code="new", title="New", color="#fff", probability=10)
    assert await routes._board_stages(Session(Result([stage]))) == [
        {"id": "new", "title": "New", "color": "#fff", "probability": 10}
    ]
    assert await routes._board_stages(Session(Result([]), Result([stage])), "other") == []
    fallback = await routes._board_stages(Session(Result([]), Result([])))
    assert fallback and fallback[0]["id"] == routes.STAGES[0]["id"]

    assert (await routes._price_summary(Session(Result(["10", "8"])), "S-1")).min_price == 8.0
    assert (await routes._price_summary(Session(Result([])), "S-2")).count == 0
    item = SimpleNamespace(id=3, sku_id=5, qty="2")
    sku = SimpleNamespace(code="S-1", title="Battery", unit="шт")
    out = await routes._build_item_out(
        Session(Result(["12"]), objects={(routes.Sku, 5): sku}), item, "ACME"
    )
    assert (out.code, out.qty, out.last_price) == ("S-1", 2.0, 12.0)

    cp = SimpleNamespace(id=4, name="ACME", unp="123", is_active=True, merged_into_id=None)
    deal = SimpleNamespace(counterparty="ACME")
    assert await routes._counterparty_for_deal(Session(Result([cp])), deal) is cp
    ref = await routes._counterparty_ref(Session(Result([cp]), Result(["1c", "1c", "erp"])), deal)
    assert ref.sources == ["1c", "erp"]
    contact = SimpleNamespace(is_primary=True)
    await routes._clear_primary(Session(Result([contact])), 4)
    assert contact.is_primary is False


@pytest.mark.asyncio
async def test_stock_and_document_helpers_are_isolated():
    rows = [SimpleNamespace(sku_id=1, qty="2")]
    skus = [SimpleNamespace(id=1, code="S-1")]
    assert await routes._deal_stock_items(Session(Result(rows), Result(skus)), 5) == [
        {"sku_code": "S-1", "qty": 2.0}
    ]
    assert await routes._deal_stock_items(Session(Result([])), 5) == []

    bus = SimpleNamespace(emit=Mock())
    onec = SimpleNamespace(post_document=AsyncMock(return_value={"ref": "1C-1"}))
    core = SimpleNamespace(services=SimpleNamespace(onec=onec), event_bus=bus)
    doc = SimpleNamespace(kind="invoice", number="INV-1", amount="100", id=9, deal_id=5, status="draft", onec_ref=None, posted_at=None)
    session = Session()
    await routes._post_document_to_1c(core, session, doc, "ACME")
    assert doc.status == "posted" and doc.onec_ref == "1C-1"
    assert session.commits == 0
    assert bus.emit.call_count == 1


def test_print_form_helpers_escape_and_render_totals():
    config = SimpleNamespace(
        seller_name="Seller", seller_unp="111", seller_address="Minsk", seller_director="Boss",
        seller_phone="+375", seller_email="seller@example.com", seller_account="BY00",
        seller_bank="Bank", seller_bik="BIC",
    )
    core = SimpleNamespace(config=config)
    seller = routes._seller_requisites(core)
    assert seller["bank"] == "Bank"
    seller_with = routes._seller_with_facsimile(core, SimpleNamespace(logo_data_url="data:image/png;base64,x", stamp_data_url="stamp", signature_data_url="sig"))
    assert seller_with["logo_data_url"].startswith("data:image")
    assert "img" in routes._contract_facsimile_block(seller_with)
    assert routes._render_contract("{{buyer.name}} {{missing}}", {"buyer.name": "ACME"}, "tail") == "ACME tail"

    doc = SimpleNamespace(number="INV-1", created_at=datetime(2026, 9, 17))
    deal = SimpleNamespace(number="D-1")
    html = routes._render_invoice(
        doc,
        deal,
        seller_with,
        {"name": "ACME <bad>", "unp": "222"},
        [{"name": "Battery <x>", "qty": "2", "unit": "шт", "price": "10"}],
    )
    assert "INV-1" in html
    assert "&lt;bad&gt;" in html
    assert "24.00" in html
