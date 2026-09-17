from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.db.repository import Repository


class Result:
    def __init__(self, rows):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self.rows


class Session:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.added = []
        self.flushed = 0

    async def get(self, _model, identity):
        return next((row for row in self.rows if row.id == identity), None)

    async def execute(self, _statement):
        return Result(self.rows)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed += 1


class Entity:
    id = "id"


@pytest.mark.asyncio
async def test_repository_crud_delegates_without_committing(monkeypatch):
    from core.db import repository as repository_module

    class Query:
        def order_by(self, _column):
            return self

    monkeypatch.setattr(repository_module, "select", lambda _model: Query())
    first = SimpleNamespace(id=1, name="one")
    session = Session([first])
    repo = Repository(session)
    repo.model = Entity

    assert await repo.get(1) is first
    assert await repo.get(99) is None
    assert list(await repo.list()) == [first]

    added = SimpleNamespace(id=2, name="two")
    assert await repo.add(added) is added
    assert session.added == [added]
    assert session.flushed == 1

    assert await repo.update(added, {"name": "updated", "extra": 3}) is added
    assert (added.name, added.extra, session.flushed) == ("updated", 3, 2)
