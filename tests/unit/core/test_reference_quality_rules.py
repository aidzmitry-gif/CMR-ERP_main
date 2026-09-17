from types import SimpleNamespace

from core.services.reference_quality import (
    _broken,
    _dup_by_title,
    _issue,
    _missing,
    _norm_title,
    _result,
    _score,
)


def test_reference_quality_normalizes_titles_and_limits_issue_samples():
    assert _norm_title("  ООО   Альфа\n") == "ооо альфа"
    issue = _issue("missing", "code", list(range(10)))
    assert issue == {
        "kind": "missing",
        "field": "code",
        "count": 10,
        "sample_keys": ["0", "1", "2", "3", "4"],
    }


def test_reference_quality_missing_broken_and_duplicates_are_explicit():
    rows = [
        SimpleNamespace(code="A", unit="", category_id=1, title="Alpha"),
        SimpleNamespace(code="B", unit="шт", category_id=9, title=" alpha "),
        SimpleNamespace(code="C", unit=None, category_id=None, title="Beta"),
    ]
    missing = _missing(rows, "code", ("unit", "category_id"))
    assert {(item["field"], item["count"]) for item in missing} == {
        ("unit", 2),
        ("category_id", 1),
    }
    broken = _broken(rows, "code", "category_id", {1})
    assert broken["kind"] == "broken_ref"
    assert broken["sample_keys"] == ["B"]
    duplicate = _dup_by_title(rows)
    assert duplicate["field"] == "title"
    assert duplicate["sample_keys"] == ["A", "B"]
    assert _broken(rows, "code", "unit", {"", "шт"}) is None


def test_reference_quality_score_is_clamped_and_result_gets_human_title():
    assert _score(0, []) == 1.0
    assert _score(4, [{"kind": "missing", "count": 1}, {"kind": "duplicate", "count": 2}]) == 0.5
    assert _score(1, [{"kind": "missing", "count": 99}]) == 0.0
    result = _result("core.units", 2, [None, {"kind": "missing", "field": "code", "count": 1}])
    assert result == {
        "ref": "core.units",
        "title": "Единицы измерения",
        "total": 2,
        "issues": [{"kind": "missing", "field": "code", "count": 1}],
        "score": 0.5,
    }
