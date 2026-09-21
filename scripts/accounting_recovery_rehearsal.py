#!/usr/bin/env python3
"""Local-only PostgreSQL dump/restore rehearsal for the current Alembic head.

The runner deliberately accepts only an already-local Docker image.  Every
database, credential, container and port is generated for one invocation, and
cleanup refuses to touch anything outside that generated namespace.
"""
from __future__ import annotations

import argparse
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parent.parent
RESOURCE_PREFIX = "crm_acc_recovery_"
DATABASE_PREFIX = "crm_acc_recovery_"
HEAD_RE = re.compile(r"^([A-Za-z0-9_]+) \(head\)$", re.MULTILINE)


class RehearsalError(RuntimeError):
    """A fail-closed recovery rehearsal failure."""


def _redact(text: str, secret: str) -> str:
    return text.replace(secret, "[REDACTED]")


def _run(label: str, args: list[str], *, timeout: int = 60,
         env: dict[str, str] | None = None, expect_success: bool | None = True,
         secret: str = "") -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            args,
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RehearsalError(f"{label}: required executable is unavailable") from exc
    except subprocess.TimeoutExpired as exc:
        raise RehearsalError(f"{label}: timed out after {timeout}s") from exc
    if expect_success is not None and (result.returncode == 0) != expect_success:
        detail = (result.stderr or result.stdout).strip()[-1000:]
        raise RehearsalError(f"{label}: unexpected exit status {result.returncode}: {_redact(detail, secret)}")
    return result


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _assert_generated(name: str, prefix: str) -> None:
    if not name.startswith(prefix) or not re.fullmatch(r"[a-z0-9_]+", name):
        raise RehearsalError("generated resource name failed safety validation")


def _alembic_head(python: list[str], env: dict[str, str], secret: str) -> str:
    result = _run("read Alembic head", [*python, "-m", "alembic", "heads"], env=env, secret=secret)
    heads = HEAD_RE.findall(result.stdout)
    if len(heads) != 1:
        raise RehearsalError("expected exactly one Alembic head")
    return heads[0]


def _psql(container: str, user: str, database: str, sql: str, *, secret: str,
          expect_success: bool = True) -> subprocess.CompletedProcess[str]:
    return _run(
        "container psql",
        ["docker", "exec", container, "psql", "-v", "ON_ERROR_STOP=1", "-U", user, "-d", database, "-c", sql],
        timeout=60,
        expect_success=expect_success,
        secret=secret,
    )


def _cleanup_database(container: str, user: str, database: str, password: str) -> None:
    _assert_generated(database, DATABASE_PREFIX)
    _run(
        "drop generated database",
        ["docker", "exec", container, "dropdb", "--if-exists", "--force", "-U", user, database],
        secret=password,
    )
    check = _psql(container, user, "postgres", f"SELECT count(*) FROM pg_database WHERE datname = '{database}'", secret=password)
    # psql formatting differs slightly by image version; accept only a standalone zero.
    if not re.search(r"(?m)^\s*0\s*$", check.stdout):
        raise RehearsalError(f"generated database cleanup was not verified: {database}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a local-only accounting PostgreSQL recovery rehearsal")
    parser.add_argument("--image", required=True, help="already-present local PostgreSQL Docker image")
    args = parser.parse_args(argv)

    token = uuid.uuid4().hex
    container = f"{RESOURCE_PREFIX}{token}"
    source_db = f"{DATABASE_PREFIX}src_{token}"
    restored_db = f"{DATABASE_PREFIX}dst_{token}"
    user = f"rehearsal_{token[:12]}"
    password = secrets.token_hex(24)
    port = _free_loopback_port()
    dump_path = f"/tmp/accounting-recovery-{token}.dump"
    for name, prefix in ((container, RESOURCE_PREFIX), (source_db, DATABASE_PREFIX), (restored_db, DATABASE_PREFIX)):
        _assert_generated(name, prefix)

    python = ["py", "-3"] if os.name == "nt" else [sys.executable]
    source_url = f"postgresql+psycopg://{user}:{quote(password, safe='')}@127.0.0.1:{port}/{source_db}"
    migration_env = os.environ.copy()
    migration_env["AIOS_DATABASE_URL"] = source_url
    migration_env["AIOS_ENVIRONMENT"] = "dev"
    migration_env.pop("DATABASE_URL", None)

    container_started = False
    container_claimed = False
    source_created = False
    restored_created = False
    cleanup_errors: list[str] = []
    try:
        _run("inspect local Docker image", ["docker", "image", "inspect", args.image], secret=password)
        container_claimed = True
        _run(
            "start local PostgreSQL container",
            [
                "docker", "run", "--detach", "--rm", "--pull", "never", "--name", container,
                "--env", f"POSTGRES_USER={user}", "--env", f"POSTGRES_PASSWORD={password}",
                "--env", "POSTGRES_DB=postgres", "--publish", f"127.0.0.1:{port}:5432", args.image,
            ],
            secret=password,
        )
        container_started = True

        deadline = time.monotonic() + 60
        while True:
            ready = _run(
                "wait for local PostgreSQL",
                ["docker", "exec", container, "pg_isready", "-U", user, "-d", "postgres"],
                timeout=10,
                expect_success=None,
                secret=password,
            )
            if ready.returncode == 0:
                break
            if time.monotonic() >= deadline:
                raise RehearsalError("local PostgreSQL did not become ready within 60s")
            time.sleep(1)

        _run("create generated source database", ["docker", "exec", container, "createdb", "-U", user, source_db], secret=password)
        source_created = True
        expected_head = _alembic_head(python, migration_env, password)
        _run("upgrade generated source database", [*python, "-m", "alembic", "upgrade", "head"], timeout=180, env=migration_env, secret=password)

        receipt_key = str(uuid.uuid4())
        digest_a, digest_b, command_digest, receipt_digest = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)
        seed_sql = f"""
WITH organization AS (
  INSERT INTO accounting.organization (name, unp, generation)
  VALUES ('Synthetic recovery rehearsal {token[:12]}', '999999999', 0)
  RETURNING id
)
INSERT INTO accounting.reconciliation_receipt (
  organization_id, request_key, period_from, period_to, left_digest, right_digest,
  left_status, right_status, left_pending_documents, right_pending_documents,
  left_rows, right_rows, difference_count, command_digest, evidence, snapshot, digest, actor
)
SELECT id, '{receipt_key}', DATE '2026-01-01', DATE '2026-01-31', '{digest_a}', '{digest_b}',
       'closed_periods', 'closed_periods', 0, 0, 0, 0, 0, '{command_digest}',
       'Synthetic local recovery rehearsal evidence', '{{"scope":"synthetic_recovery_rehearsal"}}'::jsonb,
       '{receipt_digest}', 'rehearsal'
FROM organization;
"""
        _psql(container, user, source_db, seed_sql, secret=password)
        _run("dump generated source database", ["docker", "exec", container, "pg_dump", "-Fc", "-U", user, "-d", source_db, "-f", dump_path], timeout=120, secret=password)
        _run("create generated restored database", ["docker", "exec", container, "createdb", "-U", user, restored_db], secret=password)
        restored_created = True
        _run("restore generated database", ["docker", "exec", container, "pg_restore", "--exit-on-error", "-U", user, "-d", restored_db, dump_path], timeout=180, secret=password)

        restored_head = _psql(container, user, restored_db, "SELECT version_num FROM alembic_version", secret=password)
        if expected_head not in restored_head.stdout:
            raise RehearsalError("restored Alembic version does not match the dynamically discovered head")
        count = _psql(container, user, restored_db, "SELECT count(*) FROM accounting.reconciliation_receipt", secret=password)
        if not re.search(r"(?m)^\s*1\s*$", count.stdout):
            raise RehearsalError("restored database does not contain exactly one reconciliation receipt")
        immutable_rejection = _psql(
            container,
            user,
            restored_db,
            "UPDATE accounting.reconciliation_receipt SET actor = 'forged'",
            secret=password,
            expect_success=False,
        )
        if "Reconciliation receipts are immutable" not in (immutable_rejection.stdout + immutable_rejection.stderr):
            raise RehearsalError("receipt update was rejected without the immutable reconciliation guard signal")
        print(f"recovery rehearsal passed: alembic_head={expected_head}; reconciliation_receipts=1")
        return 0
    except RehearsalError as exc:
        print(f"recovery rehearsal failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if container_started:
            for database, created in ((restored_db, restored_created), (source_db, source_created)):
                if not created:
                    continue
                try:
                    _cleanup_database(container, user, database, password)
                except RehearsalError as exc:
                    cleanup_errors.append(str(exc))
        if container_claimed:
            try:
                exists = _run(
                    "inspect generated container for cleanup",
                    ["docker", "container", "inspect", container],
                    expect_success=None,
                    secret=password,
                )
                if exists.returncode == 0:
                    _run("remove generated container", ["docker", "rm", "--force", container], secret=password)
                    _run("verify generated container removal", ["docker", "container", "inspect", container], expect_success=False, secret=password)
                elif exists.returncode != 1:
                    raise RehearsalError("generated container cleanup could not be verified")
            except RehearsalError as exc:
                cleanup_errors.append(str(exc))
        if cleanup_errors:
            print("recovery rehearsal cleanup failed: " + "; ".join(cleanup_errors), file=sys.stderr)
            return 1
        if container_started:
            print("cleanup evidence: generated source database removed; generated restored database removed; generated container removed")


if __name__ == "__main__":
    raise SystemExit(main())
