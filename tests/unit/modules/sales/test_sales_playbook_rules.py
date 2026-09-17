import pytest

from modules.sales._money_words import _int_words, _plural, _triplet
from modules.sales.ai import classify_objection, static_call_script
from modules.sales.stages import canonical_stages


@pytest.mark.parametrize("stage", ["new", "qual", "won", "lost", None, "unknown"])
def test_static_call_script_returns_known_playbook_or_new_fallback(stage):
    script = static_call_script(stage)
    assert {"goal", "target_action", "talking_points", "questions"} <= set(script)
    if stage in (None, "unknown"):
        assert script["goal"] == static_call_script("new")["goal"]


@pytest.mark.parametrize(
    ("text", "category"),
    [("У конкурента дешевле", "competitor"), ("Слишком дорого, нужна скидка", "price"), ("Когда будет в наличии?", "stock"), ("Я подумаю позже", "think"), ("Расскажите подробнее", "other")],
)
def test_objection_classifier_preserves_priority_and_returns_actionable_reply(text, category):
    actual, reply = classify_objection(text)
    assert actual == category
    assert reply


def test_canonical_stages_contains_all_funnels_and_invariants():
    rows = canonical_stages()
    assert len(rows) == 21
    assert {row["funnel"] for row in rows} == {"new_clients", "repeat_clients", "tenders"}
    for funnel in {row["funnel"] for row in rows}:
        part = [row for row in rows if row["funnel"] == funnel]
        assert [row["sort_order"] for row in part] == list(range(len(part)))
        assert all(row["is_active"] is True for row in part)
        assert all(0 <= row["probability"] <= 100 for row in part)
    assert next(row for row in rows if row["code"] == "won")["kind"] == "won"
    assert next(row for row in rows if row["code"] == "lost")["probability"] == 0


def test_money_words_helpers_cover_plural_teens_female_triplets_and_large_units():
    forms = ("one", "few", "many")
    assert [_plural(n, forms) for n in (1, 2, 5, 11, 22)] == ["one", "few", "many", "many", "few"]
    assert _triplet(21, False) == "двадцать один"
    assert _triplet(21, True) == "двадцать одна"
    assert _triplet(15, False) == "пятнадцать"
    assert _int_words(0) == "ноль"
    assert "миллиард" in _int_words(1_000_000_001)
    assert "миллион" in _int_words(2_000_000)
    assert "тысяча" in _int_words(1_000)
