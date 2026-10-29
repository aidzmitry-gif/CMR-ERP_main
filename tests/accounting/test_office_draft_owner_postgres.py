"""Native upgrade, immutable author identity and Office role workflow."""
# ruff: noqa: F811 -- imported native fixture.
import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from core.domain.models import User
from core.runtime.app import create_app
from core.runtime.deps import get_session
from core.services.logistics import snapshot_value
from modules.office.models import OfficeDoc
from modules.office.shipping_producer import office_row_snapshot
from tests.accounting.test_postgres import pg_factory  # noqa: F401

pytestmark = pytest.mark.integration


async def migrate(factory, direction, target):
    async with factory() as session:
        url = session.bind.url.render_as_string(hide_password=False)
    return await asyncio.to_thread(
        subprocess.run, [sys.executable, "-m", "alembic", direction, target],
        env={**os.environ, "AIOS_DATABASE_URL": url, "AIOS_ENVIRONMENT": "dev"},
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=60,
    )


@pytest.mark.parametrize("accounting_pg_revision", ["0198"], indirect=True)
async def test_upgrade_preserves_legacy_and_guards_authorship(pg_factory):
    async with pg_factory() as session:
        legacy_id = await session.scalar(text(
            "INSERT INTO office.office_doc(title,owner) VALUES ('Synthetic legacy','named-owner') RETURNING id"
        ))
        before = await session.scalar(text("SELECT to_jsonb(d) FROM office.office_doc d WHERE id=:id"), {"id": legacy_id})
        legacy_snapshot = snapshot_value(dict((await session.execute(
            text("SELECT * FROM office.office_doc WHERE id=:id"), {"id": legacy_id}
        )).mappings().one()))
        await session.commit()
    result = await migrate(pg_factory, "upgrade", "0199")
    assert result.returncode == 0, result.stderr[-1500:]
    async with pg_factory() as session:
        row = await session.scalar(text("SELECT to_jsonb(d) FROM office.office_doc d WHERE id=:id"), {"id": legacy_id})
        assert row.pop("draft_owner_subject") is None
        assert row == before
        assert office_row_snapshot(await session.get(OfficeDoc, legacy_id)) == legacy_snapshot
    result = await migrate(pg_factory, "downgrade", "0198")
    assert result.returncode == 0, result.stderr[-1500:]
    result = await migrate(pg_factory, "upgrade", "0199")
    assert result.returncode == 0, result.stderr[-1500:]
    async with pg_factory() as session:
        draft = OfficeDoc(title="Synthetic new draft", stage="draft", draft_owner_subject="author")
        session.add(draft)
        await session.commit()
        draft_id = draft.id
    for row_id in (legacy_id, draft_id):
        async with pg_factory() as session:
            with pytest.raises(DBAPIError, match="Office draft owner is immutable"):
                await session.execute(text(
                    "UPDATE office.office_doc SET draft_owner_subject='other' WHERE id=:id"
                ), {"id": row_id})
            await session.rollback()
    result = await migrate(pg_factory, "downgrade", "0198")
    assert result.returncode != 0
    assert "Office draft ownership history prevents downgrade" in result.stderr
    async with pg_factory() as session:
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == "0199"
        assert (await session.get(OfficeDoc, legacy_id)).draft_owner_subject is None
        assert (await session.get(OfficeDoc, draft_id)).draft_owner_subject == "author"


async def test_native_author_and_supervisor_workflow(pg_factory):
    async with pg_factory() as session:
        session.add_all([
            User(username="author", full_name="Synthetic author", role="finance", status="active"),
            User(username="reviewer", full_name="Synthetic reviewer", role="finance", status="active"),
            User(username="supervisor", full_name="Synthetic supervisor", role="director", status="active"),
        ])
        await session.commit()
    app = create_app()
    app.state.core.services.db.session_factory = pg_factory

    async def session_override():
        async with pg_factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           headers={"X-User": "author", "X-User-Roles": "finance"}) as client:
        response = await client.post("/office/docs", json={"title": "Synthetic native draft"})
        assert response.status_code == 201, response.text
        draft_id = response.json()["id"]
        assert response.json()["stage"] == "draft"
        assert (await client.patch(f"/office/docs/{draft_id}", json={"stage": "paid"})).status_code == 403
        client.headers["X-User"] = "reviewer"
        assert (await client.get("/office/docs")).json() == []
        assert (await client.patch(f"/office/docs/{draft_id}", json={"stage": "draft"})).status_code == 404
        assignment = {"subject": "reviewer", "expected_revision": 0, "evidence": "Synthetic supervisor review"}
        assert (await client.post(f"/office/docs/{draft_id}/shipping-reviewer", json=assignment)).status_code == 403
        client.headers.update({"X-User": "supervisor", "X-User-Roles": "director"})
        assigned = await client.post(f"/office/docs/{draft_id}/shipping-reviewer", json=assignment)
        assert assigned.status_code == 200, assigned.text
        client.headers.update({"X-User": "reviewer", "X-User-Roles": "finance"})
        response = await client.patch(f"/office/docs/{draft_id}", json={"stage": "ready"})
        assert response.status_code == 200, response.text
        client.headers["X-User"] = "author"
        assert (await client.get("/office/docs")).json() == []
    async with pg_factory() as session:
        assert (await session.get(OfficeDoc, draft_id)).draft_owner_subject == "author"
