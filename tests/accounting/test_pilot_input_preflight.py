import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.accounting_pilot_preflight import PreflightError, main, preflight
from tests.accounting.test_reconciliation import snapshot


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def opening_package(source_digest: str) -> dict:
    entry = {
        "source": "opening-export-2026-09",
        "source_version": 1,
        "operation": "manual",
        "document_date": "2026-09-01",
        "operation_date": "2026-09-01",
        "posting_date": "2026-09-01",
        "policy_id": 1,
        "rule_version": "manual-v1",
        "explanation": "Synthetic approved control transaction",
        "opening": True,
        "lines": [
            {"account": "51", "side": "debit", "amount": "100.00", "cash_activity": "operating"},
            {"account": "80", "side": "credit", "amount": "100.00"},
        ],
    }
    return {
        "batch": "opening-test",
        "request_key": str(uuid4()),
        "protocol_version": "opening-balance-v1",
        "source_system": "1c-export",
        "source_digest": source_digest,
        "cutover_date": "2026-09-01",
        "evidence": "Synthetic opening-balance reconciliation",
        "expected_entry_count": 1,
        "expected_line_count": 2,
        "expected_debit_byn": "100.00",
        "expected_credit_byn": "100.00",
        "entries": [entry],
    }


SOURCE_CLASS_BY_KIND = {
    "opening_source": "external_system_export",
    "opening_balances": "external_system_export",
    "bank_statement": "bank_statement",
    "inventory": "source_register",
    "receivables": "source_register",
    "vat": "source_register",
    "fx": "official_rate",
    "primary_documents": "primary_document",
    "payroll_register": "external_system_export",
    "payroll_zero_activity": "source_register",
    "osv_left": "external_system_export",
    "osv_right": "erp_control_export",
}


def artifact(
    kind: str,
    source_id: str,
    path: Path,
    *,
    source_system: str = "control-export",
    evidence_role: str = "required_evidence",
    source_class: str | None = None,
) -> dict:
    return {
        "kind": kind,
        "evidence_role": evidence_role,
        "source_class": source_class or SOURCE_CLASS_BY_KIND[kind],
        "source_system": source_system,
        "source_id": source_id,
        "path": path.name,
        "sha256": digest(path),
        "evidence": f"Synthetic accepted source evidence for {kind}",
    }


def valid_manifest(root: Path) -> tuple[Path, dict]:
    source = root / "opening-source.txt"
    source.write_text("synthetic original 1C opening balances export", encoding="utf-8")
    opening = root / "opening.json"
    opening.write_text(json.dumps(opening_package(digest(source))), encoding="utf-8")
    osv_left = root / "osv-left.csv"
    osv_right = root / "osv-right.csv"
    raw_osv = snapshot(status="closed_periods", pending="0")
    osv_left.write_bytes(raw_osv)
    osv_right.write_bytes(raw_osv)
    artifacts = [
        artifact("opening_balances", "opening-2026-09", opening, source_system="1c-export"),
        artifact("opening_source", "opening-source-2026-09", source, source_system="1c-export"),
        artifact("osv_left", "osv-source-2026-09", osv_left, source_system="1c-export"),
        artifact("osv_right", "osv-erp-2026-09", osv_right, source_system="crm-erp"),
    ]
    for kind in ("bank_statement", "inventory", "receivables", "vat", "fx", "primary_documents"):
        path = root / f"{kind}.txt"
        path.write_text(f"synthetic {kind} evidence", encoding="utf-8")
        artifacts.append(artifact(kind, f"{kind}-2026-09", path))
    payroll = root / "payroll-register.txt"
    payroll.write_text("synthetic reviewed external payroll export", encoding="utf-8")
    artifacts.append(artifact(
        "payroll_register", "payroll-2026-09", payroll,
        source_system="external-payroll",
    ))
    manifest = {
        "protocol_version": "belarus-pilot-input-v6",
        "pilot": {
            "month": "2026-09",
            "cutover_date": "2026-09-01",
            "authorization_evidence": "Synthetic approved pilot protocol reference",
        },
        "organization": {"external_id": "source-org-42", "erp_book_id": "1", "name": "Synthetic LLC", "unp": "123456789"},
        "owners": {
            "chief_accountant": "accountant:chief-1",
            "accountant": "accountant:operator-1",
            "bank_operator": "bank:operator-1",
        },
        "policy": {
            "effective_from": "2026-01-01",
            "effective_to": "2026-12-31",
            "revision": "policy-2026-v1",
            "order_reference": "order-2026-01",
            "responsible_id": "accountant:chief-1",
            "evidence": "Synthetic approved accounting policy reference",
        },
        "payroll": {
            "mode": "external_verified_import",
            "source_system": "external-payroll",
            "verified_by": "accountant:chief-1",
            "evidence": "Synthetic chief confirmation of external payroll export",
        },
        "responsibility": {
            area: {
                "owner": "erp" if area in {"sales", "procurement", "inventory"} else "external",
                "source_system": "crm-erp" if area in {"sales", "procurement", "inventory"}
                else "external-payroll" if area == "payroll" else "1c-legacy",
                "evidence": f"Synthetic source-of-truth assignment for {area}",
            }
            for area in (
                "sales", "procurement", "bank", "inventory", "settlements", "vat", "fx",
                "production", "repairs", "fixed_assets", "payroll",
            )
        },
        "artifacts": artifacts,
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, manifest


def test_preflight_validates_complete_package_without_exposing_artifact_contents(tmp_path):
    path, _ = valid_manifest(tmp_path)

    result = preflight(path)

    assert result["ok"] is True
    assert result["manifest_sha256"] == digest(path)
    assert result["organization_erp_book_id"] == "1"
    assert result["artifact_count"] == 11
    assert result["required_artifact_count"] == 11
    assert result["supporting_artifact_count"] == 0
    assert result["opening_import"]["entry_count"] == 1
    assert len(result["opening_import"]["command_digest"]) == 64
    assert result["opening_import"]["source_file_sha256"] == digest(tmp_path / "opening-source.txt")
    assert result["osv"]["period_from"] == "2026-09-01"
    assert result["osv"]["left_source_class"] == "external_system_export"
    assert result["osv"]["left_source_system"] == "1c-export"
    assert result["osv"]["right_source_class"] == "erp_control_export"
    assert result["osv"]["right_source_system"] == "crm-erp"
    assert result["payroll"]["source_contents_verified"] is False
    assert result["payroll"]["statutory_payroll_certified"] is False
    assert result["responsibility"]["operational_ownership_verified"] is False
    assert len(result["responsibility"]["declared_areas"]) == 11
    assert "synthetic bank_statement evidence" not in json.dumps(result)

    rewritten = json.loads(path.read_text(encoding="utf-8"))
    rewritten["responsibility"]["repairs"]["evidence"] = "Different declared responsibility evidence"
    path.write_text(json.dumps(rewritten), encoding="utf-8")
    changed = preflight(path)
    assert changed["manifest_sha256"] == digest(path)
    assert changed["manifest_sha256"] != result["manifest_sha256"]


def test_preflight_rejects_missing_required_artifact(tmp_path):
    path, manifest = valid_manifest(tmp_path)
    manifest["artifacts"] = [row for row in manifest["artifacts"] if row["kind"] != "vat"]
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PreflightError, match="Missing required artifact kinds: vat"):
        preflight(path)


def test_cli_reports_unverified_missing_kind_inventory_without_relaxing_preflight(tmp_path, capsys):
    path, manifest = valid_manifest(tmp_path)
    manifest["artifacts"] = [row for row in manifest["artifacts"] if row["kind"] != "vat"]
    opening = next(row for row in manifest["artifacts"] if row["kind"] == "opening_balances")
    opening["source_class"] = "operational_workbook"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    assert main(["--manifest", str(path)]) == 2

    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert "source_class cannot satisfy required opening_balances" in result["errors"][0]
    assert result["intake"] == {
        "status": "unverified_artifact_kind_inventory",
        "required_artifact_kinds": sorted(SOURCE_CLASS_BY_KIND.keys() - {"payroll_zero_activity"}),
        "declared_candidate_artifact_kinds": sorted(SOURCE_CLASS_BY_KIND.keys() - {"vat", "payroll_zero_activity"}),
        "missing_required_artifact_kinds": ["vat"],
        "payroll_mode_candidate": "external_verified_import",
        "payroll_kind_candidates": ["payroll_register", "payroll_zero_activity"],
    }
    with pytest.raises(PreflightError, match="source_class cannot satisfy required opening_balances"):
        preflight(path)


def test_preflight_rejects_tampered_artifact_and_cli_returns_failure(tmp_path, capsys):
    path, _ = valid_manifest(tmp_path)
    (tmp_path / "inventory.txt").write_text("changed after manifest", encoding="utf-8")

    assert main(["--manifest", str(path)]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False
    with pytest.raises(PreflightError, match="Artifact SHA-256 does not match"):
        preflight(path)


def test_preflight_binds_opening_package_to_attached_source_bytes(tmp_path):
    path, manifest = valid_manifest(tmp_path)
    missing_source = {**manifest, "artifacts": [
        row for row in manifest["artifacts"] if row["kind"] != "opening_source"
    ]}
    path.write_text(json.dumps(missing_source), encoding="utf-8")
    with pytest.raises(PreflightError, match="Missing required artifact kinds: opening_source"):
        preflight(path)

    package_path = tmp_path / "opening.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["source_digest"] = "a" * 64
    package_path.write_text(json.dumps(package), encoding="utf-8")
    opening = next(row for row in manifest["artifacts"] if row["kind"] == "opening_balances")
    opening["sha256"] = digest(package_path)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PreflightError, match="source_digest must match opening source file"):
        preflight(path)

    package["source_digest"] = digest(tmp_path / "opening-source.txt")
    package_path.write_text(json.dumps(package), encoding="utf-8")
    opening["sha256"] = digest(package_path)
    source = next(row for row in manifest["artifacts"] if row["kind"] == "opening_source")
    source["source_system"] = "unrelated-1c-export"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PreflightError, match="source file must match opening package source_system"):
        preflight(path)


def test_preflight_rejects_duplicate_source_identity_and_ineligible_osv(tmp_path):
    path, manifest = valid_manifest(tmp_path)
    manifest["artifacts"][1]["source_system"] = manifest["artifacts"][0]["source_system"]
    manifest["artifacts"][1]["source_id"] = manifest["artifacts"][0]["source_id"]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PreflightError, match="source_system/source_id must be unique"):
        preflight(path)

    path, manifest = valid_manifest(tmp_path)
    invalid = snapshot(status="preliminary", pending="1")
    osv = tmp_path / "osv-right.csv"
    osv.write_bytes(invalid)
    for row in manifest["artifacts"]:
        if row["kind"] == "osv_right":
            row["sha256"] = digest(osv)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PreflightError, match="OSV pair is not eligible"):
        preflight(path)


def test_preflight_rejects_operational_workbook_as_required_primary_evidence(tmp_path):
    path, manifest = valid_manifest(tmp_path)
    row = next(row for row in manifest["artifacts"] if row["kind"] == "primary_documents")
    row["source_class"] = "operational_workbook"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PreflightError, match="source_class cannot satisfy required primary_documents"):
        preflight(path)


def test_preflight_keeps_supporting_calculation_outside_required_evidence(tmp_path):
    path, manifest = valid_manifest(tmp_path)
    calculation = tmp_path / "delivery-calculation.txt"
    calculation.write_text("synthetic delivery calculation", encoding="utf-8")
    manifest["artifacts"].append(artifact(
        "supporting_calculation",
        "delivery-calc-2026-09",
        calculation,
        source_system="operations-sheet",
        evidence_role="supporting_calculation",
        source_class="operational_workbook",
    ))
    path.write_text(json.dumps(manifest), encoding="utf-8")

    result = preflight(path)

    assert result["artifact_count"] == 12
    assert result["required_artifact_count"] == 11
    assert result["supporting_artifact_count"] == 1


def test_preflight_requires_payroll_scope_and_its_matching_source(tmp_path):
    path, manifest = valid_manifest(tmp_path)
    manifest["artifacts"] = [
        row for row in manifest["artifacts"] if row["kind"] != "payroll_register"
    ]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PreflightError, match="Missing required artifact kinds: payroll_register"):
        preflight(path)

    path, manifest = valid_manifest(tmp_path)
    payroll = next(row for row in manifest["artifacts"] if row["kind"] == "payroll_register")
    payroll["source_system"] = "unrelated-export"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PreflightError, match="source_system must match payroll.source_system"):
        preflight(path)

    path, manifest = valid_manifest(tmp_path)
    manifest["payroll"]["verified_by"] = "unknown-accountant"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PreflightError, match="must identify this pilot's accountant"):
        preflight(path)

    path, manifest = valid_manifest(tmp_path)
    payroll_file = tmp_path / "payroll-register.txt"
    payroll_file.write_bytes(b"")
    payroll = next(row for row in manifest["artifacts"] if row["kind"] == "payroll_register")
    payroll["sha256"] = digest(payroll_file)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PreflightError, match="Required artifact file is empty"):
        preflight(path)

    path, manifest = valid_manifest(tmp_path)
    manifest["protocol_version"] = "belarus-pilot-input-v5"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PreflightError, match="belarus-pilot-input-v6"):
        preflight(path)


def test_preflight_requires_distinct_external_and_erp_osv_sources(tmp_path):
    path, manifest = valid_manifest(tmp_path)
    left = next(row for row in manifest["artifacts"] if row["kind"] == "osv_left")
    right = next(row for row in manifest["artifacts"] if row["kind"] == "osv_right")

    left["source_class"] = "erp_control_export"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PreflightError, match="source_class cannot satisfy required osv_left"):
        preflight(path)

    left["source_class"] = "external_system_export"
    right["source_class"] = "external_system_export"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PreflightError, match="source_class cannot satisfy required osv_right"):
        preflight(path)

    right["source_class"] = "erp_control_export"
    right["source_system"] = left["source_system"]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PreflightError, match="OSV sides must declare different source systems"):
        preflight(path)


def test_preflight_binds_osv_pair_to_declared_erp_book(tmp_path):
    path, manifest = valid_manifest(tmp_path)
    manifest["organization"]["erp_book_id"] = "2"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PreflightError, match="OSV organization_id must match"):
        preflight(path)

    manifest["organization"]["erp_book_id"] = "01"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PreflightError, match="positive ERP book ID"):
        preflight(path)

    del manifest["organization"]["erp_book_id"]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PreflightError, match="organization is missing: erp_book_id"):
        preflight(path)


def test_preflight_requires_documented_zero_payroll_activity(tmp_path):
    path, manifest = valid_manifest(tmp_path)
    manifest["payroll"]["mode"] = "no_accruals"
    manifest["payroll"]["source_system"] = "hr-control-register"
    manifest["responsibility"]["payroll"]["owner"] = "not_applicable"
    manifest["responsibility"]["payroll"]["source_system"] = None
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PreflightError, match="contradicts payroll.mode"):
        preflight(path)

    statement = tmp_path / "payroll-zero-activity.txt"
    statement.write_text("synthetic signed zero-accrual control statement", encoding="utf-8")
    manifest["artifacts"] = [
        row for row in manifest["artifacts"] if row["kind"] != "payroll_register"
    ]
    manifest["artifacts"].append(artifact(
        "payroll_zero_activity", "zero-payroll-2026-09", statement,
        source_system="hr-control-register",
    ))
    path.write_text(json.dumps(manifest), encoding="utf-8")
    accepted = preflight(path)
    assert accepted["payroll"]["mode"] == "no_accruals"
    assert accepted["payroll"]["artifact_kind"] == "payroll_zero_activity"
    assert accepted["payroll"]["source_contents_verified"] is False


def test_preflight_requires_every_area_owner_and_payroll_consistency(tmp_path):
    path, manifest = valid_manifest(tmp_path)
    del manifest["responsibility"]["fixed_assets"]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PreflightError, match="responsibility is missing: fixed_assets"):
        preflight(path)

    path, manifest = valid_manifest(tmp_path)
    manifest["responsibility"]["payroll"]["owner"] = "erp"
    manifest["responsibility"]["payroll"]["source_system"] = "crm-erp"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PreflightError, match="responsibility.payroll must match"):
        preflight(path)
