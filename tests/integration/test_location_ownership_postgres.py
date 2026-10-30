# ruff: noqa: F811 -- imported fixture is requested by name.
"""Native migration preserves unknown legacy ownership and enforces new ownership."""

import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from modules.accounting.models import Organization
from modules.wms.location_scope import validate_location_ids
from modules.wms.models import Location, WarehouseDirectory
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.integration.test_stage_descriptions_postgres import migrate


@pytest.fixture
def accounting_pg_revision():
    return "0202"


async def test_unknown_legacy_location_survives_upgrade_and_empty_downgrade(pg_factory):
    async with pg_factory() as session:
        org = Organization(name="Synthetic owner", unp="999999921")
        session.add(org)
        await session.flush()
        session.add(WarehouseDirectory(organization_id=org.id, name="Shared", title="Synthetic", created_by="test"))
        await session.execute(text("INSERT INTO wms.location(warehouse,zone,code,title,is_active) VALUES ('Shared','A','LEGACY','Preserve',true)"))
        await session.commit()
        org_id = org.id
        before = dict((await session.execute(text("SELECT * FROM wms.location WHERE code='LEGACY'"))).mappings().one())
    up = await asyncio.to_thread(migrate, pg_factory, "upgrade", "0203")
    assert up.returncode == 0, up.stderr[-1500:]
    async with pg_factory() as session:
        after = dict((await session.execute(text("SELECT * FROM wms.location WHERE code='LEGACY'"))).mappings().one())
        assert {key: after[key] for key in before} == before
        assert after["organization_id"] is None  # Even a unique warehouse name is not ownership proof.
        with pytest.raises(HTTPException):
            await validate_location_ids(session, org_id, "Shared", after["id"])
    down = await asyncio.to_thread(migrate, pg_factory, "downgrade", "0202")
    assert down.returncode == 0, down.stderr[-1500:]
    async with pg_factory() as session:
        assert dict((await session.execute(text("SELECT * FROM wms.location WHERE code='LEGACY'"))).mappings().one()) == before
    up = await asyncio.to_thread(migrate, pg_factory, "upgrade", "0203")
    assert up.returncode == 0, up.stderr[-1500:]


async def test_native_owner_fk_persistence_and_downgrade_guard(pg_factory):
    up = await asyncio.to_thread(migrate, pg_factory, "upgrade", "0203")
    assert up.returncode == 0, up.stderr[-1500:]
    async with pg_factory() as session:
        first = Organization(name="Synthetic first", unp="999999922")
        second = Organization(name="Synthetic second", unp="999999923")
        session.add_all([first, second])
        await session.flush()
        own, other = first.id, second.id
        session.add_all([WarehouseDirectory(organization_id=ident, name="Shared", title="Synthetic", created_by="test") for ident in [own, other]])
        await session.flush()
        cells = [Location(organization_id=ident, warehouse="Shared", code="CELL") for ident in [own, other]]
        session.add_all(cells)
        await session.commit()
        ids = [row.id for row in cells]
        assert (await validate_location_ids(session, own, "Shared", ids[0]))[0].organization_id == own
        with pytest.raises(HTTPException):
            await validate_location_ids(session, own, "Shared", ids[1])
    await pg_factory.kw["bind"].dispose()
    async with pg_factory() as session:
        assert [(row.id, row.organization_id) for row in (await session.scalars(select(Location).order_by(Location.id))).all()] == list(zip(ids, [own, other]))
        session.add(Location(organization_id=own, warehouse="NotRegistered", code="FORGED"))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
    down = await asyncio.to_thread(migrate, pg_factory, "downgrade", "0202")
    assert down.returncode != 0 and "must be preserved" in down.stderr
    async with pg_factory() as session:
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == "0203"
        assert (await session.get(Location, ids[1])).organization_id == other
