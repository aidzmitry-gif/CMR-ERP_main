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
SYNTHETIC_ORG_RULE = b"%PDF-1.7\nSynthetic employer rule source for local recovery rehearsal.\n"


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


def _assert_work_schedule_constraints(container: str, user: str, database: str,
                                      password: str, *, present: bool) -> None:
    result = _psql(container, user, database, """
    SELECT conname || '=' ||
           CASE WHEN pg_get_constraintdef(oid) LIKE '%work_schedule%' THEN 'yes' ELSE 'no' END
    FROM pg_constraint
    WHERE conrelid = 'accounting.payroll_evidence_file'::regclass
      AND conname IN ('payroll_evidence_kind', 'payroll_evidence_subject')
    ORDER BY conname
    """, secret=password)
    expected = 'yes' if present else 'no'
    for name in ('payroll_evidence_kind', 'payroll_evidence_subject'):
        if not re.search(rf"(?m)^\s*{name}={expected}\s*$", result.stdout):
            raise RehearsalError(f"{name} did not match the expected work-schedule migration state")


def _assert_reconciliation_blocker(container: str, user: str, database: str,
                                   password: str, *, present: bool) -> None:
    result = _psql(container, user, database, """
    SELECT CASE WHEN pg_get_functiondef(
      'accounting.guard_reconciliation_issue_insert()'::regprocedure
    ) LIKE '%erp_snapshot_mismatch%' THEN 'yes' ELSE 'no' END AS blocker
    """, secret=password)
    expected = "yes" if present else "no"
    if not re.search(rf"(?m)^\s*{expected}\s*$", result.stdout):
        raise RehearsalError("reconciliation guard did not match the expected migration state")


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


async def _store_synthetic_org_rule(url: str, root: Path, organization_id: int) -> tuple[int, str, str, int, str]:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from modules.accounting.models import PayrollEvidenceFile
    from modules.accounting.payroll_evidence_files import PayrollEvidenceFileInput, verify_bytes
    from modules.accounting.payroll_evidence_files import create as save_file
    from modules.accounting.payroll_organization_review import PayrollOrganizationInput
    from modules.accounting.payroll_organization_review import create as review_rules

    engine = create_async_engine(url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            with _payroll_root(root):
                receipt = await save_file(session, organization_id, PayrollEvidenceFileInput(
                    request_key=uuid.uuid4(), kind="payroll_organization_rule",
                    month="2026-10", reference="synthetic-recovery-org-rule",
                    filename="org-rule.pdf",
                    data_url="data:application/pdf;base64," + base64.b64encode(SYNTHETIC_ORG_RULE).decode(),
                    evidence="Synthetic local organization rule recovery evidence",
                ), "rehearsal")
                review = await review_rules(session, organization_id, "2026-10",
                    PayrollOrganizationInput.model_validate({
                        "request_key": str(uuid.uuid4()),
                        "source_file_id": receipt["file_id"],
                        "source_document": receipt["reference"],
                        "facts": [{"code": "period_work_injury_insurance_tariff",
                                   "decision": "unresolved",
                                   "finding": "Synthetic source is not a tariff decision",
                                   "source_locator": "page 1, line 2"}],
                        "evidence": "Synthetic chief read the cited employer source",
                    }), "rehearsal")
                await session.commit()
                row = await session.scalar(select(PayrollEvidenceFile).where(
                    PayrollEvidenceFile.id == receipt["file_id"],
                ))
                if row is None or verify_bytes(row) != SYNTHETIC_ORG_RULE:
                    raise RehearsalError("source employer rule file differs from its receipt")
                return row.id, row.sha256, row.storage_filename, review["review_id"], review["digest"]
    finally:
        await engine.dispose()


async def _check_restored_org_rule(url: str, root: Path, organization_id: int,
                                   review_id: int, expected_digest: str, *, available: bool) -> None:
    from fastapi import HTTPException
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from modules.accounting.models import PayrollOrganizationReview
    from modules.accounting.payroll_organization_review import current_for, result

    engine = create_async_engine(url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = await session.get(PayrollOrganizationReview, review_id)
            if (row is None or row.organization_id != organization_id
                    or result(row)["digest"] != expected_digest):
                raise RehearsalError("restored employer rule review is missing or changed")
            with _payroll_root(root):
                try:
                    current = await current_for(session, organization_id, "2026-10")
                except HTTPException as exc:
                    if not available and exc.status_code == 409:
                        return
                    raise RehearsalError(f"restored employer rule source failed: HTTP {exc.status_code}") from exc
            if not available:
                raise RehearsalError("restored employer rule review accepted unavailable source bytes")
            if current is None or current["review_digest"] != expected_digest:
                raise RehearsalError("restored employer rule review differs from its source")
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a local-only accounting PostgreSQL recovery rehearsal")
    parser.add_argument("--image", required=True, help="already-present local PostgreSQL Docker image")
    parser.add_argument("--check-work-schedule-migration", action="store_true",
                        help="rehearse 0173 downgrade/upgrade and verify both file constraints")
    parser.add_argument("--check-reconciliation-migration", action="store_true",
                        help="rehearse 0174 downgrade/upgrade and verify the ERP mismatch blocker")
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
        if args.check_work_schedule_migration:
            if expected_head not in {"0173", "0174"}:
                raise RehearsalError("work-schedule migration check requires source head 0173 or 0174")
            _assert_work_schedule_constraints(container, user, source_db, password, present=True)
            _run("downgrade generated source database to 0172",
                 [*python, "-m", "alembic", "downgrade", "0172"],
                 timeout=180, env=migration_env, secret=password)
            _assert_work_schedule_constraints(container, user, source_db, password, present=False)
            _run("reapply generated work-schedule migration",
                 [*python, "-m", "alembic", "upgrade", "head"],
                 timeout=180, env=migration_env, secret=password)
            _assert_work_schedule_constraints(container, user, source_db, password, present=True)
        if args.check_reconciliation_migration:
            if expected_head != "0174":
                raise RehearsalError("reconciliation migration check requires source head 0174")
            _assert_reconciliation_blocker(container, user, source_db, password, present=True)
            _run("downgrade generated source database to 0173",
                 [*python, "-m", "alembic", "downgrade", "0173"],
                 timeout=180, env=migration_env, secret=password)
            _assert_reconciliation_blocker(container, user, source_db, password, present=False)
            _run("reapply generated reconciliation migration",
                 [*python, "-m", "alembic", "upgrade", "head"],
                 timeout=180, env=migration_env, secret=password)
            _assert_reconciliation_blocker(container, user, source_db, password, present=True)

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
        _org_file_id, org_file_sha256, org_storage_filename, org_review_id, org_review_digest = (
            asyncio.run(_store_synthetic_org_rule(source_url, source_files, organization_id))
        )
        source_path = source_files / str(organization_id) / storage_filename
        shutil.copytree(source_files, backup_files)
        backup_path = backup_files / str(organization_id) / storage_filename
        org_backup_path = backup_files / str(organization_id) / org_storage_filename
        if (not backup_path.is_file() or hashlib.sha256(backup_path.read_bytes()).hexdigest() != file_sha256
                or source_path.read_bytes() != backup_path.read_bytes()):
            raise RehearsalError("private payroll-file backup is incomplete")
        if (not org_backup_path.is_file()
                or hashlib.sha256(org_backup_path.read_bytes()).hexdigest() != org_file_sha256
                or org_backup_path.read_bytes() != SYNTHETIC_ORG_RULE):
            raise RehearsalError("private employer-rule backup is incomplete")
        _run("dump generated source database", ["docker", "exec", container, "pg_dump", "-Fc", "-U", user, "-d", source_db, "-f", dump_path], timeout=120, secret=password)
        _run("create generated restored database", ["docker", "exec", container, "createdb", "-U", user, restored_db], secret=password)
        restored_created = True
        _run("restore generated database", ["docker", "exec", container, "pg_restore", "--exit-on-error", "-U", user, "-d", restored_db, dump_path], timeout=180, secret=password)

        asyncio.run(_check_restored_policy(restored_url, restored_files, organization_id,
                                            file_id, file_sha256, available=False))
        asyncio.run(_check_restored_org_rule(restored_url, restored_files, organization_id,
                                             org_review_id, org_review_digest, available=False))
        shutil.copytree(backup_files, restored_files, dirs_exist_ok=True)
        asyncio.run(_check_restored_policy(restored_url, restored_files, organization_id,
                                            file_id, file_sha256, available=True))
        asyncio.run(_check_restored_org_rule(restored_url, restored_files, organization_id,
                                             org_review_id, org_review_digest, available=True))
        restored_path = restored_files / str(organization_id) / storage_filename
        restored_path.write_bytes(b"%PDF-1.7\ntampered synthetic file\n")
        asyncio.run(_check_restored_policy(restored_url, restored_files, organization_id,
                                            file_id, file_sha256, available=False))
        shutil.copy2(backup_path, restored_path)
        asyncio.run(_check_restored_policy(restored_url, restored_files, organization_id,
                                            file_id, file_sha256, available=True))
        org_restored_path = restored_files / str(organization_id) / org_storage_filename
        org_restored_path.write_bytes(b"%PDF-1.7\ntampered employer rule file\n")
        asyncio.run(_check_restored_org_rule(restored_url, restored_files, organization_id,
                                             org_review_id, org_review_digest, available=False))
        shutil.copy2(org_backup_path, org_restored_path)
        asyncio.run(_check_restored_org_rule(restored_url, restored_files, organization_id,
                                             org_review_id, org_review_digest, available=True))

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
              "payroll_files=2; organization_rule_reviews=1; database_only_rejected=true; "
              "tamper_rejected=true; paired_restore_verified=true; "
              f"work_schedule_migration_checked={str(args.check_work_schedule_migration).lower()}; "
              f"reconciliation_migration_checked={str(args.check_reconciliation_migration).lower()}")
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
