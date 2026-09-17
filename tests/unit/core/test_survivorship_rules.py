from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.services import survivorship
from core.services.survivorship import FieldValue, Rule


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self.rows


class Session:
    async def execute(self, _statement):
        return Result([
            SimpleNamespace(field="name", strategy="source_priority", source_priority=["erp", "1c"]),
            SimpleNamespace(field="empty", strategy="non_empty_wins", source_priority=None),
        ])


def test_decide_covers_all_survivorship_strategies():
    incoming = FieldValue("incoming", "1c", "2026-09-17")
    assert survivorship.decide(None, incoming, Rule()).value == "incoming"
    assert survivorship.decide(FieldValue("", "erp"), incoming, Rule()).value == "incoming"
    assert survivorship.decide(FieldValue("old", "manual"), incoming, Rule()).value == "old"
    assert survivorship.decide(FieldValue("old", "manual"), FieldValue("new", "manual"), Rule("manual_only")).value == "new"
    assert survivorship.decide(FieldValue("1c", "1c"), FieldValue("erp", "erp"), Rule("source_priority")).value == "erp"
    assert survivorship.decide(FieldValue("erp", "erp"), incoming, Rule("source_priority")).value == "erp"
    assert survivorship.decide(FieldValue("old", "1c", "2026-09-01"), incoming, Rule("most_recent")).value == "incoming"
    assert survivorship.decide(FieldValue("old", "1c"), FieldValue("new", "1c"), Rule("most_recent")).value == "old"
    assert survivorship.decide(FieldValue("old", "1c", "2026-09-20"), FieldValue("", "1c", "2026-09-21"), Rule("most_recent")).value == "old"

    assert survivorship.is_empty(None) is True
    assert survivorship.is_empty("  ") is True
    assert survivorship.is_empty(0) is False
    assert Rule(strategy="source_priority", source_priority=("erp",)).priority() == ["erp"]


@pytest.mark.asyncio
async def test_load_rules_and_default_rule_lookup():
    rules = await survivorship.load_rules(Session(), "counterparty")
    assert rules["name"] == Rule(strategy="source_priority", source_priority=("erp", "1c"))
    assert rules["empty"] == Rule(strategy="non_empty_wins")
    assert survivorship.rule_for(rules, "missing") == Rule()
