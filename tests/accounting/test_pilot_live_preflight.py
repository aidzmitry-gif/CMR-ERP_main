"""The optional live pilot gate must compare one declared book to current ERP bytes."""
import hashlib
import json
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from modules.accounting import opening_import, reconciliation, service
from modules.accounting.models import Entry, OpeningImportReceipt, Organization, Period, Policy
from scripts.accounting_pilot_live_preflight import _run, main, verify_live
from scripts.accounting_pilot_preflight import PreflightError, preflight
from tests.accounting.test_pilot_input_preflight import valid_manifest
from tests.accounting.test_reconciliation import snapshot


async def current_packet(tmp_path, db, book):
    org = await db.get(Organization, book[0])
    org.name = "Synthetic LLC"
    org.unp = "123456789"
    db.add(Policy(organization_id=book[0], effective_from=date(2026, 8, 1),
                  reference="order-2026-01", inventory_method="specific",
                  allocation_basis="direct_cost", depreciation_method="straight_line",
                  normative_reference="synthetic pilot policy", normative_verified=True,
                  approved_by="tester"))
    db.add(Period(organization_id=book[0], month="2026-09", closed=True,
                  generation=0, closed_generation=0, evidence={}))
    await db.commit()

    path, manifest = valid_manifest(tmp_path)
    manifest["organization"]["erp_book_id"] = str(book[0])
    manifest["policy"]["effective_from"] = "2026-08-01"
    raw = await reconciliation.erp_snapshot(db, book[0], date(2026, 9, 1), date(2026, 9, 30))
    for kind in ("osv_left", "osv_right"):
        artifact = next(row for row in manifest["artifacts"] if row["kind"] == kind)
        target = tmp_path / artifact["path"]
        target.write_bytes(raw)
        artifact["sha256"] = hashlib.sha256(raw).hexdigest()
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert preflight(path)["osv"]["reconciliation_ready"] is True
    return path, manifest


async def test_live_preflight_matches_book_policy_and_exact_current_osv(tmp_path, db, book):
    path, _ = await current_packet(tmp_path, db, book)
    before = await db.scalar(select(func.count(Entry.id)))
    await db.execute(text("PRAGMA query_only = ON"))
    db.info["accounting_read_only_snapshot"] = True
    try:
        result = await verify_live(db, path)
        assert result["erp_live"] == {
            "organization_id": book[0],
            "book_identity_verified": True,
            "configured_policy_matched": True,
            "opening_import_status": "not_imported",
            "erp_ledger_verified": True,
            "erp_osv_sha256": result["osv"]["right_sha256"],
            "source_provenance_verified": False,
            "cutover_ready": False,
        }
        assert await db.scalar(select(func.count(Entry.id))) == before
    finally:
        db.info.pop("accounting_read_only_snapshot", None)
        await db.execute(text("PRAGMA query_only = OFF"))


@pytest.mark.parametrize("mismatch", ["unp", "policy", "osv"])
async def test_live_preflight_rejects_declared_or_current_mismatch(
        tmp_path, db, book, mismatch):
    path, manifest = await current_packet(tmp_path, db, book)
    if mismatch == "unp":
        org = await db.get(Organization, book[0])
        org.unp = "987654321"
        await db.commit()
        expected = "identity differs"
    elif mismatch == "policy":
        db.add(Policy(organization_id=book[0], effective_from=date(2026, 8, 15),
                      reference="another-signed-order", inventory_method="specific",
                      allocation_basis="direct_cost", depreciation_method="straight_line",
                      normative_reference="synthetic later policy", normative_verified=True,
                      approved_by="tester"))
        await db.commit()
        expected = "policy differs"
    else:
        altered = snapshot(status="closed_periods", pending="0")
        for kind in ("osv_left", "osv_right"):
            artifact = next(row for row in manifest["artifacts"] if row["kind"] == kind)
            (tmp_path / artifact["path"]).write_bytes(altered)
            artifact["sha256"] = hashlib.sha256(altered).hexdigest()
        path.write_text(json.dumps(manifest), encoding="utf-8")
        expected = "differs from the current ledger"
    assert preflight(path)["ok"] is True
    with pytest.raises(PreflightError, match=expected):
        await verify_live(db, path)


async def test_read_only_snapshot_flag_requires_database_guard(db, book):
    db.info["accounting_read_only_snapshot"] = True
    try:
        with pytest.raises(service.AccountingError, match="query_only"):
            await service.lock_organization(db, book[0])
    finally:
        db.info.pop("accounting_read_only_snapshot", None)


async def test_live_preflight_rejects_an_existing_different_opening_import(
        tmp_path, db, book):
    path, _ = await current_packet(tmp_path, db, book)
    opening = preflight(path)["opening_import"]
    receipt_snapshot = {"organization_id": book[0], "synthetic": True}
    db.add(OpeningImportReceipt(
        organization_id=book[0], request_key=str(uuid4()), batch="other-batch",
        protocol_version="opening-balance-v1", source_system=opening["source_system"],
        source_digest=opening["source_digest"], cutover_date=date(2026, 9, 1),
        entry_count=opening["entry_count"], line_count=opening["line_count"],
        debit_total=Decimal("100.00"), credit_total=Decimal("100.00"),
        command_digest="f" * 64, evidence="Synthetic different accepted package",
        entry_ids=[1], snapshot=receipt_snapshot,
        digest=opening_import._digest(receipt_snapshot), actor="tester",
    ))
    await db.commit()
    with pytest.raises(PreflightError, match="Accepted opening import differs"):
        await verify_live(db, path)


def test_live_cli_requires_explicit_environment_variable(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ERP_PILOT_READONLY_URL", raising=False)
    assert main(["--manifest", str(tmp_path / "manifest.json"),
                 "--database-url-env", "ERP_PILOT_READONLY_URL"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert "missing" in result["errors"][0]


async def test_live_runner_rejects_non_postgres_url(tmp_path):
    with pytest.raises(PreflightError, match="async PostgreSQL"):
        await _run(tmp_path / "manifest.json", "sqlite+aiosqlite:///:memory:")
