from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.sales import calls


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return self


class Session:
    def __init__(self, *results, objects=None):
        self.results = list(results)
        self.objects = objects or {}

    async def execute(self, _statement):
        return self.results.pop(0)

    async def get(self, model, identity):
        return self.objects.get((model, identity))


@pytest.mark.asyncio
async def test_owner_from_deals_prefers_active_then_falls_back_to_closed():
    active = SimpleNamespace(owner="active-owner")
    assert await calls._owner_from_deals(Session(Result([active])), "ACME") == "active-owner"

    closed = SimpleNamespace(owner="closed-owner")
    assert await calls._owner_from_deals(Session(Result([]), Result([closed])), "ACME") == "closed-owner"
    assert await calls._owner_from_deals(Session(Result([]), Result([])), "ACME") == ""


@pytest.mark.asyncio
async def test_resolve_owner_matches_contact_and_deal_owner():
    from core.domain.models import Counterparty

    contact = SimpleNamespace(id=4, counterparty_id=9)
    counterparty = SimpleNamespace(name="ACME")
    active_deal = SimpleNamespace(owner="Ivan")
    session = Session(Result([contact]), Result([active_deal]), objects={(Counterparty, 9): counterparty})

    assert await calls.resolve_owner(session, "+375 (29) 123-45-67") == {
        "owner": "Ivan",
        "owner_id": None,
        "counterparty_id": 9,
        "contact_id": 4,
    }


@pytest.mark.asyncio
async def test_resolve_owner_returns_empty_for_missing_phone_or_unowned_contact():
    assert await calls.resolve_owner(Session(), None) == {
        "owner": "",
        "owner_id": None,
        "counterparty_id": None,
        "contact_id": None,
    }
    contact = SimpleNamespace(id=4, counterparty_id=None)
    assert await calls.resolve_owner(Session(Result([contact])), "123456789") == {
        "owner": "",
        "owner_id": None,
        "counterparty_id": None,
        "contact_id": 4,
    }


@pytest.mark.asyncio
async def test_resolve_owner_handles_missing_contact_and_counterparty_without_fallback():
    empty = await calls.resolve_owner(Session(Result([])), "+375291234567")
    assert empty == {
        "owner": "",
        "owner_id": None,
        "counterparty_id": None,
        "contact_id": None,
    }

    from core.domain.models import Counterparty

    contact = SimpleNamespace(id=8, counterparty_id=10)
    session = Session(Result([contact]), objects={(Counterparty, 10): None})
    result = await calls.resolve_owner(session, "+375291234567")
    assert result == {
        "owner": "",
        "owner_id": None,
        "counterparty_id": 10,
        "contact_id": 8,
    }
