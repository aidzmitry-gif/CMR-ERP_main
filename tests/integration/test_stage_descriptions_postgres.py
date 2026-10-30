# ruff: noqa: F811 -- imported pytest fixture is requested by name.
"""Native migration and durable stage instruction acceptance on disposable databases."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import select, text

from modules.sales.models import Stage
from tests.accounting.test_postgres import pg_factory  # noqa: F401


@pytest.fixture
def accounting_pg_revision():
    return "0201"


def migrate(factory, *args):
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=60,
        env={**os.environ, "AIOS_ENVIRONMENT": "dev",
             "AIOS_DATABASE_URL": factory.kw["bind"].url.render_as_string(hide_password=False)},
    )


async def test_old_stage_survives_upgrade_and_empty_downgrade(pg_factory):
    async with pg_factory() as session:
        await session.execute(text("""
            INSERT INTO sales.stage(code,title,sort_order,probability,kind,color,is_active,funnel)
            VALUES ('qa_stage','Старая стадия',7,42,'normal','#123456',true,'new_clients')
        """))
        await session.commit()
        before = (await session.execute(text("SELECT * FROM sales.stage WHERE code='qa_stage'"))).mappings().one()
    up = await asyncio.to_thread(migrate, pg_factory, "upgrade", "0202")
    assert up.returncode == 0, up.stderr[-1500:]
    async with pg_factory() as session:
        after = (await session.execute(text("SELECT * FROM sales.stage WHERE code='qa_stage'"))).mappings().one()
        assert {key: after[key] for key in before} == dict(before)
        assert after["description"] == ""
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == "0202"
    down = await asyncio.to_thread(migrate, pg_factory, "downgrade", "0201")
    assert down.returncode == 0, down.stderr[-1500:]
    async with pg_factory() as session:
        assert dict((await session.execute(text("SELECT * FROM sales.stage WHERE code='qa_stage'"))).mappings().one()) == dict(before)
    up = await asyncio.to_thread(migrate, pg_factory, "upgrade", "0202")
    assert up.returncode == 0, up.stderr[-1500:]


async def test_committed_description_survives_new_connection_and_refuses_lossy_downgrade(pg_factory):
    up = await asyncio.to_thread(migrate, pg_factory, "upgrade", "0202")
    assert up.returncode == 0, up.stderr[-1500:]
    instruction = "Синтетическая инструкция.\nПроверить перед переходом."
    async with pg_factory() as session:
        session.add(Stage(code="qa_persist", title="Проверка", description=instruction))
        await session.commit()
    await pg_factory.kw["bind"].dispose()
    async with pg_factory() as session:
        assert await session.scalar(select(Stage.description).where(Stage.code == "qa_persist")) == instruction
    down = await asyncio.to_thread(migrate, pg_factory, "downgrade", "0201")
    assert down.returncode != 0 and "must be preserved" in down.stderr
    async with pg_factory() as session:
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == "0202"
        row = await session.scalar(select(Stage).where(Stage.code == "qa_persist"))
        assert row.description == instruction
        row.description = ""
        await session.commit()
    down = await asyncio.to_thread(migrate, pg_factory, "downgrade", "0201")
    assert down.returncode == 0, down.stderr[-1500:]
    up = await asyncio.to_thread(migrate, pg_factory, "upgrade", "0202")
    assert up.returncode == 0, up.stderr[-1500:]
    async with pg_factory() as session:
        assert await session.scalar(select(Stage.description).where(Stage.code == "qa_persist")) == ""
