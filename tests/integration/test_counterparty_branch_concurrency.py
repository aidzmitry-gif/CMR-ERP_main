"""Real migrated PostgreSQL: two observed waiters cannot overwrite one branch revision."""
from sqlalchemy import delete, select

from core.domain.models import AuditLog, CounterpartyBranch
from tests.integration.test_counterparty_requisites import _queued_writes, _synthetic


async def test_branch_patch_waiters_have_one_winner(pg_app):
    async with _synthetic(pg_app) as (factory, marker, unp, tasks):
        created = await pg_app.post("/system/mdm/counterparty", json={"manual": {
            "name": f"{marker}-base", "legal_name": "Verified synthetic name", "unp": unp,
        }})
        assert created.status_code == 201, created.text
        parent = created.json()
        collection = f"/system/mdm/counterparty/{parent['id']}/branches"
        initial = await pg_app.post(collection, json={
            "expected_legal_entity_revision": parent["revision"], "manual": {"name": "Initial branch"},
        })
        assert initial.status_code == 201, initial.text
        branch = initial.json()
        try:
            async def writer(name):
                return await pg_app.patch(f"{collection}/{branch['id']}", json={
                    "expected_legal_entity_revision": parent["revision"],
                    "expected_revision": branch["revision"], "manual": {"name": name},
                })
            responses, waiters = await _queued_writes(
                factory, None, tasks, lambda: writer("Winner A"), lambda: writer("Winner B"),
                counterparty_id=parent["id"],
            )
            assert len(waiters) == 2
            assert sorted(r.status_code for r in responses) == [200, 409]
            winner = next(r.json() for r in responses if r.status_code == 200)
            async with factory() as session:
                saved = await session.get(CounterpartyBranch, branch["id"])
                assert saved.name == winner["name"]
                assert saved.revision == branch["revision"] + 1
                audits = (await session.scalars(select(AuditLog).where(
                    AuditLog.entity_ref == f"counterparty:{parent['id']}",
                    AuditLog.action == "counterparty.branch.updated",
                ))).all()
                assert len(audits) == 1
        finally:
            assert all(task.done() for task in tasks)
            async with factory() as session:
                await session.execute(delete(CounterpartyBranch).where(
                    CounterpartyBranch.id == branch["id"],
                    CounterpartyBranch.legal_entity_id == parent["id"],
                ))
                await session.commit()
