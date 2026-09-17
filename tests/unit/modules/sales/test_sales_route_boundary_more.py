from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from modules.sales import routes
from modules.sales.schemas import (
    BrandingIn,
    ContactCreate,
    ContractPrepareIn,
    DealItemCreate,
    DocumentCreate,
    MessageCreate,
    PriceQuoteCreate,
)


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
        self.deleted = []
        self.commits = 0

    async def execute(self, _statement):
        return self.results.pop(0)

    async def get(self, model, identity):
        return self.objects.get((model, identity))

    def add(self, value):
        if isinstance(value, routes.DealItem) and value.id is None:
            value.id = 301
        elif isinstance(value, routes.Contact) and value.id is None:
            value.id = 302
        elif isinstance(value, routes.Message) and value.id is None:
            value.id = 303
            value.created_at = datetime(2026, 9, 17, 12, 0)
        self.added.append(value)

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1

    async def delete(self, value):
        self.deleted.append(value)


class EventBus:
    def __init__(self):
        self.events = []

    def emit(self, session, event_type, payload):
        self.events.append((event_type, payload))


def _deal() -> SimpleNamespace:
    return SimpleNamespace(id=11, number="D-11", counterparty="ACME", amount=Decimal("100"))


@pytest.mark.asyncio
async def test_add_deal_item_validates_dependencies_and_emits_change_event():
    core = SimpleNamespace(event_bus=EventBus())
    payload = DealItemCreate(sku_id=5, qty=2.5)
    with pytest.raises(HTTPException, match="Сделка не найдена"):
        await routes.add_deal_item(11, payload, core, Session())

    deal = _deal()
    with pytest.raises(HTTPException, match="Номенклатура не найдена"):
        await routes.add_deal_item(11, payload, core, Session(objects={(routes.Deal, 11): deal}))

    sku = SimpleNamespace(id=5, code="SKU-5", title="Battery", unit="шт")
    session = Session(Result([Decimal("12.50")]), objects={(routes.Deal, 11): deal, (routes.Sku, 5): sku})
    out = await routes.add_deal_item(11, payload, core, session)
    assert out.model_dump() == {
        "id": 301,
        "sku_id": 5,
        "code": "SKU-5",
        "title": "Battery",
        "unit": "шт",
        "qty": 2.5,
        "last_price": 12.5,
        "min_price": 12.5,
    }
    assert core.event_bus.events == [
        ("sales.item.changed", {"deal_id": 11, "action": "added", "entity_ref": "deal:11"})
    ]
    assert session.commits == 1


@pytest.mark.asyncio
async def test_contacts_make_primary_and_keep_missing_deal_honest_empty():
    assert await routes.list_contacts(11, Session()) == []

    deal = _deal()
    counterparty = SimpleNamespace(id=7, name="ACME")
    old_primary = SimpleNamespace(id=8, is_primary=True)
    session = Session(
        Result([counterparty]),
        Result([old_primary]),
        objects={(routes.Deal, 11): deal},
    )
    contact = await routes.add_contact(
        11, ContactCreate(full_name="Иван", phone="+375", is_primary=True), session
    )
    assert (contact.counterparty_id, contact.full_name, contact.is_primary) == (7, "Иван", True)
    assert old_primary.is_primary is False and session.commits == 1

    another = SimpleNamespace(id=9, counterparty_id=7, is_primary=False)
    primary_session = Session(Result([contact]), objects={(routes.Contact, 9): another})
    selected = await routes.set_primary_contact(9, primary_session)
    assert selected.is_primary is True and contact.is_primary is False
    with pytest.raises(HTTPException, match="Контакт не найден"):
        await routes.set_primary_contact(404, Session())


@pytest.mark.asyncio
async def test_messages_record_events_and_mark_only_unread_rows():
    core = SimpleNamespace(event_bus=EventBus())
    deal = _deal()
    session = Session(objects={(routes.Deal, 11): deal})
    message = await routes.create_message(
        11,
        MessageCreate(channel="telegram", direction="out", author="Manager", text="Здравствуйте"),
        core,
        session,
    )
    assert (message.id, message.channel, message.direction, message.author) == (303, "telegram", "out", "Manager")
    assert core.event_bus.events == [
        (
            "sales.message.sent",
            {"message_id": 303, "deal_id": 11, "channel": "telegram", "direction": "out", "entity_ref": "deal:11"},
        )
    ]

    unread = SimpleNamespace(read_at=None)
    marked = await routes.mark_messages_read(11, Session(Result([unread]), objects={(routes.Deal, 11): deal}))
    assert marked == {"ok": True, "read": 1} and isinstance(unread.read_at, datetime)
    with pytest.raises(HTTPException, match="Сделка не найдена"):
        await routes.mark_messages_read(404, Session())


@pytest.mark.asyncio
async def test_branding_and_price_handlers_return_observable_contracts():
    assert (await routes.get_branding(Session())).model_dump() == {
        "logo_data_url": None,
        "stamp_data_url": None,
        "signature_data_url": None,
    }

    branding_session = Session()
    branding = await routes.put_branding(
        BrandingIn(logo_data_url="data:image/png;base64,ok"), branding_session
    )
    assert branding.model_dump()["logo_data_url"] == "data:image/png;base64,ok"
    assert branding_session.added[0].id == 1 and branding_session.commits == 1
    with pytest.raises(HTTPException, match="data-URI"):
        await routes.put_branding(BrandingIn(stamp_data_url="not-an-image"), Session())

    price = await routes.price_info("SKU-5", "ACME", Session(Result(["19", "15"])))
    assert price.model_dump() == {"sku_code": "SKU-5", "last_price": 15.0, "min_price": 15.0, "count": 2}
    core = SimpleNamespace(event_bus=EventBus())
    quote_session = Session()
    assert await routes.create_price_quote(PriceQuoteCreate(sku_code="SKU-5", counterparty="ACME", price=19.5), core, quote_session) == {"ok": True}
    assert quote_session.added[0].price == Decimal("19.5")
    assert core.event_bus.events[0][0] == "sales.price.quoted"


@pytest.mark.asyncio
async def test_document_and_contract_preflight_fail_closed_before_external_work():
    core_without_onec = SimpleNamespace(services=SimpleNamespace(onec=None))
    with pytest.raises(HTTPException, match="Сделка не найдена"):
        await routes.create_document(11, DocumentCreate(), core_without_onec, Session())

    with pytest.raises(HTTPException, match="Интеграция 1С не подключена"):
        await routes.create_document(
            11, DocumentCreate(), core_without_onec, Session(objects={(routes.Deal, 11): _deal()})
        )

    core = SimpleNamespace(services=SimpleNamespace(registry=None))
    with pytest.raises(HTTPException, match="Шаблон договора не найден"):
        await routes.prepare_contract(
            11,
            ContractPrepareIn(template_code="missing"),
            core,
            Session(Result([]), objects={(routes.Deal, 11): _deal()}),
        )
