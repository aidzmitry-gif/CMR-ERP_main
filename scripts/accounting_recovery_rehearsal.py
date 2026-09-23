#!/usr/bin/env python3
"""Local-only database and private payroll-file recovery rehearsal.

The runner deliberately accepts only an already-local Docker image.  Every
database, credential, container and port is generated for one invocation, and
cleanup refuses to touch anything outside that generated namespace.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
RESOURCE_PREFIX = "crm_acc_recovery_"
DATABASE_PREFIX = "crm_acc_recovery_"
HEAD_RE = re.compile(r"^([A-Za-z0-9_]+) \(head\)$", re.MULTILINE)
SYNTHETIC_POLICY = b"%PDF-1.7\nSynthetic payroll policy source for local recovery rehearsal.\n"


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


@contextmanager
def _payroll_root(path: Path) -> Iterator[None]:
    previous = os.environ.get("AIOS_PAYROLL_DATA_DIR")
    os.environ["AIOS_PAYROLL_DATA_DIR"] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("AIOS_PAYROLL_DATA_DIR", None)
        else:
            os.environ["AIOS_PAYROLL_DATA_DIR"] = previous


async def _store_synthetic_policy(url: str, root: Path, request_key: str) -> tuple[int, int, str, str]:
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from modules.accounting.models import PayrollEvidenceFile
    from modules.accounting.payroll_evidence_files import (
        PayrollEvidenceFileInput,
        create,
        verify_bytes,
    )

    engine = create_async_engine(url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            organization_id = await session.scalar(text("SELECT id FROM accounting.organization LIMIT 1"))
            if not organization_id:
                raise RehearsalError("generated source organization is missing")
            command = PayrollEvidenceFileInput(
                request_key=request_key,
                kind="payroll_policy",
                reference="synthetic-recovery-policy",
                filename="recovery-policy.pdf",
                data_url="data:application/pdf;base64," + base64.b64encode(SYNTHETIC_POLICY).decode(),
                evidence="Synthetic local recovery rehearsal, no employee data",
            )
            with _payroll_root(root):
                receipt = await create(session, organization_id, command, "rehearsal")
                await session.commit()
                row = await session.scalar(select(PayrollEvidenceFile).where(
                    PayrollEvidenceFile.id == receipt["file_id"],
                ))
                if row is None or verify_bytes(row) != SYNTHETIC_POLICY:
                    raise RehearsalError("source payroll file did not match its database receipt")
                return organization_id, row.id, row.sha256, row.storage_filename
    finally:
        await engine.dispose()


async def _check_restored_policy(url: str, root: Path, organization_id: int, file_id: int,
                                 expected_sha256: str, *, available: bool) -> None:
    from fastapi import HTTPException
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from modules.accounting.models import PayrollEvidenceFile
    from modules.accounting.payroll_evidence_files import result, verify_bytes

    engine = create_async_engine(url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = await session.scalar(select(PayrollEvidenceFile).where(
                PayrollEvidenceFile.id == file_id,
                PayrollEvidenceFile.organization_id == organization_id,
            ))
            if row is None or result(row)["sha256"] != expected_sha256:
                raise RehearsalError("restored payroll file receipt is missing or changed")
            with _payroll_root(root):
                try:
                    raw = verify_bytes(row)
                except HTTPException as exc:
                    if not available and exc.status_code == 409:
                        return
                    raise RehearsalError(f"restored payroll file failed verification: HTTP {exc.status_code}") from exc
            if not available:
                raise RehearsalError("restored database accepted a missing or tampered private file")
            if raw != SYNTHETIC_POLICY or hashlib.sha256(raw).hexdigest() != expected_sha256:
                raise RehearsalError("restored payroll file bytes differ from the synthetic source")
    finally:
        await engine.dispose()


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
    restored_url = f"postgresql+psycopg://{user}:{quote(password, safe='')}@127.0.0.1:{port}/{restored_db}"
    migration_env = os.environ.copy()
    migration_env["AIOS_DATABASE_URL"] = source_url
    migration_env["AIOS_ENVIRONMENT"] = "dev"
    migration_env.pop("DATABASE_URL", None)

    scratch = tempfile.TemporaryDirectory(prefix=RESOURCE_PREFIX)
    scratch_root = Path(scratch.name).resolve()
    if not scratch_root.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise RehearsalError("generated recovery scratch directory escaped the temporary root")
    source_files = scratch_root / "private-source"
    backup_files = scratch_root / "private-backup"
    restored_files = scratch_root / "private-restored"
    for directory in (source_files, restored_files):
        directory.mkdir(mode=0o700)
        if os.name != "nt":
            directory.chmod(0o700)

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
        organization_id, file_id, file_sha256, storage_filename = asyncio.run(
            _store_synthetic_policy(source_url, source_files, str(uuid.uuid4())),
        )
        source_path = source_files / str(organization_id) / storage_filename
        shutil.copytree(source_files, backup_files)
        backup_path = backup_files / str(organization_id) / storage_filename
        if (not backup_path.is_file() or hashlib.sha256(backup_path.read_bytes()).hexdigest() != file_sha256
                or source_path.read_bytes() != backup_path.read_bytes()):
            raise RehearsalError("private payroll-file backup is incomplete")
        _run("dump generated source database", ["docker", "exec", container, "pg_dump", "-Fc", "-U", user, "-d", source_db, "-f", dump_path], timeout=120, secret=password)
        _run("create generated restored database", ["docker", "exec", container, "createdb", "-U", user, restored_db], secret=password)
        restored_created = True
        _run("restore generated database", ["docker", "exec", container, "pg_restore", "--exit-on-error", "-U", user, "-d", restored_db, dump_path], timeout=180, secret=password)

        asyncio.run(_check_restored_policy(restored_url, restored_files, organization_id,
                                            file_id, file_sha256, available=False))
        shutil.copytree(backup_files, restored_files, dirs_exist_ok=True)
        asyncio.run(_check_restored_policy(restored_url, restored_files, organization_id,
                                            file_id, file_sha256, available=True))
        restored_path = restored_files / str(organization_id) / storage_filename
        restored_path.write_bytes(b"%PDF-1.7\ntampered synthetic file\n")
        asyncio.run(_check_restored_policy(restored_url, restored_files, organization_id,
                                            file_id, file_sha256, available=False))
        shutil.copy2(backup_path, restored_path)
        asyncio.run(_check_restored_policy(restored_url, restored_files, organization_id,
                                            file_id, file_sha256, available=True))

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
        print(f"recovery rehearsal passed: alembic_head={expected_head}; reconciliation_receipts=1; "
              "payroll_files=1; database_only_rejected=true; tamper_rejected=true; paired_restore_verified=true")
        return 0
    except RehearsalError as exc:
        print(f"recovery rehearsal failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"recovery rehearsal failed: {_redact(str(exc), password)}", file=sys.stderr)
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
        try:
            scratch.cleanup()
            if scratch_root.exists():
                raise RehearsalError("generated private-file scratch cleanup was not verified")
        except (OSError, RehearsalError) as exc:
            cleanup_errors.append(str(exc))
        if cleanup_errors:
            print("recovery rehearsal cleanup failed: " + "; ".join(cleanup_errors), file=sys.stderr)
            return 1
        if container_started:
            print("cleanup evidence: generated source database removed; generated restored database removed; "
                  "generated container removed; generated private-file scratch removed")


if __name__ == "__main__":
    raise SystemExit(main())
