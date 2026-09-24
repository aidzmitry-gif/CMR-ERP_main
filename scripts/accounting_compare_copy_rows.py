"""Compare pre-existing table columns between a restored and migrated DB copy.

The databases must be isolated rehearsal copies. Only counts, hashes and table
names are emitted; source values are never printed or modified.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from decimal import Decimal

import psycopg
from psycopg import sql


def _normalized(value: object) -> object:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"bytea_hex": bytes(value).hex()}
    if isinstance(value, Decimal):
        return {"decimal": str(value)}
    if isinstance(value, dict):
        return {str(key): _normalized(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalized(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _digest(rows: Iterable[tuple[object, ...]]) -> tuple[int, str]:
    normalized = [
        json.dumps(_normalized(row), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        for row in rows
    ]
    normalized.sort()
    digest = hashlib.sha256()
    for row in normalized:
        encoded = row.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return len(normalized), digest.hexdigest()


def _rows(connection: psycopg.Connection, schema: str, table: str, columns: list[str]):
    statement = sql.SQL("SELECT {} FROM {}.{}").format(
        sql.SQL(", ").join(sql.Identifier(column) for column in columns),
        sql.Identifier(schema),
        sql.Identifier(table),
    )
    with connection.cursor() as cursor:
        cursor.execute(statement)
        return cursor.fetchall()


def _columns(connection: psycopg.Connection, schema: str, table: str) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
            (schema, table),
        )
        return [row[0] for row in cursor.fetchall()]


def main() -> None:
    options = "-c default_transaction_read_only=on"
    with (
        psycopg.connect("postgresql://postgres@127.0.0.1:5432/aios_before", options=options)
        as before,
        psycopg.connect("postgresql://postgres@127.0.0.1:5432/aios_copy", options=options)
        as after,
    ):
        with before.cursor() as cursor:
            cursor.execute(
                "SELECT schemaname, tablename FROM pg_tables "
                "WHERE schemaname NOT IN ('pg_catalog','information_schema') "
                "AND tablename <> 'alembic_version' ORDER BY schemaname, tablename"
            )
            tables = cursor.fetchall()
        missing_columns: list[str] = []
        mismatches: list[str] = []
        total_rows = 0
        for schema, table in tables:
            columns = _columns(before, schema, table)
            if not set(columns).issubset(_columns(after, schema, table)):
                missing_columns.append(f"{schema}.{table}")
                continue
            before_count, before_hash = _digest(_rows(before, schema, table, columns))
            after_count, after_hash = _digest(_rows(after, schema, table, columns))
            total_rows += before_count
            if (before_count, before_hash) != (after_count, after_hash):
                mismatches.append(f"{schema}.{table}")
        result = {
            "baseline_tables": len(tables),
            "baseline_rows": total_rows,
            "missing_columns": missing_columns,
            "content_mismatches": mismatches,
            "matched": len(tables) - len(missing_columns) - len(mismatches),
        }
        print(json.dumps(result, sort_keys=True))
        if missing_columns or mismatches:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
