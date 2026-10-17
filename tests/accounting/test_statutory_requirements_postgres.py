"""PostgreSQL guards for append-only statutory requirements."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.accounting.test_postgres import pg_book as pg_book
from tests.accounting.test_postgres import pg_factory as pg_factory

pytestmark = pytest.mark.integration


async def test_statutory_requirement_history_is_checked_and_immutable(pg_factory, pg_book):
    async with pg_factory() as session:
        async with session.begin():
            warehouse_columns = (await session.execute(text("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema='wms' AND table_name='warehouse_directory'
                  AND column_name IN ('wms_enabled', 'prohibit_negative_stock')
                ORDER BY column_name
            """))).all()
            assert [tuple(row) for row in warehouse_columns] == [
                ("prohibit_negative_stock", "boolean", "NO", "true"),
                ("wms_enabled", "boolean", "NO", "false"),
            ]
            warehouse = (await session.execute(text("""
                SELECT wms_enabled, prohibit_negative_stock FROM wms.warehouse_directory
                WHERE organization_id=:org AND name='warehouse1'
            """), {"org": pg_book[0]})).one()
            assert tuple(warehouse) == (False, True)
            column = (await session.execute(text("""
                SELECT data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema='accounting' AND table_name='policy'
                  AND column_name='document_posting'
            """))).one()
            assert tuple(column) == ("jsonb", "YES", None)
            policy = (await session.execute(text("""
                SELECT document_posting IS NULL FROM accounting.policy
                WHERE id=:policy AND organization_id=:org
            """), {"policy": pg_book[1], "org": pg_book[0]})).one()
            assert tuple(policy) == (True,)
            requirement_id = await session.scalar(text("""
                INSERT INTO accounting.statutory_requirement
                  (organization_id, kind, code, title, effective_from, revision, source_reference, evidence,
                   form_version, electronic_format_version, request_key, request_digest, digest, snapshot, actor)
                VALUES
                  (:org, 'form', 'PAYROLL-REPORT', 'Synthetic form', '2026-10-01', 1,
                   'Synthetic verified source', 'Synthetic documented requirement evidence',
                   '1.0', 'xml-1.0', '00000000-0000-0000-0000-000000000501',
                   :request_digest, :digest, '{}'::jsonb, 'tester')
                RETURNING id
            """), {"org": pg_book[0], "request_digest": "a" * 64, "digest": "b" * 64})

    async with pg_factory() as session:
        with pytest.raises(DBAPIError):
            await session.execute(text("""
                INSERT INTO accounting.statutory_requirement
                  (organization_id, kind, code, title, effective_from, revision, source_reference, evidence,
                   rate_value, rate_unit, rate_basis, request_key, request_digest, digest, snapshot, actor)
                VALUES
                  (:org, 'rate', 'INVALID-RATE', 'Synthetic rate', '2026-10-02', 1,
                   'Synthetic verified source', 'Synthetic documented requirement evidence',
                   0, 'percent', 'synthetic basis', '00000000-0000-0000-0000-000000000502',
                   :request_digest, :digest, '{}'::jsonb, 'tester')
            """), {"org": pg_book[0], "request_digest": "c" * 64, "digest": "d" * 64})
        await session.rollback()

    async with pg_factory() as session:
        with pytest.raises(DBAPIError):
            await session.execute(text("""
                INSERT INTO accounting.statutory_requirement
                  (organization_id, kind, code, title, effective_from, revision, source_reference, evidence,
                   form_version, electronic_format_version, rate_value, rate_unit, rate_basis,
                   request_key, request_digest, digest, snapshot, actor)
                VALUES
                  (:org, 'form', 'MIXED-FORM', 'Synthetic mixed form', '2026-10-01', 1,
                   'Synthetic verified source', 'Synthetic documented requirement evidence',
                   '1.0', 'xml-1.0', 0, 'percent', 'synthetic basis',
                   '00000000-0000-0000-0000-000000000503',
                   :request_digest, :digest, '{}'::jsonb, 'tester')
            """), {"org": pg_book[0], "request_digest": "e" * 64, "digest": "f" * 64})
        await session.rollback()

    for statement in (
        "UPDATE accounting.statutory_requirement SET title='forged' WHERE id=:id",
        "DELETE FROM accounting.statutory_requirement WHERE id=:id",
        "TRUNCATE accounting.statutory_requirement",
    ):
        async with pg_factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(text(statement), {"id": requirement_id})
            await session.rollback()
