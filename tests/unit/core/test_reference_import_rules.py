from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.domain.models import Counterparty
from core.services import reference_import, survivorship


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return self


class Session:
    def __init__(self, *results):
        self.results = list(results)
        self.added = []
        self.next_id = 100

    async def execute(self, _statement):
        return self.results.pop(0)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        for value in self.added:
            if isinstance(value, Counterparty) and value.id is None:
                value.id = self.next_id
                self.next_id += 1


@pytest.mark.asyncio
async def test_upsert_creates_counterparty_and_adds_alias(monkeypatch):
    monkeypatch.setattr(
        reference_import.survivorship,
        "load_rules",
        AsyncMock(return_value={"name": survivorship.Rule()}),
    )
    monkeypatch.setattr(reference_import.mdm, "match_candidates", AsyncMock(return_value=[]))
    session = Session(Result([]))

    result = await reference_import.upsert_counterparty(
        session,
        unp="111",
        name="Alpha",
        source="1c",
        external_ref="A-1",
        at="2026-09-17",
    )

    assert result.created is True
    assert result.alias_added is True
    assert result.updated_fields == ()
    assert result.counterparty.id == 100
    assert result.counterparty.provenance == {"name": {"source": "1c", "at": "2026-09-17"}}
    assert len(session.added) == 2


@pytest.mark.asyncio
async def test_upsert_matches_updates_empty_field_and_is_idempotent(monkeypatch):
    existing = Counterparty(id=7, name="", unp="222", provenance={})
    monkeypatch.setattr(reference_import.mdm, "match_candidates", AsyncMock(return_value=[existing]))
    monkeypatch.setattr(
        reference_import.survivorship,
        "load_rules",
        AsyncMock(return_value={"name": survivorship.Rule()}),
    )
    session = Session(Result([]))
    first = await reference_import.upsert_counterparty(
        session, unp="222", name="Beta", source="bitrix", external_ref="B-1"
    )
    assert first.created is False
    assert first.alias_added is True
    assert first.updated_fields == ("name",)
    assert existing.name == "Beta"

    monkeypatch.setattr(reference_import.mdm, "add_source_alias", AsyncMock())
    second = await reference_import.upsert_counterparty(
        session, unp="222", name="Beta", source="bitrix", external_ref=None,
        rules={"name": survivorship.Rule()},
    )
    assert second.created is False
    assert second.alias_added is False

    with pytest.raises(ValueError, match="УНП"):
        await reference_import.upsert_counterparty(session, unp="", name="missing")


@pytest.mark.asyncio
async def test_batch_import_counts_skips_and_delegates(monkeypatch):
    monkeypatch.setattr(
        reference_import.survivorship,
        "load_rules",
        AsyncMock(return_value={"name": survivorship.Rule()}),
    )
    results = iter(
        [
            reference_import.UpsertResult(SimpleNamespace(), True, True),
            reference_import.UpsertResult(SimpleNamespace(), False, False),
        ]
    )
    upsert = AsyncMock(side_effect=lambda *args, **kwargs: next(results))
    monkeypatch.setattr(reference_import, "upsert_counterparty", upsert)

    result = await reference_import.import_counterparties(
        Session(),
        [
            {"unp": "111", "name": "A", "id": "A-1"},
            {"unp": "", "name": "group"},
            {"unp": "222", "name": "B", "external_ref": "B-1"},
        ],
        source="erp",
    )

    assert result == {
        "total": 3,
        "created": 1,
        "matched": 1,
        "aliases_added": 1,
        "skipped_no_unp": 1,
    }
    assert upsert.await_count == 2
