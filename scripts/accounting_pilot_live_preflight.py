"""Compare an offline-validated pilot packet with one current, read-only ERP book.

The original file/hash preflight remains independent of database availability.
This optional second gate neither imports balances nor accepts a 1C source.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.accounting import opening_import, reconciliation  # noqa: E402
from modules.accounting.models import OpeningImportReceipt, Organization, Policy  # noqa: E402
from modules.accounting.service import AccountingError  # noqa: E402
from scripts.accounting_pilot_preflight import (  # noqa: E402
    MAX_MANIFEST_BYTES,
    PreflightError,
    _read_json_with_digest,
    _read_structured_artifact,
    _relative_file,
    preflight,
)


def _name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


async def verify_live(session: AsyncSession, manifest_path: Path) -> dict:
    """Fail closed on book, policy, accepted import or current-OSV mismatches."""
    offline = preflight(manifest_path)
    manifest_path = manifest_path.resolve()
    manifest, manifest_sha256 = _read_json_with_digest(
        manifest_path, limit=MAX_MANIFEST_BYTES)
    if manifest_sha256 != offline["manifest_sha256"]:
        raise PreflightError("Pilot manifest changed during live preflight")

    organization_id = int(offline["organization_erp_book_id"])
    organization = await session.get(Organization, organization_id)
    if organization is None:
        raise PreflightError("Declared ERP book does not exist")
    declared = manifest["organization"]
    if organization.unp != declared["unp"] or _name(organization.name) != _name(declared["name"]):
        raise PreflightError("Declared ERP book identity differs from the current organization")

    cutover = date.fromisoformat(offline["pilot"]["cutover_date"])
    policy = await session.scalar(select(Policy).where(
        Policy.organization_id == organization_id,
        Policy.effective_from <= cutover,
    ).order_by(Policy.effective_from.desc()).limit(1))
    declared_policy = manifest["policy"]
    if (policy is None or policy.normative_verified is not True
            or policy.effective_from.isoformat() != declared_policy["effective_from"]
            or policy.reference != declared_policy["order_reference"]):
        raise PreflightError("Current ERP accounting policy differs from the pilot declaration")

    opening = offline["opening_import"]
    receipt = await session.scalar(select(OpeningImportReceipt).where(
        OpeningImportReceipt.organization_id == organization_id,
        OpeningImportReceipt.cutover_date == cutover,
    ))
    import_status = "not_imported"
    if receipt is not None:
        if (not isinstance(receipt.snapshot, dict)
                or receipt.command_digest != opening["command_digest"]
                or receipt.source_digest != opening["source_digest"]
                or receipt.source_system != opening["source_system"]
                or receipt.entry_count != opening["entry_count"]
                or receipt.line_count != opening["line_count"]
                or opening_import._digest(receipt.snapshot) != receipt.digest
                or receipt.snapshot.get("organization_id") != organization_id):
            raise PreflightError("Accepted opening import differs from the pilot package")
        import_status = "matching_receipt"

    right_artifact = next(row for row in manifest["artifacts"] if row["kind"] == "osv_right")
    right_path = _relative_file(manifest_path.parent, right_artifact["path"], "osv_right.path")
    right_raw = _read_structured_artifact(right_path)
    right_sha256 = hashlib.sha256(right_raw).hexdigest()
    if right_sha256 != offline["osv"]["right_sha256"]:
        raise PreflightError("ERP OSV file changed during live preflight")
    start = date.fromisoformat(offline["osv"]["period_from"])
    end = date.fromisoformat(offline["osv"]["period_to"])
    try:
        current_raw = await reconciliation.erp_snapshot(session, organization_id, start, end)
    except (ValueError, AccountingError) as exc:
        raise PreflightError("Current ERP OSV cannot be produced for this book and period") from exc
    if current_raw != right_raw:
        raise PreflightError("ERP OSV file differs from the current ledger export")

    return {
        **offline,
        "erp_live": {
            "organization_id": organization_id,
            "book_identity_verified": True,
            "configured_policy_matched": True,
            "opening_import_status": import_status,
            "erp_ledger_verified": True,
            "erp_osv_sha256": right_sha256,
            "source_provenance_verified": False,
            "cutover_ready": False,
        },
        "next": "Current ERP book and OSV match; source provenance and accountant acceptance remain separate.",
    }


async def _run(manifest_path: Path, database_url: str) -> dict:
    if not database_url.startswith(("postgresql+psycopg://", "postgresql+asyncpg://")):
        raise PreflightError("Live preflight requires an async PostgreSQL URL")
    engine = create_async_engine(database_url, isolation_level="REPEATABLE READ")
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            async with AsyncSession(
                bind=connection, expire_on_commit=False,
                info={"accounting_read_only_snapshot": True},
            ) as session:
                result = await verify_live(session, manifest_path)
            await connection.rollback()
            return result
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--database-url-env", required=True,
                        help="Environment variable containing an async read-only ERP database URL")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.database_url_env):
        raise SystemExit("--database-url-env must name an environment variable")
    database_url = os.environ.get(args.database_url_env)
    if not database_url:
        print(json.dumps({"ok": False, "errors": ["ERP database URL environment variable is missing"]}))
        return 2
    try:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        result = asyncio.run(_run(args.manifest, database_url))
    except PreflightError as exc:
        print(json.dumps({"ok": False, "errors": [str(exc)]}, ensure_ascii=False))
        return 2
    except Exception:
        # Driver diagnostics can contain credentials and private database data.
        print(json.dumps({"ok": False, "errors": ["ERP database read-only check failed"]}))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
