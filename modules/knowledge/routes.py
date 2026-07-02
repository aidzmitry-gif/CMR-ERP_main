"""HTTP-API модуля Knowledge. Монтируется под префиксом ``/knowledge``."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.runtime.deps import get_session
from core.runtime.funnel import FunnelBoardOut, FunnelCard, build_board
from modules.knowledge.models import Course, CourseEnrollment
from modules.knowledge.schemas import (
    CourseCreate,
    CourseEnrollmentCreate,
    CourseEnrollmentOut,
    CourseEnrollmentPatch,
    CourseOut,
    StageUpdate,
)
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


# --------------------------------------------------------------------------- #
#  Учёт прохождения курсов (назначения сотрудникам)
# --------------------------------------------------------------------------- #

@router.get("/enrollments", response_model=list[CourseEnrollmentOut])
async def list_enrollments(
    employee_name: str | None = None,
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Реестр назначений курсов с фильтрами по сотруднику и статусу."""
    q = select(CourseEnrollment).order_by(CourseEnrollment.id.desc())
    if employee_name:
        q = q.where(CourseEnrollment.employee_name == employee_name)
    if status:
        q = q.where(CourseEnrollment.status == status)
    return (await session.execute(q)).scalars().all()


@router.post("/enrollments", response_model=CourseEnrollmentOut, status_code=201)
async def create_enrollment(
    payload: CourseEnrollmentCreate,
    session: AsyncSession = Depends(get_session),
):
    """Назначить курс сотруднику."""
    obj = CourseEnrollment(**payload.model_dump())
    session.add(obj)
    await session.flush()
    await session.commit()
    await session.refresh(obj)
    return obj


@router.get("/enrollments/{enrollment_id}", response_model=CourseEnrollmentOut)
async def get_enrollment(enrollment_id: int, session: AsyncSession = Depends(get_session)):
    obj = await session.get(CourseEnrollment, enrollment_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Назначение не найдено")
    return obj


@router.patch("/enrollments/{enrollment_id}", response_model=CourseEnrollmentOut)
async def patch_enrollment(
    enrollment_id: int,
    payload: CourseEnrollmentPatch,
    session: AsyncSession = Depends(get_session),
):
    """Обновить статус/прогресс/дату завершения. При status=completed — дата и прогресс выставляются автоматически."""
    from datetime import date

    obj = await session.get(CourseEnrollment, enrollment_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Назначение не найдено")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(obj, field, value)
    if obj.status == "completed":
        if not obj.completed_at:
            obj.completed_at = date.today().isoformat()
        obj.progress = 100
    await session.commit()
    await session.refresh(obj)
    return obj
