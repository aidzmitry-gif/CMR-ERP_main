from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.services import reference_quality


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return self.rows

    def scalars(self):
        return self


class Session:
    def __init__(self, *results):
        self.results = list(results)

    async def execute(self, _statement):
        return self.results.pop(0)


def test_quality_primitives_calculate_issues_and_score():
    assert reference_quality._norm_title("  Alpha   LTD ") == "alpha ltd"
    issue = reference_quality._issue("missing", "unit", [1, 2, 3, 4, 5, 6])
    assert issue == {"kind": "missing", "field": "unit", "count": 6, "sample_keys": ["1", "2", "3", "4", "5"]}
    assert reference_quality._score(0, []) == 1.0
    assert reference_quality._score(2, [issue]) == 0.0
    assert reference_quality._missing(
        [SimpleNamespace(code="a", unit="", category_id=1), SimpleNamespace(code="b", unit="шт", category_id=None)],
        "code", ("unit", "category_id"),
    )
    assert reference_quality._broken(
        [SimpleNamespace(code="a", ref="missing")], "code", "ref", {"ok"}
    )["sample_keys"] == ["a"]
    assert reference_quality._dup_by_title([
        SimpleNamespace(code="A", title=" Alpha "), SimpleNamespace(code="B", title="alpha")
    ])["count"] == 2
    assert reference_quality._result("unknown", 0, [None, issue])["title"] == "unknown"


@pytest.mark.asyncio
async def test_audit_skus_reports_missing_broken_and_margin_blind(monkeypatch):
    rows = [
        SimpleNamespace(code="S-1", unit="", category_id=99, tnved_code="BAD", weight_kg=None, volume_m3=None),
        SimpleNamespace(code="S-2", unit="шт", category_id=10, tnved_code="8507", weight_kg=1, volume_m3=0),
    ]
    monkeypatch.setattr(
        reference_quality.tnved,
        "effective_code_for_sku",
        AsyncMock(side_effect=[{"code": None}, {"code": "8507"}]),
    )
    session = Session(Result(rows), Result([("8507",)]), Result([(10,)]))
    result = await reference_quality.audit_reference(session, "core.skus")
    kinds = {(i["kind"], i["field"]) for i in result["issues"]}
    assert ("missing", "unit") in kinds
    assert ("broken_ref", "tnved_code") in kinds
    assert ("broken_ref", "category_id") in kinds
    assert ("margin_blind", "landed_cost") in kinds
    assert result["total"] == 2


@pytest.mark.asyncio
async def test_audit_categories_counterparties_simple_and_hierarchical(monkeypatch):
    groups = [
        SimpleNamespace(
            id=1, code="G1", tnved_code=None, vat_code="BAD", unit="шт", country="BY",
            parent_id=None, is_active=True, title="Group 1",
        ),
        SimpleNamespace(
            id=2, code="G2", tnved_code="8507", vat_code="20", unit="BAD", country="BAD",
            parent_id=99, is_active=True, title="Group 1",
        ),
    ]
    session = Session(
        Result(groups), Result([("20",)]), Result([("8507",)]), Result([("шт",)]), Result([("BY",)])
    )
    categories = await reference_quality.audit_reference(session, "core.nomenclature_groups")
    kinds = {(i["kind"], i["field"]) for i in categories["issues"]}
    assert ("missing", "tnved_code") in kinds
    assert ("broken_ref", "vat_code") in kinds
    assert ("orphan", "parent_id") in kinds

    cps = [
        SimpleNamespace(id=1, unp=None, is_active=True, merged_into_id=None),
        SimpleNamespace(id=2, unp="111", is_active=True, merged_into_id=None),
        SimpleNamespace(id=3, unp="111", is_active=False, merged_into_id=2),
    ]
    monkeypatch.setattr(reference_quality.mdm, "duplicate_clusters", AsyncMock(return_value=[{"unp": "111"}]))
    cp_result = await reference_quality.audit_reference(Session(Result(cps)), "core.counterparties")
    assert cp_result["total"] == 2
    assert {(i["kind"], i["field"]) for i in cp_result["issues"]} == {
        ("missing", "unp"), ("duplicate", "unp")
    }

    simple = await reference_quality.audit_reference(
        Session(Result([SimpleNamespace(code="A", title="x"), SimpleNamespace(code="B", title="X")])),
        "core.units",
    )
    assert simple["issues"][0]["kind"] == "duplicate"
    hierarchical = await reference_quality.audit_reference(
        Session(Result([
            SimpleNamespace(id=1, code="10", title="Assets", parent_id=None, is_active=True),
            SimpleNamespace(id=2, code="20", title="assets", parent_id=99, is_active=True),
        ])),
        "core.accounts",
    )
    assert {i["kind"] for i in hierarchical["issues"]} == {"duplicate", "orphan"}
    assert await reference_quality.audit_reference(Session(), "core.unknown") is None
