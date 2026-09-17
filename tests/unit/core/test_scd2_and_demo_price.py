from datetime import date
from types import SimpleNamespace

import pytest

from core.services import price_cost_demo, scd2


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows

    def scalars(self):
        return self


class Session:
    def __init__(self, *results):
        self.results = list(results)
        self.added = []

    async def execute(self, _statement):
        return self.results.pop(0)

    def add(self, value):
        self.added.append(value)


class Field:
    def __eq__(self, _other):
        return self

    def __le__(self, _other):
        return self

    def __gt__(self, _other):
        return self

    def is_(self, _other):
        return self


class DummyStatement:
    def where(self, *_conditions):
        return self


class Version:
    key = Field()
    start_date = Field()
    end_date = Field()

    def __init__(self, **values):
        self.__dict__.update(values)


@pytest.mark.asyncio
async def test_scd2_queries_current_and_as_of_version_without_committing(monkeypatch):
    monkeypatch.setattr(scd2, "select", lambda _model: DummyStatement())
    monkeypatch.setattr(scd2, "or_", lambda *_conditions: Field())
    current = SimpleNamespace(id=1)
    historical = SimpleNamespace(id=2)
    assert await scd2.current_version(Session(Result([current])), Version, "key", "SKU") is current
    assert await scd2.version_as_of(
        Session(Result([historical])), Version, "key", "SKU", date(2026, 9, 17)
    ) is historical


@pytest.mark.asyncio
async def test_scd2_add_version_closes_open_row_and_rejects_overlap(monkeypatch):
    monkeypatch.setattr(scd2, "select", lambda _model: DummyStatement())
    monkeypatch.setattr(scd2, "or_", lambda *_conditions: Field())
    open_row = SimpleNamespace(start_date=date(2026, 1, 1), end_date=None)
    session = Session(Result([open_row]))
    new = await scd2.add_version(
        session, Version, "key", "SKU", date(2026, 2, 1), amount=10
    )
    assert open_row.end_date == date(2026, 2, 1)
    assert (new.key, new.start_date, new.end_date, new.amount) == (
        "SKU",
        date(2026, 2, 1),
        None,
        10,
    )
    assert session.added == [new]

    with pytest.raises(ValueError, match="должна начинаться позже"):
        await scd2.add_version(
            Session(Result([SimpleNamespace(start_date=date(2026, 2, 1), end_date=None)])),
            Version,
            "key",
            "SKU",
            date(2026, 1, 31),
        )


def test_demo_pseudo_cost_is_deterministic_and_bounded():
    first = price_cost_demo._pseudo_cost_byn("SKU-1")
    assert first == price_cost_demo._pseudo_cost_byn("SKU-1")
    assert 20 <= first <= 500.01


@pytest.mark.asyncio
async def test_demo_price_source_returns_only_known_skus_with_explicit_demo_provenance():
    source = price_cost_demo.DemoPriceCostSource()
    assert await source.get_item_price_cost(Session(), []) == {}
    result = await source.get_item_price_cost(Session(Result(["SKU-1", "SKU-2"])), ["SKU-1", "SKU-2"])
    assert set(result) == {"SKU-1", "SKU-2"}
    assert all(item.source == "demo" and item.currency == "BYN" for item in result.values())
    assert all(item.price_byn > item.cost_byn for item in result.values())
