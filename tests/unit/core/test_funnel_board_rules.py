from types import SimpleNamespace

from core.runtime.funnel import FunnelCard, build_board


def test_build_board_preserves_stage_order_and_aggregates_amounts():
    rows = [
        SimpleNamespace(stage="new", id=1, amount=10),
        SimpleNamespace(stage="new", id=2, amount=None),
        SimpleNamespace(stage="won", id=3, amount=2.5),
        SimpleNamespace(stage="missing", id=4, amount=999),
    ]

    board = build_board(
        [
            {"id": "new", "title": "Новые", "color": "blue"},
            {"id": "work", "title": "В работе", "color": "amber"},
            {"id": "won", "title": "Выиграны", "color": "green"},
        ],
        rows,
        lambda row: FunnelCard(id=row.id, amount=row.amount),
    )

    assert [stage.id for stage in board.stages] == ["new", "work", "won"]
    assert board.stages[0].count == 2
    assert board.stages[0].sum == 10.0
    assert board.stages[1].count == 0
    assert board.stages[1].cards == []
    assert board.stages[2].count == 1
    assert board.stages[2].sum == 2.5
    assert [card.id for card in board.stages[0].cards] == [1, 2]


def test_build_board_accepts_custom_stage_selector_and_ignores_unknown_stage():
    rows = [SimpleNamespace(bucket="a", id=1), SimpleNamespace(bucket="other", id=2)]
    board = build_board(
        [{"id": "a", "title": "A", "color": "x"}],
        rows,
        lambda row: FunnelCard(id=row.id),
        stage_of=lambda row: row.bucket,
    )
    assert board.stages[0].count == 1
    assert board.stages[0].cards[0].id == 1
