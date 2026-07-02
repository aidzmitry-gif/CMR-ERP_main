"""Survivorship — какое значение поля «побеждает» при конфликте источников (M2).

Правило слияния задаётся **как данные** (таблица ``survivorship_rule``), а не зашито в код.
Для каждого поля — стратегия:

- ``source_priority`` — берётся значение из самого приоритетного доступного источника
  (список ``source_priority``, слева направо). Реквизиты: ЕГР → ERP → 1С.
- ``manual_only`` — меняется только человеком в ERP; никакой синк не перезаписывает.
- ``most_recent`` — выигрывает самое свежее по дате, независимо от источника.
- ``non_empty_wins`` — дефолт: непустое замещает пустое; при конфликте двух непустых эталон
  сохраняется (так же, как делал хардкод ``_apply_survivorship`` в ``mdm`` до M2).

Это **чистая логика** (без сессии/I/O): ``decide`` решает по одному полю, ``load_rules``
читает правила из БД. Применяют движок ``reference_import`` (импорт) и ``mdm`` (merge).
Спорные случаи — в человека-в-контуре (approval), здесь не авто-решаются (концепция §7.2).
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import SurvivorshipRule

#: дефолтный приоритет источников (по убыванию доверия) — конституция данных M2.
DEFAULT_SOURCE_PRIORITY = ["egr", "erp", "manual", "1c", "bitrix"]

#: стратегия по умолчанию для поля без явного правила.
DEFAULT_STRATEGY = "non_empty_wins"


@dataclass(frozen=True)
class FieldValue:
    """Кандидат на значение поля: само значение, его источник и дата изменения (ISO-строка)."""

    value: object
    source: str = "1c"
    at: str | None = None


@dataclass(frozen=True)
class Rule:
    """Правило слияния для одного поля."""

    strategy: str = DEFAULT_STRATEGY
    source_priority: tuple[str, ...] = ()

    def priority(self) -> list[str]:
        return list(self.source_priority) or DEFAULT_SOURCE_PRIORITY


def is_empty(value: object) -> bool:
    """Значение «пустое» для survivorship: None или строка из пробелов. Ноль/False — НЕ пусто."""
    return value is None or (isinstance(value, str) and value.strip() == "")


def decide(current: FieldValue | None, incoming: FieldValue, rule: Rule) -> FieldValue:
    """Вернуть значение-победитель для поля по правилу. ``current`` — что в эталоне (может быть None).

    Возвращается всегда один из аргументов (не мутирует) — вызывающий код решает, писать ли.
    """
    if current is None:
        return incoming

    strategy = rule.strategy
    if strategy == "manual_only":
        # синк не трогает; меняет только ручной ввод (source="manual")
        return incoming if incoming.source == "manual" else current

    if strategy == "source_priority":
        order = rule.priority()
        cur_rank = order.index(current.source) if current.source in order else len(order)
        inc_rank = order.index(incoming.source) if incoming.source in order else len(order)
        # меньший индекс = выше доверие; при равенстве — оставляем эталон (стабильность)
        return incoming if inc_rank < cur_rank else current

    if strategy == "most_recent":
        if is_empty(incoming.value):
            return current
        # ponytail: даты сравниваются как ISO-строки лексикографически — корректно для
        # разных дней и одинакового формата; в граничном «тот же день, разные форматы»
        # (date-only vs с временем) может ошибиться. Апгрейд — парсить в datetime, когда
        # источники начнут слать разный формат `at`.
        if current.at and incoming.at:
            return incoming if incoming.at >= current.at else current
        return incoming if incoming.at and not current.at else current

    # non_empty_wins (дефолт): непустое заполняет пустое; иначе эталон сохраняется
    if is_empty(current.value) and not is_empty(incoming.value):
        return incoming
    return current


async def load_rules(session: AsyncSession, entity_type: str) -> dict[str, Rule]:
    """Загрузить правила сущности из БД: ``{field: Rule}``. Поля без записи берут дефолт."""
    rows = (
        await session.execute(
            select(SurvivorshipRule).where(SurvivorshipRule.entity_type == entity_type)
        )
    ).scalars().all()
    return {
        r.field: Rule(strategy=r.strategy, source_priority=tuple(r.source_priority or ()))
        for r in rows
    }


def rule_for(rules: dict[str, Rule], field: str) -> Rule:
    """Правило поля или дефолт ``non_empty_wins`` (поле без явного правила)."""
    return rules.get(field, Rule())
