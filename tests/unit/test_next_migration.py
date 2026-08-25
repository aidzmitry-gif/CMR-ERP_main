from scripts import next_migration


def test_head_prefers_real_head_over_stale_reservation():
    assert next_migration._head(
        {"0090", "0105", "0106"},
        {"0090", "0105"},
        [(90, "0090")],
    ) == "0106"


def test_head_uses_newer_reservation_after_real_head():
    assert next_migration._head(
        {"0105", "0106"},
        {"0105"},
        [(107, "0106")],
    ) == "0107"


def test_head_uses_nonnumeric_alembic_tip_when_no_numeric_tip_exists():
    assert next_migration._head({"base", "merge_tip"}, {"base"}, []) == "merge_tip"
