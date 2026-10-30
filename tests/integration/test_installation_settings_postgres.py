"""Native CAS proof in a disposable schema; no business rows are touched."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from core.domain.installation import PlatformInstallation
from core.domain.models import AuditLog
from core.services.auth import CurrentUser
from core.services.installation_settings import InstallationOrganizationUpdate, save_settings


@pytest_asyncio.fixture
async def installation_pg(postgres_url):
    schema = "installation_scope_" + uuid4().hex
    engine = create_async_engine(postgres_url, execution_options={"schema_translate_map": {None: schema}})
    async with engine.begin() as connection:
        await connection.execute(CreateSchema(schema))
        await connection.run_sync(lambda conn: PlatformInstallation.__table__.create(conn))
        await connection.run_sync(lambda conn: AuditLog.__table__.create(conn))
    try:
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True))
        await engine.dispose()


USER = CurrentUser("synthetic-admin", ["director"])


async def organizations(*_):
    return [{"id": n, "name": f"Synthetic {n}", "unp": f"12345678{n}"} for n in [7, 8, 9]]


GATEWAY = SimpleNamespace(source_organizations=organizations)


def command(organization_id=7, expected_revision=0):
    return InstallationOrganizationUpdate(organization_id=organization_id, expected_revision=expected_revision, request_id=uuid4())


def concurrent_factory(engine):
    barrier = asyncio.Barrier(2)

    class ReadTogether(AsyncSession):
        async def get(self, entity, ident, **kwargs):
            value = await super().get(entity, ident, **kwargs)
            if entity is PlatformInstallation:
                await asyncio.wait_for(barrier.wait(), 10)
            return value

    return async_sessionmaker(engine, class_=ReadTogether, expire_on_commit=False)


async def run_race(factory, commands):
    async def run(body):
        async with factory() as session:
            return await save_settings(session, USER, GATEWAY, body)
    results = await asyncio.gather(*(run(body) for body in commands), return_exceptions=True)
    assert len([value for value in results if isinstance(value, dict)]) == 1, results
    errors = [value for value in results if isinstance(value, HTTPException)]
    assert len(errors) == 1 and errors[0].status_code == 409, results


async def test_only_one_concurrent_initial_selection_commits(installation_pg):
    await run_race(concurrent_factory(installation_pg), [command(7), command(8)])
    async with async_sessionmaker(installation_pg)() as session:
        assert (await session.get(PlatformInstallation, 1)).revision == 1
        assert await session.scalar(select(func.count()).select_from(AuditLog)) == 1


async def test_only_one_concurrent_revision_update_commits(installation_pg):
    async with async_sessionmaker(installation_pg)() as session:
        await save_settings(session, USER, GATEWAY, command())
    await run_race(concurrent_factory(installation_pg), [command(8, 1), command(9, 1)])
    async with async_sessionmaker(installation_pg)() as session:
        row = await session.get(PlatformInstallation, 1)
        assert row.revision == 2 and row.organization_id in [8, 9]
        assert await session.scalar(select(func.count()).select_from(AuditLog)) == 2


async def test_retry_from_another_worker_does_not_duplicate_the_setting(installation_pg):
    body = command()
    async with async_sessionmaker(installation_pg)() as session:
        original = await save_settings(session, USER, GATEWAY, body)
    async with async_sessionmaker(installation_pg)() as session:
        assert await save_settings(session, USER, GATEWAY, body) == original
        assert await session.scalar(select(func.count()).select_from(AuditLog)) == 1
