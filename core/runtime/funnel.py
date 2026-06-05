"""Переиспользуемая воронка-доска для модулей-канбанов.

Доска сделок (`/sales/board`) группирует сущности по стадиям и считает агрегаты.
Тот же паттерн нужен модулям закупок, производства, склада, HR, юр-отдела и др.,
поэтому он вынесен сюда: модуль задаёт список стадий (`STAGES`) и функцию-маппер
«сущность → :class:`FunnelCard`», а :func:`build_board` собирает доску.

Карточка :class:`FunnelCard` — универсальная: модуль заполняет только нужные поля
(номер, заголовок, сумма, приоритет, прогресс, теги…), фронт рендерит их единообразно.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence

from pydantic import BaseModel, ConfigDict, Field


class FunnelCard(BaseModel):
    """Карточка воронки (универсальная). Заполняются только нужные модулю поля."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str = ""           # номер (напр. «ЗАК-2026-0341»)
    title: str = ""          # главный заголовок (товар / компания / кандидат / курс)
    subtitle: str = ""       # подзаголовок (поставщик / описание / должность / аудитория)
    flag: str = ""           # эмодзи-флаг страны (напр. поставщика) — опц.
    amount: float | None = None  # сумма (если есть) — идёт в агрегат стадии
    priority: str = ""       # «Высокий» | «Средний» | «Низкий» (опц.)
    status_tag: str = ""     # доп. бейдж статуса (напр. «СРОЧНО», «QC OK»)
    owner: str = ""          # ответственный
    date: str = ""           # дата / дедлайн (строкой, как deal_date в sales)
    progress: int | None = None  # % выполнения (производство / обучение)
    next_step: str = ""      # следующий шаг / действие
    insight: str = ""        # AI-рекомендация по карточке (фиолетовая строка)
    score: str = ""          # доп. бейдж-рейтинг (напр. «Score 8.7»)
    state: str = ""          # статус-чип (Пройдено / В процессе / Не начат)
    action: str = ""         # подпись основной кнопки на карточке
    details: list[dict[str, str]] = Field(default_factory=list)  # key-value блок [{"k","v"}]
    tags: list[str] = Field(default_factory=list)  # доп. чипсы


class FunnelStage(BaseModel):
    """Стадия-колонка доски с агрегатами и карточками."""

    id: str
    title: str
    color: str
    count: int
    sum: float
    cards: list[FunnelCard]


class FunnelBoardOut(BaseModel):
    """Доска воронки целиком — список стадий по порядку колонок."""

    stages: list[FunnelStage]


def build_board(
    stages: Sequence[dict],
    rows: Iterable[object],
    to_card: Callable[[object], FunnelCard],
    *,
    stage_of: Callable[[object], str] = lambda r: r.stage,
) -> FunnelBoardOut:
    """Сгруппировать сущности по стадиям и посчитать агрегаты (count и сумма).

    ``stages`` — список ``{"id","title","color"}`` (порядок = порядок колонок);
    ``to_card`` превращает сущность в :class:`FunnelCard`; ``stage_of`` достаёт id
    стадии из сущности (по умолчанию атрибут ``stage``). Сумма стадии — по полю
    ``amount`` карточек (пустые игнорируются).
    """
    by_stage: dict[str, list[object]] = defaultdict(list)
    for row in rows:
        by_stage[stage_of(row)].append(row)

    result: list[FunnelStage] = []
    for s in stages:
        cards = [to_card(r) for r in by_stage.get(s["id"], [])]
        result.append(
            FunnelStage(
                id=s["id"],
                title=s["title"],
                color=s["color"],
                count=len(cards),
                sum=float(sum(c.amount or 0 for c in cards)),
                cards=cards,
            )
        )
    return FunnelBoardOut(stages=result)
