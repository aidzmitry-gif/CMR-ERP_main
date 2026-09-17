from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from core.domain.models import Contact, Counterparty, CounterpartyAlias, SurvivorshipRule
from core.services import mdm


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
    def __init__(self, *results, objects=None, dialect="sqlite"):
        self.results = list(results)
        self.objects = objects or {}
        self.added = []
        self.deleted = []
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect))

    async def execute(self, _statement):
        return self.results.pop(0)

    async def get(self, model, identity):
        return self.objects.get((model, identity))

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

    async def delete(self, value):
        self.deleted.append(value)


class EventBus:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


def test_mdm_normalizers_and_survivorship_helpers():
    assert mdm._normalize_name(' ООО «Альфа»,  Ltd.  ') == "альфа"
    assert mdm._phone_tail("+375 (29) 123-45-67") == "291234567"
    assert mdm._phone_tail("123") == ""
    assert mdm._entity_ref(7) == "counterparty:7"

    survivor = SimpleNamespace(name="", unp="123")
    duplicate = SimpleNamespace(name="ООО Альфа", unp="")
    mdm._apply_survivorship(survivor, duplicate)
    assert survivor.name == "ООО Альфа"
    assert survivor.unp == "123"


@pytest.mark.asyncio
async def test_duplicate_clusters_and_import_preview_are_read_only():
    rows = [SimpleNamespace(id=1, name="A"), SimpleNamespace(id=2, name="B")]
    session = Session(Result(["123"]), Result(rows))
    clusters = await mdm.duplicate_clusters(session)
    assert clusters == [{"unp": "123", "members": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]}]
    assert session.added == []

    preview_session = Session(Result([("123",), ("999",)]))
    onec = SimpleNamespace(
        fetch_counterparties=__import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(
            return_value=[{"unp": "123"}, {"УНП": "555"}, {}, "invalid"]
        )
    )
    preview = await mdm.import_preview(preview_session, onec)
    assert preview == {"total": 4, "would_create": 1, "would_match_by_unp": 1, "without_unp": 2}


@pytest.mark.asyncio
async def test_contact_lookup_and_get_or_create():
    contact = SimpleNamespace(full_name="", phone=None, email=None)
    session = Session(Result([contact]))
    found = await mdm.find_contact(session, phone="+375291234567", email=" USER@EXAMPLE.COM ")
    assert found is contact

    no_query = Session()
    assert await mdm.find_contact(no_query) is None

    existing_session = Session(Result([contact]))
    existing, created = await mdm.link_contact(
        existing_session,
        4,
        full_name="Alice",
        phone="+375291234567",
        email="a@example.com",
    )
    assert existing is contact
    assert created is False
    assert (contact.full_name, contact.phone, contact.email) == (
        "Alice",
        "+375291234567",
        "a@example.com",
    )

    new_session = Session(Result([]))
    new_contact, created = await mdm.link_contact(
        new_session, 4, full_name="Bob", phone="+375291111111", is_primary=True
    )
    assert isinstance(new_contact, Contact)
    assert (new_contact.counterparty_id, new_contact.full_name, new_contact.is_primary) == (4, "Bob", True)
    assert created is True
    assert new_session.added == [new_contact]


@pytest.mark.asyncio
async def test_match_and_fuzzy_candidates_cover_sqlite_and_postgres_paths():
    empty = Session()
    assert await mdm.match_candidates(empty, unp=None) == []

    candidates = [SimpleNamespace(id=1, name="Alpha", unp="1")]
    session = Session(Result(candidates))
    assert await mdm.match_candidates(session, unp="1", exclude_id=9) == candidates

    sqlite = Session(
        Result([(1, "ООО Альфа"), (2, "Совсем другое")]),
        dialect="sqlite",
    )
    fuzzy = await mdm.fuzzy_candidates(sqlite, name='"Альфа"', threshold=0.5, limit=1)
    assert len(fuzzy) == 1
    assert fuzzy[0]["id"] == 1
    assert fuzzy[0]["score"] >= 0.5
    assert await mdm.fuzzy_candidates(Session(Result([])), name="   ") == []

    postgres = Session(
        Result([SimpleNamespace(id=3, name="Alpha", score="0.91")]),
        dialect="postgresql",
    )
    assert await mdm.fuzzy_candidates(postgres, name="Alpha", exclude_id=8) == [
        {"id": 3, "name": "Alpha", "score": 0.91}
    ]


@pytest.mark.asyncio
async def test_merge_unmerge_and_aliases_emit_auditable_events():
    survivor = Counterparty(id=1, name="", unp="111", is_active=True, merged_into_id=None, provenance={})
    duplicate = Counterparty(id=2, name="Duplicate", unp="222", is_active=True, merged_into_id=None, provenance={})
    session = Session(objects={(Counterparty, 1): survivor, (Counterparty, 2): duplicate})
    bus = EventBus()

    result = await mdm.merge(session, bus, 1, 2, by="admin")
    assert result is survivor
    assert survivor.name == "Duplicate"
    assert duplicate.is_active is False
    assert duplicate.merged_into_id == 1
    assert isinstance(session.added[0], CounterpartyAlias)
    assert bus.calls[0][1] == "counterparty.merged"

    alias = CounterpartyAlias(counterparty_id=1, source="merge", external_ref="2")
    session = Session(Result([alias]), objects={(Counterparty, 2): duplicate})
    result = await mdm.unmerge(session, bus, 2, by="admin")
    assert result is duplicate
    assert duplicate.is_active is True
    assert duplicate.merged_into_id is None
    assert session.deleted == [alias]
    assert bus.calls[-1][1] == "counterparty.unmerged"

    with pytest.raises(ValueError, match="саму с собой"):
        await mdm.merge(session, bus, 2, 2)
    with pytest.raises(ValueError, match="не является"):
        await mdm.unmerge(session, bus, 2)


@pytest.mark.asyncio
async def test_alias_listing_card_and_survivorship_rules():
    created_alias = await mdm.add_source_alias(Session(), 4, "1c", "EXT-4")
    assert (created_alias.counterparty_id, created_alias.source, created_alias.external_ref) == (4, "1c", "EXT-4")

    alias = SimpleNamespace(source="1c", external_ref="EXT-4", created_at=datetime(2026, 9, 17))
    alias_session = Session(Result([alias]))
    assert await mdm.aliases(alias_session, 4) == [alias]

    cp = SimpleNamespace(
        id=4,
        name="Alpha",
        unp="123",
        is_active=True,
        merged_into_id=None,
        provenance={"name": {"source": "erp"}},
    )
    merged = SimpleNamespace(id=5, name="Old", unp="123")
    contact = SimpleNamespace(id=8, full_name="Alice", phone="123", email="a@x", is_primary=True)
    audit = SimpleNamespace(id=9, ts=datetime(2026, 9, 17), actor="admin", action="merge", detail={"ok": True})
    card_session = Session(
        Result([alias]),
        Result([merged]),
        Result([contact]),
        Result([audit]),
        objects={(Counterparty, 4): cp},
    )
    card = await mdm.counterparty_card(card_session, 4)
    assert card["provenance"]["name"]["source"] == "erp"
    assert card["aliases"][0]["external_ref"] == "EXT-4"
    assert card["merged_duplicates"] == [{"id": 5, "name": "Old", "unp": "123"}]
    assert card["contacts"][0]["full_name"] == "Alice"
    assert card["audit"][0]["action"] == "merge"
    assert await mdm.counterparty_card(Session(objects={}), 99) is None

    rule = SurvivorshipRule(id=1, entity_type="counterparty", field="name", strategy="source_priority", source_priority=["erp"])
    rules = await mdm.survivorship_rules(Session(Result([rule])))
    assert rules == [{"id": 1, "entity_type": "counterparty", "field": "name", "strategy": "source_priority", "source_priority": ["erp"]}]
    assert await mdm.survivorship_rules(Session(Result([])), "sku") == []
