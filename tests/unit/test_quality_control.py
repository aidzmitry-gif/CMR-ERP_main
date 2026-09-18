"""Regression tests for the fail-closed Harness quality gates."""

import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUALITY_CONTROL = runpy.run_path(ROOT / "scripts" / "quality" / "quality_control.py")
compare_baseline = QUALITY_CONTROL["compare_baseline"]
validate_bundle = QUALITY_CONTROL["validate_bundle"]
validate_junit = QUALITY_CONTROL["validate_junit"]


def _record(test_id: str, *, size: str = "Small", fingerprint: str = "a") -> dict:
    digest = fingerprint * 64
    return {
        "testId": test_id,
        "platform": "backend",
        "runner": "pytest",
        "sourcePath": "tests/unit/test_example.py",
        "layer": "unit",
        "layers": ["unit"],
        "size": size,
        "domain": "platform",
        "domainCandidates": ["platform"],
        "cuj": "unclassified",
        "cujCandidates": [],
        "sourceSha256": digest,
        "caseFingerprint": digest,
    }


def test_validate_junit_reads_nested_testsuite_cases(tmp_path):
    report_path = tmp_path / "nested.xml"
    report_path.write_text(
        "<testsuites tests='2' failures='1'>"
        "<testsuite tests='2' failures='1'>"
        "<testcase classname='g04' name='pass'/>"
        "<testcase classname='g04' name='fail'><failure/></testcase>"
        "</testsuite></testsuites>",
        encoding="utf-8",
    )

    report = validate_junit(report_path, require_executed=False)

    assert report["tests"] == 2
    assert report["passed"] == 1
    assert report["failed"] == 1
    assert report["ok"] is False


def test_compare_baseline_detects_added_removed_and_changed_records():
    baseline = [_record("test:one")]
    candidate = [_record("test:two", fingerprint="b")]

    comparison = compare_baseline(baseline, candidate)

    assert comparison["added"] == ["test:two"]
    assert comparison["removed"] == ["test:one"]
    assert comparison["hasChanges"] is True


def test_compare_baseline_detects_classification_change():
    comparison = compare_baseline(
        [_record("test:one")],
        [_record("test:one", size="Medium")],
    )

    assert comparison["classificationChanged"] == ["test:one"]
    assert comparison["changed"] == []


def test_validate_bundle_fails_when_a_baseline_test_is_removed(tmp_path):
    baseline_record = _record("test:removed")
    inventory_path = tmp_path / "inventory.json"
    evidence_path = tmp_path / "evidence.json"
    baseline_path = tmp_path / "baseline.json"
    inventory_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "chainId": "CRM-QA-001",
                "nativeSources": {
                    name: {
                        "nativeCollectionAvailable": True,
                        "nativeItemInventory": True,
                    }
                    for name in ("backend", "frontendVitest", "frontendPlaywright")
                },
                "counts": {"totalRecords": 0},
                "records": [],
            }
        ),
        encoding="utf-8",
    )
    evidence_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "commands": [
                    {"id": command_id, "exitCode": 0}
                    for command_id in (
                        "backend-collect-all",
                        "backend-collect-unit",
                        "backend-collect-api",
                        "backend-collect-integration",
                        "frontend-vitest-list",
                        "frontend-playwright-list",
                    )
                ],
                "artifacts": [],
            }
        ),
        encoding="utf-8",
    )
    baseline_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "recordCount": 1,
                "records": [baseline_record],
            }
        ),
        encoding="utf-8",
    )

    report = validate_bundle(
        inventory_path,
        evidence_path,
        baseline_path,
        "integrity",
    )

    assert report["ok"] is False
    assert any("regression baseline drift" in issue for issue in report["issues"])


def test_validate_bundle_accepts_ephemeral_vitest_reproduction_when_worker_count_matches_inventory(tmp_path):
    inventory_path = tmp_path / "inventory.json"
    evidence_path = tmp_path / "evidence.json"
    baseline_path = tmp_path / "baseline.json"
    inventory_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "chainId": "CRM-QA-001",
                "nativeSources": {
                    name: {
                        "nativeCollectionAvailable": True,
                        "nativeItemInventory": True,
                    }
                    for name in ("backend", "frontendVitest", "frontendPlaywright")
                },
                "counts": {"totalRecords": 0, "byRunner": {"vitest": 2}},
                "records": [],
            }
        ),
        encoding="utf-8",
    )
    evidence_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "commands": [
                    {
                        "id": "frontend-vitest-list",
                        "exitCode": 1,
                    },
                    *[
                        {"id": command_id, "exitCode": 0}
                        for command_id in (
                            "backend-collect-all",
                            "backend-collect-unit",
                            "backend-collect-api",
                            "backend-collect-integration",
                            "frontend-playwright-list",
                        )
                    ],
                ],
                "nativeArtifactProvenance": {
                    "frontendVitest": {"workerExitCode": 0, "recordCount": 2}
                },
                "artifacts": [],
            }
        ),
        encoding="utf-8",
    )
    baseline_path.write_text(
        json.dumps({"schemaVersion": 1, "recordCount": 0, "records": []}),
        encoding="utf-8",
    )

    report = validate_bundle(inventory_path, evidence_path, baseline_path, "integrity")

    assert report["ok"] is True
    assert any("2 records" in note for note in report["notes"])
