"""Explicit disposable-cluster proof; uses the installed application dependencies.

Run from the candidate root:
    CRM_REL_001_G03_ACCEPTANCE=1 CRM_REL_001_G03_POSTGRES_URL=<isolated URL> \
        python tests/integration/crm_rel_001_migration_proof.py

Requires the dedicated local role/database below and a fresh cluster. Never
uses AIOS_DATABASE_URL, testcontainers, ORM create_all, stamp, or a live database.
The standalone runner needs no pytest installation and never skips a case.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
HEAD = "crm_rel_001_joint_01"
PARENTS = ("0192", "crm_live_deal_task_fidelity_01")
ROLE = "crm_rel_001_g03"
ADMIN_DATABASE = "crm_rel_001_g03_admin"
PREFIX = "crm_rel_001_g03_"


def selected_url():
    value = os.environ.get("CRM_REL_001_G03_POSTGRES_URL", "")
    if os.environ.get("CRM_REL_001_G03_ACCEPTANCE") != "1" or not value:
        raise ValueError("Explicit CRM_REL_001_G03_ACCEPTANCE=1 and disposable URL required")
    url = make_url(value)
    if not (
        url.drivername == "postgresql+psycopg"
        and url.host in {"127.0.0.1", "localhost"}
        and url.port is not None
        and url.username == ROLE
        and url.database == ADMIN_DATABASE
        and not url.query
    ):
        raise ValueError("Refusing a target outside the dedicated local G03 role/database")
    return url


def connect(url):
    return psycopg.connect(
        url.set(drivername="postgresql").render_as_string(hide_password=False),
        autocommit=True,
        connect_timeout=10,
    )


def upgrade(url, revision):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=ROOT,
        env={
            **os.environ,
            "AIOS_ENVIRONMENT": "dev",
            "AIOS_DATABASE_URL": url.render_as_string(hide_password=False),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        text=True,
        capture_output=True,
        timeout=300,
    )
    if result.returncode:
        detail = result.stderr[-3000:]
        if url.password:
            detail = detail.replace(url.password, "<redacted>")
        raise RuntimeError(f"Alembic upgrade {revision} failed: {detail}")


def revision(connection):
    return [row[0] for row in connection.execute("SELECT version_num FROM alembic_version")]


def seed(connection, rich):
    deal = connection.execute(
        "INSERT INTO sales.deal (number, title, counterparty, amount) "
        "VALUES ('CRM-REL-001-G03', 'Synthetic G03 deal', 'Synthetic only', 123.45) RETURNING id"
    ).fetchone()[0]
    task = connection.execute(
        "INSERT INTO sales.deal_task (deal_id, title) VALUES (%s, 'Synthetic G03 task') RETURNING id",
        (deal,),
    ).fetchone()[0]
    rows = {"sales.deal": [deal], "sales.deal_task": [task]}
    if rich:
        connection.execute(
            "UPDATE sales.deal_task SET description='[b]G03[/b]', description_in_bbcode=true, "
            "source_responsible_id='42', source_status_code='2', source_ref='g03:bound' WHERE id=%s",
            (task,),
        )
        unbound = connection.execute(
            "INSERT INTO sales.deal_task (title, source_ref, description) "
            "VALUES ('Synthetic unbound task', 'g03:unbound', 'Preserve unbound task') RETURNING id"
        ).fetchone()[0]
        rows["sales.deal_task"].append(unbound)
        rows["sales.deal_task_crm_link"] = []
        for task_id, ordinal, raw, kind, source, deal_id in (
            (task, 0, f"D_{deal}", "deal", str(deal), deal),
            (task, 1, "L_42", "lead", "42", None),
            (unbound, 0, "L_43", "lead", "43", None),
        ):
            link = connection.execute(
                "INSERT INTO sales.deal_task_crm_link "
                "(task_id, ordinal, raw_binding, entity_type, source_id, deal_id) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (task_id, ordinal, raw, kind, source, deal_id),
            ).fetchone()[0]
            rows["sales.deal_task_crm_link"].append(link)
    if connection.execute("SELECT to_regclass('accounting.organization')").fetchone()[0]:
        org = connection.execute(
            "INSERT INTO accounting.organization (name, unp, generation) "
            "VALUES ('Synthetic G03 organization', '999999999', 1) RETURNING id"
        ).fetchone()[0]
        rows["accounting.organization"] = [org]
    return rows


def snapshot(connection, rows):
    data = {}
    for table, identities in rows.items():
        schema, name = table.split(".")
        data[table] = connection.execute(
            sql.SQL("SELECT to_jsonb(t) FROM {} t WHERE id = ANY(%s) ORDER BY id").format(
                sql.Identifier(schema, name)
            ),
            (identities,),
        ).fetchall()
        assert len(data[table]) == len(identities), f"Missing fixture rows in {table}"
    return data


def constraints(connection, tables):
    return set(connection.execute(
        "SELECT n.nspname, t.relname, c.conname, pg_get_constraintdef(c.oid) "
        "FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid "
        "JOIN pg_namespace n ON n.oid=t.relnamespace "
        "WHERE n.nspname||'.'||t.relname = ANY(%s)",
        (list(tables),),
    ).fetchall())


def rejected(connection, statement, params, state):
    try:
        with connection.transaction():
            connection.execute(statement, params)
            raise AssertionError("Database guard accepted an invalid synthetic row")
    except psycopg.Error as error:
        assert error.sqlstate == state, f"Wrong guard: expected {state}, got {error.sqlstate}"


def joint_guards(connection, rows):
    task = rows["sales.deal_task"][0]
    deal = rows["sales.deal"][0]
    assert connection.execute(
        "SELECT amount::text FROM sales.deal WHERE id=%s", (deal,)
    ).fetchone()[0] == "123.45"
    assert connection.execute(
        "SELECT count(*) FROM sales.deal_task_crm_link WHERE task_id=%s AND ordinal=0", (task,)
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT deal_id FROM sales.deal_task_crm_link WHERE task_id=%s AND ordinal=0", (task,)
    ).fetchone()[0] == deal
    rejected(connection,
             "INSERT INTO sales.deal_task_crm_link (task_id, ordinal) VALUES (%s, 0)",
             (task,), "23505")
    rejected(connection,
             "INSERT INTO sales.deal_task_crm_link (task_id, ordinal) VALUES (-1, 0)",
             (), "23503")
    guard_task = connection.execute(
        "INSERT INTO sales.deal_task (title, source_ref) "
        "VALUES ('G03 nullable guard', 'g03:guard') RETURNING id"
    ).fetchone()[0]
    rows["sales.deal_task"].append(guard_task)
    rejected(connection,
             "INSERT INTO sales.deal_task (title, source_ref) VALUES ('G03 duplicate', 'g03:guard')",
             (), "23505")
    assert connection.execute(
        "SELECT to_regclass('accounting.inbound_vat_correction_workpaper')"
    ).fetchone()[0] is not None
    if "accounting.organization" not in rows:
        org = connection.execute(
            "INSERT INTO accounting.organization (name, unp, generation) "
            "VALUES ('Synthetic G03 organization', '999999999', 1) RETURNING id"
        ).fetchone()[0]
        rows["accounting.organization"] = [org]
    rejected(connection,
             "INSERT INTO accounting.organization (name, unp, generation) "
             "VALUES ('G03 duplicate', '999999999', 1)", (), "23505")
    rejected(connection, "TRUNCATE accounting.inbound_vat_correction_workpaper", (), "P0001")
    rows["sales.deal_task_crm_link"] = [row[0] for row in connection.execute(
        "SELECT id FROM sales.deal_task_crm_link WHERE task_id=ANY(%s) ORDER BY id",
        (rows["sales.deal_task"],),
    )]


def run_case(admin, url, start):
    label = start or "empty"
    database = PREFIX + uuid4().hex
    marker = "crm-rel-001-g03:" + database
    print(json.dumps({"case": label, "status": "started"}), flush=True)
    existing = {row[0] for row in admin.execute("SELECT datname FROM pg_database WHERE NOT datistemplate")}
    assert existing == {"postgres", ADMIN_DATABASE}, "Refusing a cluster containing other databases"
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    admin.execute(sql.SQL("COMMENT ON DATABASE {} IS {}").format(
        sql.Identifier(database), sql.Literal(marker)
    ))
    case_url = url.set(database=database)
    try:
        with connect(case_url) as connection:
            assert connection.execute(
                "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE c.relkind IN ('r', 'p') AND n.nspname NOT LIKE 'pg_%' "
                "AND n.nspname <> 'information_schema'"
            ).fetchone()[0] == 0
        rows, before, old_constraints = {}, {}, set()
        if start:
            upgrade(case_url, start)
            with connect(case_url) as connection:
                assert revision(connection) == [start]
                rows = seed(connection, rich=start == PARENTS[1])
                before = snapshot(connection, rows)
                old_constraints = constraints(connection, rows)
        upgrade(case_url, HEAD)
        with connect(case_url) as connection:
            assert revision(connection) == [HEAD]
            if not start:
                rows = seed(connection, rich=True)
            after = snapshot(connection, rows)
            for table, originals in before.items():
                for original, current in zip(originals, after[table], strict=True):
                    assert all(current[0][key] == value for key, value in original[0].items()), table
            assert old_constraints <= constraints(connection, rows), "Existing constraints changed"
            joint_guards(connection, rows)
            stable = snapshot(connection, rows)
            stable_constraints = constraints(connection, rows)
        upgrade(case_url, HEAD)
        with connect(case_url) as connection:
            assert revision(connection) == [HEAD]
            assert snapshot(connection, rows) == stable, "Repeated upgrade changed fixture data"
            assert constraints(connection, rows) == stable_constraints
        result = {
            "case": label, "status": "passed", "head": HEAD,
            "fixture_rows": {table: len(ids) for table, ids in rows.items()},
            "preserved_constraints": len(old_constraints),
            "joint_constraints": len(stable_constraints), "repeat_upgrade": "passed",
            "fixture_sha256": hashlib.sha256(
                json.dumps(stable, sort_keys=True).encode()
            ).hexdigest(),
        }
    finally:
        identity = admin.execute(
            "SELECT pg_get_userbyid(datdba), shobj_description(oid, 'pg_database') "
            "FROM pg_database WHERE datname=%s", (database,),
        ).fetchone()
        assert identity == (ROLE, marker), "Refusing cleanup of an unowned database"
        admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))
    result["cleanup"] = "passed"
    print(json.dumps(result), flush=True)
    return result


def main():
    if not __debug__:
        raise ValueError("Proof requires Python assertions enabled")
    url = selected_url()
    with connect(url) as admin:
        assert admin.execute("SELECT current_database(), current_user").fetchone() == (
            ADMIN_DATABASE, ROLE
        )
        cases = [run_case(admin, url, start) for start in (None, *PARENTS)]
        version = admin.execute("SHOW server_version").fetchone()[0]
    migration_hash = hashlib.sha256()
    for path in sorted((ROOT / "migrations" / "versions").glob("*.py")):
        migration_hash.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    print(json.dumps({
        "status": "passed", "head": HEAD, "parents": PARENTS,
        "postgres_version": version, "cases": cases,
        "migrations_sha256": migration_hash.hexdigest(),
        "proof_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "downgrade": "not claimed; release recovery requires the G06 restore proof",
    }), flush=True)


if __name__ == "__main__":
    main()
