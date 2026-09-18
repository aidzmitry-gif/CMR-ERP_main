"""Fail-closed validation for the CRM-QA-001 operational scorecard."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def current_head(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def current_worktree_dirty(root: Path) -> bool | None:
    """Return the actual repository dirty state, or None if Git cannot answer."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def _under_root(root: Path, relative: str) -> Path | None:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _artifact_manifest(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    artifacts = payload.get("inputArtifacts")
    if not isinstance(artifacts, list):
        return {}
    return {
        item["path"]: item
        for item in artifacts
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }


def _load_json_artifact(
    root: Path,
    manifest: dict[str, dict[str, Any]],
    relative: str,
    issues: list[str],
    *,
    required: bool = False,
) -> dict[str, Any] | None:
    item = manifest.get(relative)
    if item is None:
        if required:
            issues.append(f"required input artifact is not fingerprinted: {relative}")
        return None
    path = _under_root(root, relative)
    if path is None or not path.is_file():
        if required:
            issues.append(f"required input artifact is unavailable: {relative}")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(f"input artifact is invalid JSON: {relative}: {exc}")
        return None
    if not isinstance(value, dict):
        issues.append(f"input artifact must be a JSON object: {relative}")
        return None
    return value


def _junit_counts(path: Path, issues: list[str], label: str) -> dict[str, int] | None:
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError) as exc:
        issues.append(f"{label} JUnit is invalid: {exc}")
        return None
    cases = root.findall(".//testcase")
    counts = {
        "tests": len(cases),
        "failed": sum(1 for case in cases if case.find("failure") is not None),
        "errors": sum(1 for case in cases if case.find("error") is not None),
        "skipped": sum(1 for case in cases if case.find("skipped") is not None),
    }
    counts["passed"] = counts["tests"] - counts["failed"] - counts["errors"] - counts["skipped"]
    if counts["tests"] == 0:
        issues.append(f"{label} JUnit contains no test cases")
    return counts


def _compare_counts(
    issues: list[str],
    expected: dict[str, Any],
    actual: dict[str, int],
    label: str,
) -> None:
    for field in ("tests", "passed", "failed", "skipped", "errors"):
        expected_value = expected.get(field, 0) if field in {"errors", "skipped"} else expected.get(field)
        if expected_value != actual[field]:
            issues.append(
                f"{label}.{field}={expected_value!r} does not match evidence {actual[field]}"
            )


def _compare_number(
    issues: list[str],
    expected: Any,
    actual: Any,
    label: str,
    *,
    tolerance: float = 0.011,
) -> None:
    if not isinstance(expected, (int, float)) or not isinstance(actual, (int, float)):
        issues.append(f"{label} is not numeric in scorecard/evidence")
    elif abs(float(expected) - float(actual)) > tolerance:
        issues.append(f"{label}={expected!r} does not match evidence {actual!r}")


def _validate_fingerprinted_evidence(
    payload: dict[str, Any],
    *,
    root: Path,
    manifest: dict[str, dict[str, Any]],
    issues: list[str],
) -> None:
    """Cross-check scorecard claims against the native reports it fingerprints."""
    regression = payload.get("regression") or {}
    coverage = payload.get("coverage") or {}

    junit_pairs = (
        (
            "regression.backendFull",
            regression.get("backendFull") or {},
            ".harness/work/CRM-QA-001.backend-full.marker-fixed.xml",
            ".harness/work/CRM-QA-001.backend-full.marker-fixed-gate.json",
        ),
        (
            "coverage.backendUnit",
            coverage.get("backendUnit") or {},
            ".harness/work/CRM-QA-001.backend-unit.marker-fixed.xml",
            ".harness/work/CRM-QA-001.backend-unit.marker-fixed-gate.json",
        ),
        (
            "regression.backendApi",
            regression.get("backendApi") or {},
            ".harness/work/CRM-QA-001.backend-api.marker-fixed.xml",
            ".harness/work/CRM-QA-001.backend-api.marker-fixed-gate.json",
        ),
        (
            "coverage.frontendVitest",
            (coverage.get("frontendVitest") or {}),
            ".harness/work/CRM-QA-001.frontend-vitest-coverage.xml",
            ".harness/work/CRM-QA-001.frontend-vitest-coverage-gate.json",
        ),
    )
    for label, scorecard_block, junit_relative, gate_relative in junit_pairs:
        junit_item = manifest.get(junit_relative)
        gate_item = manifest.get(gate_relative)
        if junit_item is None and gate_item is None:
            continue
        junit_path = _under_root(root, junit_relative)
        if junit_path is None or not junit_path.is_file():
            issues.append(f"fingerprinted JUnit evidence is unavailable: {junit_relative}")
            continue
        actual = _junit_counts(junit_path, issues, label)
        if actual is None:
            continue
        _compare_counts(issues, scorecard_block, actual, label)
        gate = _load_json_artifact(root, manifest, gate_relative, issues)
        if gate is not None:
            _compare_counts(issues, gate, actual, f"{gate_relative}")

    unit_report_relative = ".harness/work/CRM-QA-001.unit-report.marker-fixed.json"
    if unit_report_relative in manifest:
        unit_report = _load_json_artifact(root, manifest, unit_report_relative, issues)
        totals = (unit_report or {}).get("totals") or {}
        unit = coverage.get("backendUnit") or {}
        _compare_number(
            issues,
            unit.get("linePercent"),
            totals.get("percent_statements_covered"),
            "coverage.backendUnit.linePercent",
        )
        _compare_number(
            issues,
            unit.get("branchPercent"),
            totals.get("percent_branches_covered"),
            "coverage.backendUnit.branchPercent",
        )
        _compare_number(
            issues,
            unit.get("combinedLineBranchPercent"),
            totals.get("percent_covered"),
            "coverage.backendUnit.combinedLineBranchPercent",
        )

    frontend_summary_relative = "frontend/coverage/coverage-summary.json"
    if frontend_summary_relative in manifest:
        frontend_summary = _load_json_artifact(root, manifest, frontend_summary_relative, issues)
        total = (frontend_summary or {}).get("total") or {}
        frontend = coverage.get("frontendVitest") or {}
        for scorecard_key, evidence_key in (
            ("linePercent", "lines"),
            ("statementsPercent", "statements"),
            ("branchPercent", "branches"),
            ("functionsPercent", "functions"),
        ):
            evidence_metric = total.get(evidence_key) or {}
            _compare_number(
                issues,
                frontend.get(scorecard_key),
                evidence_metric.get("pct"),
                f"coverage.frontendVitest.{scorecard_key}",
            )

    inventory_relative = ".harness/work/CRM-QA-001.g03.inventory.json"
    if inventory_relative in manifest:
        inventory = _load_json_artifact(root, manifest, inventory_relative, issues)
        counts = (inventory or {}).get("counts") or {}
        registry = payload.get("registry") or {}
        by_layer = counts.get("byLayer") or {}
        by_size = counts.get("bySize") or {}
        debt = registry.get("classificationDebt") or {}
        expected_pairs = (
            ("registry.totalRecords", registry.get("totalRecords"), counts.get("totalRecords")),
            ("registry.primaryLayers.unit", (registry.get("primaryLayers") or {}).get("unit"), by_layer.get("unit", 0)),
            ("registry.primaryLayers.api", (registry.get("primaryLayers") or {}).get("api"), by_layer.get("api", 0)),
            ("registry.primaryLayers.integration", (registry.get("primaryLayers") or {}).get("integration"), by_layer.get("integration", 0)),
            ("registry.primaryLayers.e2e", (registry.get("primaryLayers") or {}).get("e2e"), by_layer.get("e2e", 0)),
            ("registry.size.Small", (registry.get("size") or {}).get("Small"), by_size.get("Small", 0)),
            ("registry.size.Medium", (registry.get("size") or {}).get("Medium"), by_size.get("Medium", 0)),
            ("registry.size.Large", (registry.get("size") or {}).get("Large"), by_size.get("Large", 0)),
            ("registry.size.unknown", (registry.get("size") or {}).get("unknown"), by_size.get("unknown", 0)),
            ("registry.classificationDebt.unclassifiedDomain", debt.get("unclassifiedDomain"), counts.get("unclassifiedDomainRecords")),
            ("registry.classificationDebt.unclassifiedCuj", debt.get("unclassifiedCuj"), counts.get("unclassifiedCujRecords")),
        )
        for label, expected, actual in expected_pairs:
            if expected != actual:
                issues.append(f"{label}={expected!r} does not match inventory {actual!r}")

    source_relative = ".harness/work/CRM-QA-001.source-snapshot.check.json"
    if source_relative in manifest:
        source = _load_json_artifact(root, manifest, source_relative, issues)
        scorecard_source = (payload.get("repository") or {}).get("sourceSnapshot") or {}
        if source is not None:
            if scorecard_source.get("ok") != source.get("ok"):
                issues.append("repository.sourceSnapshot.ok does not match source-snapshot evidence")
            if scorecard_source.get("mismatchCount") != source.get("mismatchCount"):
                issues.append("repository.sourceSnapshot.mismatchCount does not match source-snapshot evidence")
            actual_mismatches = sorted(
                item.get("path")
                for item in source.get("submodules", [])
                if isinstance(item, dict) and item.get("matchesParentGitlink") is False
            )
            if sorted(scorecard_source.get("mismatchedSubmodules", [])) != actual_mismatches:
                issues.append("repository.sourceSnapshot.mismatchedSubmodules do not match source-snapshot evidence")
            if scorecard_source.get("parentHead") != source.get("parentHead"):
                issues.append("repository.sourceSnapshot.parentHead does not match source-snapshot evidence")


def _validate_proof_artifact(
    root: Path,
    manifest: dict[str, dict[str, Any]],
    relative: str,
    issues: list[str],
    *,
    label: str,
) -> dict[str, Any] | None:
    proof = _load_json_artifact(root, manifest, relative, issues, required=True)
    if proof is None:
        return None
    if proof.get("schemaVersion") != 1:
        issues.append(f"{label} proof schemaVersion must be 1")
    if proof.get("chainId") != "CRM-QA-001":
        issues.append(f"{label} proof chainId is not CRM-QA-001")
    if proof.get("status") != "pass":
        issues.append(f"{label} proof status is not pass")
    return proof


def validate_scorecard(
    scorecard_path: Path,
    *,
    root: Path,
    expected_head: str | None = None,
) -> list[str]:
    issues: list[str] = []
    try:
        payload: dict[str, Any] = json.loads(scorecard_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"scorecard unreadable: {type(exc).__name__}: {exc}"]

    for key in ("schemaVersion", "metricsSchemaVersion", "chainId", "status", "repository", "inputArtifacts"):
        if key not in payload:
            issues.append(f"missing top-level field: {key}")
    if payload.get("chainId") != "CRM-QA-001":
        issues.append("chainId must be CRM-QA-001")
    if payload.get("metricsSchemaVersion") != 2:
        issues.append("metricsSchemaVersion must be 2")
    status = payload.get("status")
    if status not in {"pre-acceptance-blocked", "accepted"}:
        issues.append(f"unsupported scorecard status: {status!r}")

    repository = payload.get("repository") or {}
    recorded_head = repository.get("head")
    actual_head = expected_head if expected_head is not None else current_head(root)
    if not recorded_head:
        issues.append("repository.head is missing")
    elif actual_head is None:
        issues.append("current git HEAD is unavailable")
    elif recorded_head != actual_head:
        issues.append(f"scorecard HEAD {recorded_head} does not match current HEAD {actual_head}")

    backend_unit = ((payload.get("coverage") or {}).get("backendUnit") or {})
    line_percent = backend_unit.get("linePercent")
    if not isinstance(line_percent, (int, float)) or line_percent <= 91:
        issues.append("backend unit line coverage must be greater than 91%")

    regression = payload.get("regression") or {}
    full = regression.get("backendFull") or {}
    api = regression.get("backendApi") or {}
    postgres = ((payload.get("integration") or {}).get("postgres") or {})
    production_alert = ((payload.get("alerting") or {}).get("productionWebhook") or {}).get("status")
    manifest = _artifact_manifest(payload)
    _validate_fingerprinted_evidence(payload, root=root, manifest=manifest, issues=issues)
    if status == "accepted":
        actual_dirty = current_worktree_dirty(root)
        if actual_dirty is None:
            issues.append("accepted scorecard requires an observable git worktree status")
        elif actual_dirty:
            issues.append("accepted scorecard requires the actual git worktree to be clean")
        if repository.get("dirty") is not False:
            issues.append("accepted scorecard requires repository.dirty=false")
        if full.get("failed", 0) or full.get("skipped", 0) or full.get("errors", 0):
            issues.append("accepted scorecard cannot contain failed, skipped or errored full-suite cases")
        if api.get("failed", 0) or api.get("errors", 0):
            issues.append("accepted scorecard cannot contain failed or errored API cases")
        frontend = (payload.get("coverage") or {}).get("frontendVitest") or {}
        if frontend.get("failed", 0) or frontend.get("skipped", 0) or frontend.get("errors", 0):
            issues.append("accepted scorecard cannot contain failed, skipped or errored frontend cases")
        if not isinstance(frontend.get("linePercent"), (int, float)) or frontend.get("linePercent") <= 91:
            issues.append("accepted scorecard requires frontend line coverage greater than 91%")
        debt = ((payload.get("registry") or {}).get("classificationDebt") or {})
        if any(debt.get(key, 0) for key in ("unclassifiedDomain", "unclassifiedCuj", "domainOverlap", "cujOverlap")):
            issues.append("accepted scorecard requires zero classification debt")
        controls = payload.get("controls") or {}
        if controls.get("g03Integrity") != "pass":
            issues.append("accepted scorecard requires an integrity-passing registry")
        if controls.get("g04StrictRegistry") != "pass":
            issues.append("accepted scorecard requires a strict-passing registry")
        if postgres.get("status") != "pass":
            issues.append("accepted scorecard requires a passing Postgres integration status")
        if (
            not isinstance(postgres.get("collected"), int)
            or postgres.get("collected", 0) <= 0
            or postgres.get("executed") != postgres.get("collected")
            or postgres.get("skipped") != 0
            or postgres.get("passed") != postgres.get("executed")
        ):
            issues.append("accepted scorecard requires all collected Postgres cases to execute and pass")
        postgres_proof = postgres.get("proofArtifact")
        if not isinstance(postgres_proof, str) or postgres_proof not in manifest:
            issues.append("accepted scorecard requires a fingerprinted Postgres proof artifact")
        else:
            proof = _validate_proof_artifact(root, manifest, postgres_proof, issues, label="Postgres")
            if proof is not None:
                if proof.get("database") not in {"postgres", "postgresql"}:
                    issues.append("Postgres proof must identify a PostgreSQL database")
                for proof_key, scorecard_key in (
                    ("executedCases", "executed"),
                    ("passedCases", "passed"),
                    ("skippedCases", "skipped"),
                ):
                    if proof.get(proof_key) != postgres.get(scorecard_key):
                        issues.append(f"Postgres proof {proof_key} does not match scorecard {scorecard_key}")
                for proof_key in (
                    "migrationVerified",
                    "rollbackVerified",
                    "idempotencyVerified",
                    "concurrencyVerified",
                ):
                    if proof.get(proof_key) is not True:
                        issues.append(f"Postgres proof requires {proof_key}=true")
        if production_alert != "pass":
            issues.append("accepted scorecard requires externally verified production alert delivery")
        alerting = (payload.get("alerting") or {}).get("productionWebhook") or {}
        alert_proof = alerting.get("proofArtifact")
        if not isinstance(alert_proof, str) or alert_proof not in manifest:
            issues.append("accepted scorecard requires a fingerprinted production alert proof artifact")
        else:
            proof = _validate_proof_artifact(root, manifest, alert_proof, issues, label="production alert")
            if proof is not None:
                if proof.get("deliveryVerified") is not True:
                    issues.append("production alert proof requires deliveryVerified=true")
                if not isinstance(proof.get("receiver"), str) or not proof["receiver"].strip():
                    issues.append("production alert proof requires a receiver")
                if not isinstance(proof.get("deliveredAt"), str) or not proof["deliveredAt"].strip():
                    issues.append("production alert proof requires deliveredAt")
        if repository.get("sourceSnapshot", {}).get("ok") is not True:
            issues.append("accepted scorecard requires a matching source snapshot")

        required_artifacts = {
            ".harness/work/CRM-QA-001.g03.inventory.json",
            ".harness/work/CRM-QA-001.source-snapshot.check.json",
            ".harness/work/CRM-QA-001.backend-full.marker-fixed.xml",
            ".harness/work/CRM-QA-001.backend-full.marker-fixed-gate.json",
            ".harness/work/CRM-QA-001.backend-unit.marker-fixed.xml",
            ".harness/work/CRM-QA-001.backend-unit.marker-fixed-gate.json",
            ".harness/work/CRM-QA-001.unit-report.marker-fixed.json",
            ".harness/work/CRM-QA-001.backend-api.marker-fixed.xml",
            ".harness/work/CRM-QA-001.backend-api.marker-fixed-gate.json",
            ".harness/work/CRM-QA-001.frontend-vitest-coverage.xml",
            ".harness/work/CRM-QA-001.frontend-vitest-coverage-gate.json",
            "frontend/coverage/coverage-summary.json",
            ".harness/work/CRM-QA-001.g04.registry-integrity.json",
            ".harness/work/CRM-QA-001.g04.registry-strict.json",
        }
        for relative in sorted(required_artifacts):
            if relative not in manifest:
                issues.append(f"accepted scorecard is missing required input artifact: {relative}")

    artifacts = payload.get("inputArtifacts")
    if not isinstance(artifacts, list) or not artifacts:
        issues.append("inputArtifacts must be a non-empty list")
    else:
        for item in artifacts:
            relative = item.get("path") if isinstance(item, dict) else None
            if not isinstance(relative, str):
                issues.append("input artifact path is missing")
                continue
            path = _under_root(root, relative)
            if path is None:
                issues.append(f"input artifact escapes repository root: {relative}")
                continue
            if not path.is_file():
                issues.append(f"input artifact is missing: {relative}")
                continue
            if path.stat().st_size != item.get("sizeBytes"):
                issues.append(f"input artifact size mismatch: {relative}")
            if sha256_file(path) != item.get("sha256"):
                issues.append(f"input artifact hash mismatch: {relative}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a CRM-QA-001 operational scorecard")
    parser.add_argument(
        "--scorecard",
        default=".harness/work/CRM-QA-001.scorecard.json",
        help="scorecard path relative to the repository root",
    )
    parser.add_argument("--report", help="optional JSON report path relative to the repository root")
    args = parser.parse_args()
    scorecard_path = _under_root(ROOT, args.scorecard)
    if scorecard_path is None:
        print("SCORECARD FAIL CLOSED: scorecard path escapes repository root")
        return 1
    issues = validate_scorecard(scorecard_path, root=ROOT)
    report = {
        "schemaVersion": 1,
        "scorecard": args.scorecard,
        "scorecardSha256": sha256_file(scorecard_path),
        "scorecardSizeBytes": scorecard_path.stat().st_size,
        "validatedAt": datetime.now(timezone.utc).isoformat(),
        "currentHead": current_head(ROOT),
        "ok": not issues,
        "issues": issues,
    }
    if args.report:
        report_path = _under_root(ROOT, args.report)
        if report_path is None:
            print("SCORECARD FAIL CLOSED: report path escapes repository root")
            return 1
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if issues:
        print("SCORECARD FAIL CLOSED")
        return 1
    print("SCORECARD VALIDATION PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
