import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.accounting_pilot_preflight import PreflightError, main, preflight
from tests.accounting.test_reconciliation import snapshot


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def opening_package() -> dict:
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
        "source_digest": "a" * 64,
        "cutover_date": "2026-09-01",
        "evidence": "Synthetic opening-balance reconciliation",
        "expected_entry_count": 1,
        "expected_line_count": 2,
        "expected_debit_byn": "100.00",
        "expected_credit_byn": "100.00",
        "entries": [entry],
    }


def artifact(kind: str, source_id: str, path: Path, *, source_system: str = "control-export") -> dict:
    return {
        "kind": kind,
        "source_system": source_system,
        "source_id": source_id,
        "path": path.name,
        "sha256": digest(path),
        "evidence": f"Synthetic accepted source evidence for {kind}",
    }


def valid_manifest(root: Path) -> tuple[Path, dict]:
    opening = root / "opening.json"
    opening.write_text(json.dumps(opening_package()), encoding="utf-8")
    osv_left = root / "osv-left.csv"
    osv_right = root / "osv-right.csv"
    raw_osv = snapshot(status="closed_periods", pending="0")
    osv_left.write_bytes(raw_osv)
    osv_right.write_bytes(raw_osv)
    artifacts = [
        artifact("opening_balances", "opening-2026-09", opening, source_system="1c-export"),
        artifact("osv_left", "osv-source-2026-09", osv_left),
        artifact("osv_right", "osv-erp-2026-09", osv_right),
    ]
    for kind in ("bank_statement", "inventory", "receivables", "vat", "fx", "primary_documents"):
        path = root / f"{kind}.txt"
        path.write_text(f"synthetic {kind} evidence", encoding="utf-8")
        artifacts.append(artifact(kind, f"{kind}-2026-09", path))
    manifest = {
        "protocol_version": "belarus-pilot-input-v1",
        "pilot": {
            "month": "2026-09",
            "cutover_date": "2026-09-01",
            "authorization_evidence": "Synthetic approved pilot protocol reference",
        },
        "organization": {"external_id": "source-org-42", "name": "Synthetic LLC", "unp": "123456789"},
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
        "artifacts": artifacts,
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, manifest


def test_preflight_validates_complete_package_without_exposing_artifact_contents(tmp_path):
    path, _ = valid_manifest(tmp_path)

    result = preflight(path)

    assert result["ok"] is True
    assert result["artifact_count"] == 9
    assert result["opening_import"]["entry_count"] == 1
    assert result["osv"]["period_from"] == "2026-09-01"
    assert "synthetic bank_statement evidence" not in json.dumps(result)


def test_preflight_rejects_missing_required_artifact(tmp_path):
    path, manifest = valid_manifest(tmp_path)
    manifest["artifacts"] = [row for row in manifest["artifacts"] if row["kind"] != "vat"]
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PreflightError, match="Missing required artifact kinds: vat"):
        preflight(path)


def test_preflight_rejects_tampered_artifact_and_cli_returns_failure(tmp_path, capsys):
    path, _ = valid_manifest(tmp_path)
    (tmp_path / "inventory.txt").write_text("changed after manifest", encoding="utf-8")

    assert main(["--manifest", str(path)]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False
    with pytest.raises(PreflightError, match="Artifact SHA-256 does not match"):
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
