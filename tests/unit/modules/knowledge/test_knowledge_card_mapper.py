from modules.knowledge.models import Course
from modules.knowledge.routes import _to_card


def test_course_card_maps_tags_and_not_started_state():
    card = _to_card(
        Course(
            id=1,
            title="Онбординг",
            description="Вводный курс",
            kind="Видео",
            duration=45,
            progress=0,
            audience="Все сотрудники",
        )
    )
    assert card.code == "КУРС-001"
    assert card.state == "Не начат"
    assert card.action == "Начать"
    assert card.tags == ["Видео", "45 мин"]
    assert card.status_tag == "Все сотрудники"


def test_course_card_has_in_progress_and_completed_boundaries():
    in_progress = _to_card(
        Course(
            id=2,
            number="K-2",
            title="",
            description="",
            kind="",
            progress=50,
            duration=0,
            audience="",
        )
    )
    assert in_progress.state == "В процессе"
    assert in_progress.action == "Продолжить →"
    assert in_progress.tags == []

    for progress in (100, 125):
        completed = _to_card(
            Course(
                id=3,
                title="",
                description="",
                kind="",
                progress=progress,
                duration=0,
                audience="",
            )
        )
        assert completed.state == "Пройдено"
        assert completed.action == "Повторить"
