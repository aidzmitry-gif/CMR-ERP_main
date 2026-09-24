#!/usr/bin/env python3
"""Rehearse a populated 0116 -> current-head upgrade in a fresh local PostgreSQL.

The script creates its own loopback-only cluster with synthetic data, checks
legacy rows, dumps/restores the upgraded database, and removes that cluster.
It never accepts a database URL or touches an existing PostgreSQL instance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
TEMP_ROOT = Path(tempfile.gettempdir()).resolve()
PREFIX = "crm_acc_0116_to_head_"
DATABASE = "crm_acc_synthetic"
RESTORED_DATABASE = "crm_acc_restored"


def run(args: list[str], *, env: dict[str, str] | None = None, timeout: int = 600) -> str:
    result = subprocess.run(args, cwd=ROOT, env=env, text=True, capture_output=True,
                            timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"{Path(args[0]).name} failed ({result.returncode}): "
                           f"{(result.stderr or result.stdout)[-1200:]}")
    return result.stdout


def connection(port: int, database: str) -> psycopg.Connection:
    return psycopg.connect(host="127.0.0.1", port=port, user="postgres", dbname=database)


def table_counts(conn: psycopg.Connection) -> dict[str, int]:
    tables = conn.execute("""
        SELECT schemaname, tablename FROM pg_tables
        WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
        ORDER BY schemaname, tablename
    """).fetchall()
    return {f"{schema}.{table}": conn.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(
        sql.Identifier(schema), sql.Identifier(table))).fetchone()[0]
        for schema, table in tables}


def snapshot(conn: psycopg.Connection) -> dict:
    tables = conn.execute("""
        SELECT schemaname, tablename FROM pg_tables
        WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
        ORDER BY schemaname, tablename
    """).fetchall()
    rows = {}
    for schema, table in tables:
        values = conn.execute(sql.SQL("SELECT row_to_json(t)::text FROM {}.{} t").format(
            sql.Identifier(schema), sql.Identifier(table))).fetchall()
        body = json.dumps(sorted(value[0] for value in values), ensure_ascii=False).encode()
        rows[f"{schema}.{table}"] = (len(values), hashlib.sha256(body).hexdigest())
    triggers = conn.execute("""
        SELECT n.nspname, c.relname, t.tgname, pg_get_triggerdef(t.oid)
        FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE NOT t.tgisinternal ORDER BY 1,2,3
    """).fetchall()
    sequences = conn.execute("""
        SELECT schemaname, sequencename, last_value
        FROM pg_sequences ORDER BY 1,2
    """).fetchall()
    return {"tables": rows, "triggers": triggers, "sequences": sequences}


def seed_legacy(conn: psycopg.Connection) -> dict[str, tuple]:
    counterparty = conn.execute("""
        INSERT INTO counterparty (name, unp)
        VALUES ('Synthetic legacy counterparty', '999999991') RETURNING id
    """).fetchone()[0]
    sku = conn.execute("""
        INSERT INTO sku (code, title) VALUES ('SYNTHETIC-0116', 'Synthetic legacy SKU')
        RETURNING id
    """).fetchone()[0]
    deal = conn.execute("""
        INSERT INTO sales.deal (number, title, counterparty, amount)
        VALUES ('SYNTHETIC-0116', 'Synthetic legacy deal',
                'Synthetic legacy counterparty', 123.45) RETURNING id
    """).fetchone()[0]
    conn.commit()
    return {"counterparty": (counterparty, "Synthetic legacy counterparty", "999999991"),
            "sku": (sku, "SYNTHETIC-0116", "Synthetic legacy SKU"),
            "deal": (deal, "SYNTHETIC-0116", "Synthetic legacy deal",
                     "Synthetic legacy counterparty", "123.45")}


def assert_legacy(conn: psycopg.Connection, expected: dict[str, tuple]) -> None:
    queries = {
        "counterparty": "SELECT id,name,unp FROM counterparty WHERE id=%s",
        "sku": "SELECT id,code,title FROM sku WHERE id=%s",
        "deal": "SELECT id,number,title,counterparty,amount FROM sales.deal WHERE id=%s",
    }
    for name, query in queries.items():
        row = conn.execute(query, (expected[name][0],)).fetchone()
        if row is None or tuple(map(str, row)) != tuple(map(str, expected[name])):
            raise AssertionError(f"legacy {name} changed during migration")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def remove_generated_directory(directory: Path) -> bool:
    resolved = directory.resolve()
    if resolved != directory or resolved.parent != TEMP_ROOT or not resolved.name.startswith(PREFIX):
        raise RuntimeError("refusing to remove a directory outside the generated temp namespace")
    shutil.rmtree(resolved)
    return not resolved.exists()


def rehearse(bin_dir: Path, output: Path) -> dict:
    required = ("initdb.exe", "pg_ctl.exe", "createdb.exe", "pg_dump.exe", "pg_restore.exe")
    if not all((bin_dir / name).is_file() for name in required):
        raise RuntimeError("portable PostgreSQL binaries are incomplete")
    directory = Path(tempfile.mkdtemp(prefix=PREFIX, dir=TEMP_ROOT)).resolve()
    if directory.parent != TEMP_ROOT or not directory.name.startswith(PREFIX):
        raise RuntimeError("generated directory failed safety validation")
    data = directory / "data"
    log = directory / "postgres.log"
    dump = directory / "synthetic.dump"
    port = free_port()
    started = False
    result = {"status": "failed", "baseline": "0116", "port": port,
              "candidate": run(["git", "rev-parse", "HEAD"]).strip(), "cleanup": False,
              "loopback_only": True, "synthetic_fixture": "counterparty, SKU and deal",
              "production_data_tested": False, "server_changed": False}
    try:
        run([str(bin_dir / "initdb.exe"), "-D", str(data), "-U", "postgres",
             "-A", "trust", "-E", "UTF8", "--locale=C", "--no-instructions"])
        # On Windows the server inherits pg_ctl's output handles. Capturing
        # those pipes would keep subprocess.run waiting after pg_ctl exits.
        start = subprocess.run(
            [str(bin_dir / "pg_ctl.exe"), "-D", str(data), "-l", str(log),
             "-o", f"-h 127.0.0.1 -p {port}", "-w", "start"],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=60, check=False,
        )
        if start.returncode:
            started = (data / "postmaster.pid").exists()
            raise RuntimeError(f"pg_ctl start failed ({start.returncode}): "
                               f"{log.read_text(encoding='utf-8', errors='replace')[-800:]}")
        started = True
        run([str(bin_dir / "createdb.exe"), "-h", "127.0.0.1", "-p", str(port),
             "-U", "postgres", DATABASE])
        env = dict(os.environ, AIOS_ENVIRONMENT="dev", AIOS_DATABASE_URL=(
            f"postgresql+psycopg://postgres@127.0.0.1:{port}/{DATABASE}"))
        run([sys.executable, "-m", "alembic", "upgrade", "0116"], env=env)
        with connection(port, DATABASE) as conn:
            if conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] != "0116":
                raise AssertionError("baseline revision is not 0116")
            legacy = seed_legacy(conn)
            before = table_counts(conn)
        run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env)
        with connection(port, DATABASE) as conn:
            head = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            assert_legacy(conn, legacy)
            after = table_counts(conn)
            changed = {name: (count, after.get(name)) for name, count in before.items()
                       if name != "public.alembic_version" and after.get(name) != count}
            if changed:
                raise AssertionError(f"baseline table row counts changed: {changed}")
            original = snapshot(conn)
        run([str(bin_dir / "pg_dump.exe"), "-h", "127.0.0.1", "-p", str(port),
             "-U", "postgres", "-d", DATABASE, "-Fc", "--no-owner", "--no-acl",
             "-f", str(dump)])
        run([str(bin_dir / "createdb.exe"), "-h", "127.0.0.1", "-p", str(port),
             "-U", "postgres", RESTORED_DATABASE])
        run([str(bin_dir / "pg_restore.exe"), "-h", "127.0.0.1", "-p", str(port),
             "-U", "postgres", "-d", RESTORED_DATABASE, "--no-owner", "--no-acl",
             "--exit-on-error", str(dump)])
        with connection(port, RESTORED_DATABASE) as conn:
            if conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] != head:
                raise AssertionError("restored revision changed")
            assert_legacy(conn, legacy)
            restored = snapshot(conn)
        if original != restored:
            raise AssertionError("restored rows, triggers or sequences differ")
        result.update(status="pass", revision=head, baseline_tables=len(before),
                      result_tables=len(original["tables"]), triggers=len(original["triggers"]),
                      sequences=len(original["sequences"]), legacy_rows=len(legacy),
                      dump_sha256=hashlib.sha256(dump.read_bytes()).hexdigest())
    except Exception as exc:
        result["error"] = str(exc)[-1200:]
    finally:
        try:
            if started:
                run([str(bin_dir / "pg_ctl.exe"), "-D", str(data), "-m", "immediate",
                     "-w", "stop"], timeout=60)
                result["cleanup"] = remove_generated_directory(directory)
            elif directory.is_dir():
                result["cleanup"] = remove_generated_directory(directory)
        except Exception as exc:
            result["cleanup_error"] = str(exc)[-600:]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if result["status"] != "pass" or not result["cleanup"]:
        raise RuntimeError(f"rehearsal failed; inspect {output}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin", type=Path, required=True, help="existing portable PostgreSQL bin directory")
    parser.add_argument("--output", type=Path, required=True, help="local JSON receipt")
    args = parser.parse_args()
    print(json.dumps(rehearse(args.bin.resolve(), args.output.resolve()), ensure_ascii=False))


if __name__ == "__main__":
    main()
