from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.services import tnved


class Session:
    def __init__(self, objects=None):
        self.objects = objects or {}

    async def get(self, model, identity):
        return self.objects.get(identity)


@pytest.mark.asyncio
async def test_resolve_tnved_and_vat_versions(monkeypatch):
    row = SimpleNamespace(
        code="8507", name="Accumulators", duty_rate="5.5", vat_code="20",
        excise=None, unit="%",
    )
    vat = SimpleNamespace(rate="20")
    version = AsyncMock(side_effect=[row, vat])
    monkeypatch.setattr(tnved.scd2, "version_as_of", version)

    result = await tnved.resolve(Session(), "8507", date(2026, 9, 17))

    assert result == {
        "code": "8507", "name": "Accumulators", "duty_rate": 5.5,
        "vat_code": "20", "vat_rate": 20.0, "excise": None, "unit": "%",
        "as_of": "2026-09-17",
    }

    monkeypatch.setattr(tnved.scd2, "version_as_of", AsyncMock(return_value=None))
    assert await tnved.resolve(Session(), "missing", date(2026, 9, 17)) is None


@pytest.mark.asyncio
async def test_effective_group_fields_attributes_and_cycle_guard():
    own = SimpleNamespace(tnved_code="OWN", unit="шт", category_id=1, attributes={"brand": 7})
    assert await tnved.effective_group_field(Session(), own, "unit") == {
        "value": "шт", "source": "own", "group_code": None, "group_name": None
    }
    assert await tnved.effective_group_attr(Session(), own, "brand") == {
        "value": "7", "source": "own", "group_code": None, "group_name": None
    }

    parent = SimpleNamespace(
        tnved_code="GROUP", unit="компл", country="BY", vat_code="20",
        attributes={"brand": "GroupBrand"}, category_id=None,
        parent_id=None, is_active=True, code="P", name="Parent",
    )
    archived = SimpleNamespace(
        tnved_code="ARCHIVE", unit=None, country=None, vat_code=None,
        attributes={"brand": "Old"}, category_id=None,
        parent_id=2, is_active=False, code="A", name="Archived",
    )
    session = Session({1: archived, 2: parent})
    inherited = SimpleNamespace(tnved_code=None, unit=None, category_id=1, attributes={})
    assert await tnved.effective_group_field(session, inherited, "tnved_code") == {
        "value": "GROUP", "source": "group", "group_code": "P", "group_name": "Parent"
    }
    assert await tnved.effective_group_attr(session, inherited, "brand") == {
        "value": "GroupBrand", "source": "group", "group_code": "P", "group_name": "Parent"
    }
    assert await tnved.effective_group_field(Session(), SimpleNamespace(category_id=None, unit=None), "unit") == {
        "value": None, "source": None, "group_code": None, "group_name": None
    }
    assert tnved._attrs_dict(None) == {}
    assert tnved._attrs_dict({"a": 1}) == {"a": 1}

    cycle = {
        1: SimpleNamespace(parent_id=2, is_active=False, code="1", name="1", attributes={}),
        2: SimpleNamespace(parent_id=1, is_active=False, code="2", name="2", attributes={}),
    }
    assert (await tnved._walk_up_groups(Session(cycle), 1, lambda _cat: None))["value"] is None


@pytest.mark.asyncio
async def test_effective_code_wrapper_and_none_group_values():
    sku = SimpleNamespace(tnved_code=None, category_id=7, attributes={})
    session = Session({7: SimpleNamespace(
        tnved_code=None, parent_id=None, is_active=True, code="G", name="Group", attributes={}
    )})
    assert await tnved.effective_code_for_sku(session, sku) == {
        "code": None, "source": None, "group_code": None, "group_name": None
    }
