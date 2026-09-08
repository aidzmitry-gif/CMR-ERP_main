"""G09: queued concurrent writes on migrated, isolated PostgreSQL via real pg_app.

Collection is not PostgreSQL proof; the fixture's infrastructure skip is not PASS.
PATCH cases cover both the shared UNP advisory queue and dirty fields without
UNP, which wait only on the row lock. Both require observed concurrent waiters.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from secrets import randbelow
from uuid import uuid4

from sqlalchemy import delete, func, select, text

from core.domain.models import (
    AuditLog,
    Contact,
    Counterparty,
    CounterpartyUnpConflict,
    lock_counterparty_unps,
)

WAITERS = text("""
    SELECT DISTINCT waiting.pid
    FROM pg_locks AS held
    JOIN pg_locks AS waiting
      ON waiting.locktype = held.locktype
     AND waiting.database = held.database
     AND waiting.classid = held.classid
     AND waiting.objid = held.objid
     AND waiting.objsubid = held.objsubid
    WHERE held.pid = :holder_pid AND held.locktype = 'advisory' AND held.granted
      AND NOT waiting.granted AND waiting.pid <> held.pid
""")


@asynccontextmanager
async def _synthetic(pg_app):
    app = pg_app._transport.app
    db = app.state.core.services.db
    assert not app.dependency_overrides, "This proof requires real request sessions"
    assert db.engine.dialect.name == "postgresql", "SQLite is not concurrency proof"
    factory = db.session_factory
    marker = f"G09-PG-{uuid4().hex}"
    unp = str(100_000_000 + randbelow(900_000_000))
    names = [f"{marker}-{suffix}" for suffix in ("base", "A", "B", "orm")]
    async with asyncio.timeout(10):
        async with factory() as session:
            assert await session.scalar(select(Counterparty.id).where(func.trim(Counterparty.unp) == unp)) is None
    tasks = []
    try:
        yield factory, marker, unp, tasks
    finally:
        # Never delete rows while a writer might still commit. _queued_writes
        # drains these tasks first; a failed cancellation leaves data for diagnosis.
        assert all(task.done() for task in tasks), "Writer still active; synthetic cleanup refused"
        async with asyncio.timeout(10):
            async with factory() as session:
                ids = list(await session.scalars(select(Counterparty.id).where(
                    Counterparty.unp == unp, Counterparty.name.in_(names),
                )))
                if ids:
                    await session.execute(delete(Contact).where(Contact.counterparty_id.in_(ids)))
                    await session.execute(delete(AuditLog).where(
                        AuditLog.entity_ref.in_([f"counterparty:{value}" for value in ids]),
                    ))
                    await session.execute(delete(Counterparty).where(Counterparty.id.in_(ids)))
                    await session.commit()


async def _row_waiter_pids(observer, holder_pid):
    # A second row writer may wait on the first writer's tuple lock, so follow
    # the actual blocking chain rather than require a direct edge to the holder.
    await observer.execute(text("SELECT pg_stat_clear_snapshot()"))
    blocked = (await observer.execute(text("""
        SELECT DISTINCT locks.pid, pg_blocking_pids(locks.pid) AS blockers
        FROM pg_locks AS locks
        JOIN pg_stat_activity AS activity ON activity.pid = locks.pid
        WHERE NOT locks.granted AND activity.datname = current_database()
          AND activity.state = 'active' AND activity.wait_event_type = 'Lock'
    """))).all()
    connected = {holder_pid}
    while True:
        expanded = connected | {pid for pid, blockers in blocked if connected.intersection(blockers)}
        if expanded == connected:
            return connected - {holder_pid}
        connected = expanded


async def _queued_writes(factory, unp, tasks, *writers, counterparty_id=None):
    """Keep two distinct DB backends queued on the actual application lock."""
    assert len(writers) == 2
    async with factory() as holder, factory() as observer:
        try:
            async with asyncio.timeout(10):
                holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
                observer_pid = await observer.scalar(text("SELECT pg_backend_pid()"))
                assert holder_pid != observer_pid
                if counterparty_id is None:
                    await holder.run_sync(lambda sync: lock_counterparty_unps(sync, {unp}))
                    assert await observer.scalar(text("""
                        SELECT count(*) FROM pg_locks
                        WHERE pid = :pid AND locktype = 'advisory' AND granted
                    """), {"pid": holder_pid}) == 1
                else:
                    assert await holder.scalar(select(Counterparty.id).where(
                        Counterparty.id == counterparty_id,
                    ).with_for_update()) == counterparty_id
                tasks.extend(asyncio.create_task(writer()) for writer in writers)
                while True:
                    pids = await _row_waiter_pids(observer, holder_pid) if counterparty_id is not None else set(
                        await observer.scalars(WAITERS, {"holder_pid": holder_pid}),
                    )
                    if len(pids) == 2:
                        assert not pids.intersection({holder_pid, observer_pid})
                        assert all(not task.done() for task in tasks)
                        break
                    if any(task.done() for task in tasks):
                        results = [task.result() for task in tasks if task.done()]
                        raise AssertionError(f"Writer finished before proven overlap: {results!r}")
                    await asyncio.sleep(0.05)
            # Only now may either writer proceed. No assumption about which wins.
            await asyncio.wait_for(holder.rollback(), timeout=5)
            _, pending = await asyncio.wait(tasks, timeout=15)
            assert not pending, "Queued writers did not finish after lock release"
            return [task.result() for task in tasks], pids
        finally:
            try:
                await asyncio.wait_for(holder.rollback(), timeout=5)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                if tasks:
                    _, pending = await asyncio.wait(tasks, timeout=10)
                    assert not pending, "Writer cancellation did not drain"
                    await asyncio.gather(*tasks, return_exceptions=True)
                await asyncio.wait_for(observer.rollback(), timeout=5)


async def _stored(factory, unp):
    # A fresh session after both request sessions ended proves committed state.
    async with asyncio.timeout(10):
        async with factory() as session:
            companies = list(await session.scalars(select(Counterparty).where(Counterparty.unp == unp)))
            ids = [company.id for company in companies]
            contacts = list(await session.scalars(select(Contact).where(Contact.counterparty_id.in_(ids))))
            audit = list(await session.scalars(select(AuditLog).where(
                AuditLog.entity_ref.in_([f"counterparty:{value}" for value in ids]),
            ).order_by(AuditLog.id)))
            return companies, contacts, audit


async def test_same_unp_api_creates_overlap_and_only_winner_persists(pg_app):
    async with _synthetic(pg_app) as (factory, marker, unp, tasks):
        payloads = [{
            "manual": {"name": f"{marker}-{suffix}", "unp": unp, "bank_name": f"Bank {suffix}"},
            "contacts": [{"full_name": f"{marker}-{suffix}", "phone": f"+37529000000{index}", "is_primary": True}],
        } for index, suffix in enumerate(("A", "B"))]
        responses, _ = await _queued_writes(factory, unp, tasks, *[
            lambda payload=payload: pg_app.post("/system/mdm/counterparty", json=payload)
            for payload in payloads
        ])
        assert sorted(response.status_code for response in responses) == [201, 409]
        winner = next(index for index, response in enumerate(responses) if response.status_code == 201)
        receipt, conflict = responses[winner].json(), responses[1 - winner].json()["detail"]
        assert conflict["code"] == "duplicate_unp" and conflict["ids"] == [receipt["id"]]
        companies, contacts, audit = await _stored(factory, unp)
        assert len(companies) == len(contacts) == len(audit) == 1
        cp = companies[0]
        assert cp.is_active and cp.id == receipt["id"] and cp.revision == receipt["revision"]
        assert cp.name == payloads[winner]["manual"]["name"]
        assert cp.requisites["bank_name"] == payloads[winner]["manual"]["bank_name"]
        assert contacts[0].full_name == payloads[winner]["contacts"][0]["full_name"]
        assert contacts[0].is_primary and audit[0].actor
        assert audit[0].action == "counterparty.created"
        assert audit[0].detail["after"]["name"] == cp.name
        assert audit[0].detail["revision"] == cp.revision


async def test_same_revision_updates_overlap_without_loser_contacts_or_audit(pg_app):
    async with _synthetic(pg_app) as (factory, marker, unp, tasks):
        async with asyncio.timeout(10):
            created = await pg_app.post("/system/mdm/counterparty", json={
                "manual": {"name": f"{marker}-base", "unp": unp, "bank_name": "Base bank"},
                "contacts": [{"full_name": f"{marker}-base", "is_primary": True}],
            })
        assert created.status_code == 201, created.text
        receipt = created.json()
        _, initial_contacts, _ = await _stored(factory, unp)
        contact_id = initial_contacts[0].id
        payloads = [{
            "expected_revision": receipt["revision"],
            "manual": {"name": f"{marker}-{suffix}", "unp": unp, "bank_name": f"Bank {suffix}"},
            "contacts": [
                {"id": contact_id, "full_name": f"{marker}-{suffix}", "phone": f"+37529000000{index}"},
                {"full_name": f"{marker}-{suffix}-new", "email": f"{suffix.lower()}@example.invalid", "is_primary": True},
            ],
        } for index, suffix in enumerate(("A", "B"))]
        responses, _ = await _queued_writes(factory, unp, tasks, *[
            lambda payload=payload: pg_app.patch(f"/system/mdm/counterparty/{receipt['id']}", json=payload)
            for payload in payloads
        ])
        assert sorted(response.status_code for response in responses) == [200, 409]
        winner = next(index for index, response in enumerate(responses) if response.status_code == 200)
        assert responses[1 - winner].json()["detail"]["code"] == "stale_revision"
        companies, contacts, audit = await _stored(factory, unp)
        assert len(companies) == 1 and companies[0].is_active
        cp = companies[0]
        assert cp.revision == receipt["revision"] + 1 == responses[winner].json()["revision"]
        assert cp.name == payloads[winner]["manual"]["name"]
        assert cp.requisites["bank_name"] == payloads[winner]["manual"]["bank_name"]
        assert len(contacts) == 2
        assert {contact.full_name for contact in contacts} == {patch["full_name"] for patch in payloads[winner]["contacts"]}
        original = next(contact for contact in contacts if contact.id == contact_id)
        assert original.phone == payloads[winner]["contacts"][0]["phone"] and not original.is_primary
        new = next(contact for contact in contacts if contact.id != contact_id)
        assert new.is_primary and new.email == payloads[winner]["contacts"][1]["email"]
        assert [entry.action for entry in audit] == ["counterparty.created", "counterparty.updated"]
        assert audit[1].actor and audit[1].detail["revision"] == cp.revision
        assert audit[1].detail["before"]["name"] == f"{marker}-base"
        assert audit[1].detail["after"]["name"] == cp.name
        assert {contact["full_name"] for contact in audit[1].detail["after"]["contacts"]} == {contact.full_name for contact in contacts}


async def test_row_only_patch_overlaps_without_loser_address_contact_or_audit(pg_app):
    async with _synthetic(pg_app) as (factory, marker, unp, tasks):
        async with asyncio.timeout(10):
            created = await pg_app.post("/system/mdm/counterparty", json={
                "manual": {"name": f"{marker}-base", "unp": unp, "legal_address": "Base address"},
                "contacts": [{"full_name": f"{marker}-base", "phone": "+375290000000", "is_primary": True}],
            })
        assert created.status_code == 201, created.text
        receipt = created.json()
        _, initial_contacts, _ = await _stored(factory, unp)
        assert len(initial_contacts) == 1
        contact_id = initial_contacts[0].id
        payloads = [{
            "expected_revision": receipt["revision"],
            "manual": {"legal_address": f"Address {suffix}"},
            "contacts": [{"id": contact_id, "full_name": f"{marker}-{suffix}", "phone": f"+37529000000{index}"}],
        } for index, suffix in enumerate(("A", "B"), start=1)]
        # Neither request has manual.unp or registry: only SELECT FOR UPDATE
        # can hold them behind our separate row-lock holder.
        responses, waiters = await _queued_writes(factory, None, tasks, *[
            lambda payload=payload: pg_app.patch(f"/system/mdm/counterparty/{receipt['id']}", json=payload)
            for payload in payloads
        ], counterparty_id=receipt["id"])
        assert len(waiters) == 2
        assert sorted(response.status_code for response in responses) == [200, 409]
        winner = next(index for index, response in enumerate(responses) if response.status_code == 200)
        assert responses[1 - winner].json()["detail"]["code"] == "stale_revision"
        companies, contacts, audit = await _stored(factory, unp)
        assert len(companies) == len(contacts) == 1
        cp, contact = companies[0], contacts[0]
        assert cp.is_active and cp.id == receipt["id"] == responses[winner].json()["id"]
        assert cp.name == f"{marker}-base" and cp.unp == unp
        assert cp.revision == receipt["revision"] + 1 == responses[winner].json()["revision"]
        assert cp.requisites["legal_address"] == payloads[winner]["manual"]["legal_address"]
        assert contact.id == contact_id and contact.is_primary
        assert contact.full_name == payloads[winner]["contacts"][0]["full_name"]
        assert contact.phone == payloads[winner]["contacts"][0]["phone"]
        assert [entry.action for entry in audit] == ["counterparty.created", "counterparty.updated"]
        assert audit[1].actor and audit[1].detail["revision"] == cp.revision
        assert audit[1].detail["before"]["requisites"]["legal_address"] == "Base address"
        assert audit[1].detail["after"]["requisites"]["legal_address"] == cp.requisites["legal_address"]
        assert len(audit[1].detail["after"]["contacts"]) == 1
        assert audit[1].detail["after"]["contacts"][0]["full_name"] == contact.full_name
        assert audit[1].detail["after"]["contacts"][0]["phone"] == contact.phone


async def test_api_and_direct_orm_share_unp_lock_and_recheck(pg_app):
    async with _synthetic(pg_app) as (factory, marker, unp, tasks):
        async def orm_writer():
            async with factory() as session:
                pid = await session.scalar(text("SELECT pg_backend_pid()"))
                try:
                    cp = Counterparty(name=f"{marker}-orm", unp=unp, requisites={"bank_name": "ORM bank"})
                    session.add(cp)
                    await session.flush()  # actual before_flush guard, no manual lock call
                    session.add(Contact(counterparty_id=cp.id, full_name=f"{marker}-orm", is_primary=True))
                    await session.commit()
                    return {"status": 201, "pid": pid, "id": cp.id, "revision": cp.revision}
                except CounterpartyUnpConflict as exc:
                    await session.rollback()
                    return {"status": 409, "pid": pid, "ids": exc.ids}

        responses, waiters = await _queued_writes(
            factory, unp, tasks,
            lambda: pg_app.post("/system/mdm/counterparty", json={
                "manual": {"name": f"{marker}-A", "unp": unp, "bank_name": "API bank"},
                "contacts": [{"full_name": f"{marker}-A", "is_primary": True}],
            }),
            orm_writer,
        )
        api_response, orm_result = responses
        assert orm_result["pid"] in waiters
        assert sorted([api_response.status_code, orm_result["status"]]) == [201, 409]
        api_won = api_response.status_code == 201
        receipt = api_response.json() if api_won else orm_result
        conflict = orm_result if api_won else api_response.json()["detail"]
        assert conflict["ids"] == [receipt["id"]]
        if not api_won:
            assert conflict["code"] == "duplicate_unp"
        companies, contacts, audit = await _stored(factory, unp)
        assert len(companies) == len(contacts) == 1
        cp = companies[0]
        assert cp.is_active and cp.id == receipt["id"] and cp.revision == receipt["revision"]
        assert cp.name == f"{marker}-{'A' if api_won else 'orm'}"
        assert cp.requisites["bank_name"] == ("API bank" if api_won else "ORM bank")
        assert contacts[0].full_name == cp.name and contacts[0].is_primary
        # The legacy direct ORM writer has no API audit side effect. A losing
        # API request must not leave one; a winning API request must have one.
        assert len(audit) == int(api_won)
        if api_won:
            assert audit[0].action == "counterparty.created" and audit[0].actor
            assert audit[0].detail["after"]["name"] == cp.name
