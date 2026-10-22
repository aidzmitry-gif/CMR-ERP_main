"""Registered Finance ownership migrations and concurrent bank settlement, synthetic only."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text

from core.domain.models import OutboxEvent, User
from core.services.auth import CurrentUser
from core.services.eventbus import OutboxEventBus
from modules.accounting.gateway import AccountingService
from modules.accounting.models import SourceBinding
from modules.finance.models import BankTransaction, Payment, PaymentAllocation
from modules.finance.routes import match_bank_transaction
from modules.finance.schemas import BankManualMatch
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401 — owned native fixtures

pytestmark = [pytest.mark.integration,
              pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)]


async def _alembic(factory, tmp_path, command, revision, *, refusal=None):
    engine = factory.kw["bind"]
    root = Path(__file__).resolve().parents[2]
    database = engine.url.database
    assert database and database.startswith("acc_test_") and len(database) == 41
    async with engine.connect() as conn:
        marker = await conn.scalar(text(
            "SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname=current_database()"))
        assert marker == f"crm-acc-fixture:{database}"
    env = dict(os.environ, AIOS_ENVIRONMENT="dev", AIOS_AUTH_MODE="dev",
               AIOS_DATABASE_URL=engine.url.render_as_string(hide_password=False))
    env.pop("ALEMBIC_CONFIG", None)
    log = tmp_path / f"{command}-{revision}-{len(list(tmp_path.iterdir()))}.private.log"
    with log.open("xb") as stream:
        result = await asyncio.to_thread(subprocess.run,
            [sys.executable, "-B", "-m", "alembic", "-c", str(root / "alembic.ini"), command, revision],
            cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=150)
    if refusal is None:
        assert result.returncode == 0, "Native migration failed; private log retained"
    else:
        assert result.returncode != 0, "Unsafe downgrade unexpectedly succeeded"
        assert f"RuntimeError: {refusal}" in log.read_text(encoding="utf-8", errors="replace"), (
            "Migration did not refuse for its exact expected guard; private log retained")


async def _state(factory):
    async with factory() as session:
        rows = {}
        for table in ("public.app_user", "finance.bank_account", "finance.payment"):
            rows[table] = (await session.scalars(text(
                f"SELECT to_jsonb(row) FROM {table} row ORDER BY id"))).all()
        constraints = (await session.execute(text("""
            SELECT n.nspname, c.relname, k.conname, pg_get_constraintdef(k.oid)
            FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='finance' OR (n.nspname='public' AND c.relname='app_user')
            ORDER BY 1,2,3
        """))).all()
        indexes = (await session.execute(text("""
            SELECT schemaname, tablename, indexname, indexdef FROM pg_indexes
            WHERE schemaname='finance' OR (schemaname='public' AND tablename='app_user')
            ORDER BY 1,2,3
        """))).all()
        revision = (await session.scalars(text("SELECT version_num FROM alembic_version"))).all()
        return rows, constraints, indexes, revision


async def _legacy(factory):
    async with factory() as session:
        await session.execute(text("""
            INSERT INTO app_user(username, full_name, employee_id) VALUES ('synthetic-legacy', 'Synthetic legacy', 9901)
        """))
        await session.execute(text("""
            INSERT INTO finance.bank_account(code,title,opening_balance) VALUES ('synthetic-old','Synthetic old',12.34)
        """))
        await session.execute(text("""
            INSERT INTO finance.payment(ref,amount,account_id) VALUES ('SYN-LEGACY',45.67,
                (SELECT id FROM finance.bank_account WHERE code='synthetic-old'))
        """))
        await session.commit()


async def test_registered_upgrade_0194_to_0196_preserves_legacy_rows(pg_factory, tmp_path):
    await _alembic(pg_factory, tmp_path, "downgrade", "0194")
    await _legacy(pg_factory)
    before = await _state(pg_factory)
    await _alembic(pg_factory, tmp_path, "upgrade", "0196")
    after = await _state(pg_factory)
    assert after[3] == ["0196"]
    for table, rows in before[0].items():
        expected = [dict(row, organization_id=None) if table.startswith("finance.") else row for row in rows]
        assert after[0][table] == expected
    assert any(row[2] == "ix_app_user_employee_id" for row in after[2])


async def test_registered_0196_clean_roundtrip_preserves_rows_and_constraints(pg_factory, tmp_path):
    await _alembic(pg_factory, tmp_path, "downgrade", "0194")
    await _legacy(pg_factory)
    before = await _state(pg_factory)
    await _alembic(pg_factory, tmp_path, "upgrade", "0196")
    at_head = await _state(pg_factory)
    await _alembic(pg_factory, tmp_path, "downgrade", "0194")
    assert await _state(pg_factory) == before
    await _alembic(pg_factory, tmp_path, "upgrade", "0196")
    assert await _state(pg_factory) == at_head


async def test_0195_downgrade_refuses_aliases_atomically(pg_factory, tmp_path):
    await _alembic(pg_factory, tmp_path, "downgrade", "0195")
    async with pg_factory() as session:
        await session.execute(text("""
            INSERT INTO app_user(username,full_name,employee_id) VALUES
            ('synthetic-alias-a','Synthetic alias',9901),('synthetic-alias-b','Synthetic alias',9901)
        """))
        await session.commit()
    before = await _state(pg_factory)
    await _alembic(pg_factory, tmp_path, "downgrade", "0194",
                   refusal="Resolve login aliases before restoring one-account constraint")
    assert await _state(pg_factory) == before


async def test_0196_downgrade_refuses_owned_account_atomically(pg_factory, pg_book, tmp_path):
    async with pg_factory() as session:
        await session.execute(text("""INSERT INTO finance.bank_account(organization_id,code,title)
            VALUES (:org,'owned','Synthetic owned')"""), {"org": pg_book[0]})
        await session.commit()
    before = await _state(pg_factory)
    await _alembic(pg_factory, tmp_path, "downgrade", "0195",
                   refusal="Confirmed Finance ownership cannot be discarded; use the verified release restore")
    assert await _state(pg_factory) == before


async def test_0196_downgrade_refuses_owned_payment_atomically(pg_factory, pg_book, tmp_path):
    async with pg_factory() as session:
        await session.execute(text("""INSERT INTO finance.payment(organization_id,ref,amount,account_id)
            VALUES (:org,'SYN-OWNED',123.45,NULL)"""), {"org": pg_book[0]})
        await session.commit()
    before = await _state(pg_factory)
    await _alembic(pg_factory, tmp_path, "downgrade", "0195",
                   refusal="Confirmed Finance ownership cannot be discarded; use the verified release restore")
    assert await _state(pg_factory) == before


async def test_0196_downgrade_refuses_duplicate_legacy_codes_atomically(pg_factory, tmp_path):
    async with pg_factory() as session:
        await session.execute(text("""INSERT INTO finance.bank_account(organization_id,code,title)
            VALUES (NULL,'same','Synthetic legacy A'),(NULL,'same','Synthetic legacy B')"""))
        await session.commit()
    before = await _state(pg_factory)
    await _alembic(pg_factory, tmp_path, "downgrade", "0195",
                   refusal="Duplicate legacy account codes prevent Finance rollback; use the verified release restore")
    assert await _state(pg_factory) == before


async def test_owned_bank_match_concurrent_replay_allocates_once(pg_factory, pg_book):
    org = pg_book[0]
    async with pg_factory() as session:
        tx = BankTransaction(ext_id="SYN-CONCURRENT", amount=100, currency="BYN")
        payment = Payment(organization_id=org, ref="SYN-CONCURRENT", amount=100)
        session.add_all([tx, payment, User(username="tester", full_name="Synthetic bank operator",
                                         role="director", status="active")])
        await session.flush()
        session.add(SourceBinding(organization_id=org, source_type="finance_bank_transaction", source_id=tx.id,
                                  ownership="own", evidence="Synthetic bank evidence", actor="tester"))
        await session.commit()
        tx_id, payment_id = tx.id, payment.id
    core = SimpleNamespace(services=SimpleNamespace(accounting=AccountingService()), event_bus=OutboxEventBus())
    user = CurrentUser("tester", ["director"])
    pids = set()

    async def writer():
        async with pg_factory() as session:
            pids.add(await session.scalar(text("SELECT pg_backend_pid()")))
            try:
                result = await match_bank_transaction(tx_id=tx_id, payload=BankManualMatch(payment_id=payment_id),
                    organization_id=org, core=core, session=session, user=user)
                assert result["payment_id"] == payment_id
                return 200
            except HTTPException as exc:
                await session.rollback()
                return exc.status_code

    tasks = []
    try:
        async with pg_factory() as blocker:
            await blocker.execute(text("SELECT id FROM accounting.organization WHERE id=:org FOR UPDATE"), {"org": org})
            tasks = [asyncio.create_task(writer()) for _ in range(2)]
            try:
                for _ in range(60):
                    async with pg_factory() as observer:
                        waiting = set((await observer.scalars(text("""
                            SELECT pid FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'
                        """))).all())
                    if len(pids) == 2 and pids <= waiting:
                        break
                    await asyncio.sleep(0.05)
                else:
                    pytest.fail("Both independent bank match sessions must wait on the actual book lock")
            finally:
                await blocker.rollback()
            results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=30)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=15)
    assert sorted(results) == [200, 409]
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(PaymentAllocation)) == 1
        assert await session.scalar(select(func.sum(PaymentAllocation.amount))) == 100
        assert await session.scalar(select(func.count()).select_from(OutboxEvent)
            .where(OutboxEvent.event_type.in_(["finance.payment.received", "finance.payment.paid"]))) == 2
        payment = await session.get(Payment, payment_id)
        tx = await session.get(BankTransaction, tx_id)
        assert payment.status == "paid" and payment.organization_id == org
        assert tx.match_status == "manual" and tx.payment_id == payment_id and tx.allocation_id is not None


async def test_pg_factory_finance_ownership_constraints(pg_factory):
    """The current Finance metadata keeps its real constraints after bootstrap."""
    async with pg_factory() as session:
        rows = (await session.execute(text("""
            SELECT relation.relname AS table_name, constraint_row.conname AS name,
                   constraint_row.contype::text AS kind,
                   ARRAY(SELECT attribute.attname::text
                         FROM unnest(constraint_row.conkey) WITH ORDINALITY AS key(attnum, position)
                         JOIN pg_attribute AS attribute
                           ON attribute.attrelid = relation.oid AND attribute.attnum = key.attnum
                         ORDER BY key.position) AS local_columns,
                   target_namespace.nspname AS target_schema, target.relname AS target_table,
                   ARRAY(SELECT attribute.attname::text
                         FROM unnest(constraint_row.confkey) WITH ORDINALITY AS key(attnum, position)
                         JOIN pg_attribute AS attribute
                           ON attribute.attrelid = target.oid AND attribute.attnum = key.attnum
                         ORDER BY key.position) AS target_columns,
                   constraint_row.confdeltype::text AS delete_action,
                   constraint_row.confupdtype::text AS update_action,
                   constraint_row.convalidated AS validated,
                   constraint_row.condeferrable AS deferrable,
                   constraint_row.condeferred AS deferred,
                   pg_get_expr(constraint_row.conbin, relation.oid) AS expression
            FROM pg_constraint AS constraint_row
            JOIN pg_class AS relation ON relation.oid = constraint_row.conrelid
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            LEFT JOIN pg_class AS target ON target.oid = constraint_row.confrelid
            LEFT JOIN pg_namespace AS target_namespace ON target_namespace.oid = target.relnamespace
            WHERE namespace.nspname = 'finance'
              AND relation.relname IN ('bank_account', 'payment', 'payment_allocation', 'bank_transaction')
              AND constraint_row.contype IN ('f', 'u', 'c')
        """))).mappings().all()
    foreign_keys = [row for row in rows if row["kind"] == "f"]
    assert {(row["table_name"], tuple(row["local_columns"]), row["target_schema"],
             row["target_table"], tuple(row["target_columns"]), row["delete_action"])
            for row in foreign_keys} == {
        ("bank_account", ("organization_id",), "accounting", "organization", ("id",), "r"),
        ("payment", ("organization_id",), "accounting", "organization", ("id",), "r"),
        ("payment", ("account_id",), "finance", "bank_account", ("id",), "r"),
        ("payment", ("organization_id", "account_id"), "finance", "bank_account", ("organization_id", "id"), "r"),
        ("payment_allocation", ("payment_id",), "finance", "payment", ("id",), "c"),
        ("bank_transaction", ("payment_id",), "finance", "payment", ("id",), "n"),
        ("bank_transaction", ("allocation_id",), "finance", "payment_allocation", ("id",), "n"),
    }
    assert len(foreign_keys) == 7
    assert all(row["validated"] and not row["deferrable"] and not row["deferred"]
               and row["update_action"] == "a" for row in foreign_keys)
    unique = [row for row in rows if row["kind"] == "u" and row["table_name"] == "bank_account"]
    assert {(row["name"], tuple(row["local_columns"])) for row in unique} == {
        ("uq_finance_bank_account_organization_code", ("organization_id", "code")),
        ("uq_finance_bank_account_organization_id", ("organization_id", "id")),
    }
    assert len(unique) == 2
    checks = [row for row in rows if row["kind"] == "c" and row["table_name"] in {"bank_account", "payment"}]
    assert {(row["table_name"], row["name"],
             "".join(row["expression"].translate(str.maketrans("", "", "()")).split()).lower())
            for row in checks} == {
        ("bank_account", "ck_bank_account_ck_finance_bank_account_organization_positive", "organization_idisnullororganization_id>0"),
        ("payment", "ck_payment_ck_finance_payment_organization_positive", "organization_idisnullororganization_id>0"),
    }
    assert len(checks) == 2
    assert all(row["validated"] and not row["deferrable"] and not row["deferred"] for row in unique + checks)
