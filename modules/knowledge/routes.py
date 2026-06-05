"""HTTP-API модуля Knowledge. Монтируется под префиксом ``/knowledge``."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.runtime.deps import get_session
from core.runtime.funnel import FunnelBoardOut, FunnelCard, build_board
from modules.knowledge.models import Course
from modules.knowledge.schemas import CourseCreate, CourseOut, StageUpdate
from modules.knowledge.stages import STAGES

router = APIRouter(tags=["knowledge"])


def _to_card(r: Course) -> FunnelCard:
    tags = [t for t in (r.kind, f"{r.duration} мин" if r.duration else "") if t]
    # Статус курса и кнопка-действие из прогресса (как в референсе)
    if r.progress >= 100:
        state, action = "Пройдено", "Повторить"
    elif r.progress <= 0:
        state, action = "Не начат", "Начать"
    else:
        state, action = "В процессе", "Продолжить →"
    return FunnelCard(
        id=r.id,
        code=r.number or f"КУРС-{r.id:03d}",
        title=r.title,
        subtitle=r.description,
        progress=r.progress,
        status_tag=r.audience,
        state=state,
        action=action,
        tags=tags,
    )


@router.get("/courses", response_model=list[CourseOut])
async def list_courses(session: AsyncSession = Depends(get_session)):
    """Курсы программы обучения (плоский список)."""
    return (await session.execute(select(Course).order_by(Course.id.desc()))).scalars().all()


@router.get("/board", response_model=FunnelBoardOut)
async def board(session: AsyncSession = Depends(get_session)) -> FunnelBoardOut:
    """Канбан обучения: курсы сгруппированы по разделам программы."""
    rows = (await session.execute(select(Course))).scalars().all()
    return build_board(STAGES, rows, _to_card)


@router.post("/courses", response_model=CourseOut, status_code=201)
async def create_course(payload: CourseCreate, session: AsyncSession = Depends(get_session)):
    """Создать курс. Номер генерируется автоматически, если не задан."""
    obj = Course(**payload.model_dump())
    session.add(obj)
    await session.flush()
    if not obj.number:
        obj.number = f"КУРС-{obj.id:03d}"
    await session.commit()
    await session.refresh(obj)
    return obj


@router.patch("/courses/{course_id}", response_model=CourseOut)
async def update_course(
    course_id: int, payload: StageUpdate, session: AsyncSession = Depends(get_session)
):
    """Переместить курс в другой раздел программы."""
    obj = await session.get(Course, course_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Курс не найден")
    obj.stage = payload.stage
    await session.commit()
    await session.refresh(obj)
    return obj
