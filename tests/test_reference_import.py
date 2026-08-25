"""Идемпотентная загрузка контрагентов (входной адаптер 1С): upsert по УНП + alias."""
import pytest
from sqlalchemy import func, select

from core.domain.models import Counterparty
from core.services import reference_import


async def _count(session, model) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar() or 0


async def test_upsert_creates_then_matches(session):
    # первый импорт — создаёт + alias
    r1 = await reference_import.upsert_counterparty(
        session, unp="191234567", name="ООО Ромашка", source="1c", external_ref="0000-1"
    )
    assert r1.created is True
    assert r1.alias_added is True
    await session.flush()

    # повтор тех же данных — матч по УНП, без новых записей и без дубля алиаса
    r2 = await reference_import.upsert_counterparty(
        session, unp="191234567", name="ООО Ромашка", source="1c", external_ref="0000-1"
    )
    assert r2.created is False
    assert r2.alias_added is False
    assert r2.counterparty.id == r1.counterparty.id

    assert await _count(session, Counterparty) == 1


async def test_upsert_fills_empty_name_and_adds_new_alias(session):
    a = Counterparty(name="", unp="100045678")
    session.add(a)
    await session.flush()

    r = await reference_import.upsert_counterparty(
        session, unp="100045678", name="ОАО БелАвтоТех", source="bitrix", external_ref="14502"
    )
    assert r.created is False
    assert r.counterparty.id == a.id
    assert a.name == "ОАО БелАвтоТех"  # пустое имя заполнено из источника
    assert r.alias_added is True


async def test_existing_name_not_overwritten(session):
    a = Counterparty(name="Точное имя", unp="222333444")
    session.add(a)
    await session.flush()

    await reference_import.upsert_counterparty(
        session, unp="222333444", name="Имя из 1С", source="1c", external_ref="x"
    )
    assert a.name == "Точное имя"  # существующее имя не перезатёрто


async def test_batch_import_summary_idempotent(session):
    rows = [
        {"unp": "111", "name": "A", "id": "a1"},
        {"unp": "222", "name": "B", "id": "b1"},
        {"unp": "111", "name": "A", "id": "a1"},  # дубль строки → матч, без новой записи
    ]
    summary = await reference_import.import_counterparties(session, rows)
    assert summary == {
        "total": 3,
        "created": 2,
        "matched": 1,
        "aliases_added": 2,
        "skipped_no_unp": 0,
    }
    assert await _count(session, Counterparty) == 2

    # повторный прогон того же батча — всё матчится, ничего не создаётся
    again = await reference_import.import_counterparties(session, rows)
    assert again["created"] == 0
    assert await _count(session, Counterparty) == 2


async def test_batch_skips_rows_without_unp(session):
    rows = [
        {"unp": "", "name": "Группа без УНП", "id": "g1"},
        {"unp": None, "name": "Ещё без", "id": "g2"},
        {"unp": "191000001", "name": "ООО С УНП", "id": "c1"},
    ]
    summary = await reference_import.import_counterparties(session, rows)
    assert summary["skipped_no_unp"] == 2
    assert summary["created"] == 1
    assert summary["total"] == 3
    assert await _count(session, Counterparty) == 1


async def test_upsert_requires_unp(session):
    with pytest.raises(ValueError):
        await reference_import.upsert_counterparty(session, unp="", name="без УНП")


async def test_batch_import_skips_rows_without_unp(session):
    summary = await reference_import.import_counterparties(
        session,
        [
            {"unp": "", "name": "Группа 1С", "id": "group-1"},
            {"unp": "191234567", "name": "ООО Ромашка", "id": "cp-1"},
        ],
    )
    assert summary == {
        "total": 2,
        "created": 1,
        "matched": 0,
        "aliases_added": 1,
        "skipped_no_unp": 1,
    }
    assert await _count(session, Counterparty) == 1
