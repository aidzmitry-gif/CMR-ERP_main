from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.quality.scorecard_control import validate_scorecard


def _write_fixture(tmp_path: Path, *, status: str = "pre-acceptance-blocked") -> Path:
    artifact = tmp_path / "evidence.json"
    artifact.write_text('{"ok": true}\n', encoding="utf-8")
    payload = {
        "schemaVersion": 1,
        "metricsSchemaVersion": 2,
        "chainId": "CRM-QA-001",
        "status": status,
        "repository": {
            "head": "abc123",
            "sourceSnapshot": {"ok": status != "accepted"},
        },
        "coverage": {"backendUnit": {"linePercent": 93.44}},
        "regression": {"backendFull": {"failed": 0, "skipped": 0, "errors": 0}},
        "integration": {"postgres": {"status": "pass"}},
        "alerting": {"productionWebhook": {"status": "pass"}},
        "inputArtifacts": [
            {
                "path": "evidence.json",
                "sizeBytes": artifact.stat().st_size,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            }
        ],
    }
    scorecard = tmp_path / "scorecard.json"
    scorecard.write_text(json.dumps(payload), encoding="utf-8")
    return scorecard


def test_scorecard_accepts_fingerprinted_preacceptance_snapshot(tmp_path: Path) -> None:
    scorecard = _write_fixture(tmp_path)
    assert validate_scorecard(scorecard, root=tmp_path, expected_head="abc123") == []


def test_scorecard_rejects_changed_input_artifact(tmp_path: Path) -> None:
    scorecard = _write_fixture(tmp_path)
    artifact = tmp_path / "evidence.json"
    artifact.write_text('{"ok": false}\n', encoding="utf-8")
    issues = validate_scorecard(scorecard, root=tmp_path, expected_head="abc123")
    assert "input artifact size mismatch: evidence.json" in issues
    assert "input artifact hash mismatch: evidence.json" in issues


def test_scorecard_rejects_false_acceptance(tmp_path: Path) -> None:
    scorecard = _write_fixture(tmp_path, status="accepted")
    payload = json.loads(scorecard.read_text(encoding="utf-8"))
    payload["regression"]["backendFull"]["failed"] = 1
    payload["coverage"]["backendUnit"]["linePercent"] = 91
    scorecard.write_text(json.dumps(payload), encoding="utf-8")
    issues = validate_scorecard(scorecard, root=tmp_path, expected_head="abc123")
    assert "accepted scorecard cannot contain failed, skipped or errored full-suite cases" in issues
    assert "backend unit line coverage must be greater than 91%" in issues
    assert "accepted scorecard requires a matching source snapshot" in issues
    assert "accepted scorecard requires repository.dirty=false" in issues
    assert any(
        issue in issues
        for issue in (
            "accepted scorecard requires an observable git worktree status",
            "accepted scorecard requires the actual git worktree to be clean",
        )
    )
    assert "accepted scorecard requires frontend line coverage greater than 91%" in issues
    assert "accepted scorecard requires a fingerprinted Postgres proof artifact" in issues

    proof = tmp_path / "postgres-proof.json"
    proof.write_text(json.dumps({"status": "pass", "chainId": "CRM-QA-001"}), encoding="utf-8")
    payload["integration"]["postgres"] = {
        "status": "pass",
        "collected": 1,
        "executed": 1,
        "passed": 1,
        "skipped": 0,
        "proofArtifact": "postgres-proof.json",
    }
    payload["inputArtifacts"].append(
        {
            "path": "postgres-proof.json",
            "sizeBytes": proof.stat().st_size,
            "sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
        }
    )
    scorecard.write_text(json.dumps(payload), encoding="utf-8")
    proof_issues = validate_scorecard(scorecard, root=tmp_path, expected_head="abc123")
    assert "Postgres proof schemaVersion must be 1" in proof_issues


def test_scorecard_rejects_junit_claim_that_does_not_match_fingerprinted_report(tmp_path: Path) -> None:
    scorecard = _write_fixture(tmp_path)
    work = tmp_path / ".harness" / "work"
    work.mkdir(parents=True)
    junit = work / "CRM-QA-001.backend-full.marker-fixed.xml"
    junit.write_text(
        '<testsuite name="pytest"><testcase classname="demo" name="ok" /></testsuite>\n',
        encoding="utf-8",
    )
    gate = work / "CRM-QA-001.backend-full.marker-fixed-gate.json"
    gate.write_text(
        json.dumps({"tests": 1, "passed": 1, "failed": 0, "skipped": 0, "errors": 0}),
        encoding="utf-8",
    )
    payload = json.loads(scorecard.read_text(encoding="utf-8"))
    payload["regression"]["backendFull"] = {"tests": 2, "passed": 2, "failed": 0, "skipped": 0, "errors": 0}
    payload["inputArtifacts"].extend(
        [
            {
                "path": ".harness/work/CRM-QA-001.backend-full.marker-fixed.xml",
                "sizeBytes": junit.stat().st_size,
                "sha256": hashlib.sha256(junit.read_bytes()).hexdigest(),
            },
            {
                "path": ".harness/work/CRM-QA-001.backend-full.marker-fixed-gate.json",
                "sizeBytes": gate.stat().st_size,
                "sha256": hashlib.sha256(gate.read_bytes()).hexdigest(),
            },
        ]
    )
    scorecard.write_text(json.dumps(payload), encoding="utf-8")
    issues = validate_scorecard(scorecard, root=tmp_path, expected_head="abc123")
    assert "regression.backendFull.tests=2 does not match evidence 1" in issues


def test_scorecard_rejects_frontend_coverage_mismatch(tmp_path: Path) -> None:
    scorecard = _write_fixture(tmp_path)
    summary_dir = tmp_path / "frontend" / "coverage"
    summary_dir.mkdir(parents=True)
    summary = summary_dir / "coverage-summary.json"
    summary.write_text(
        json.dumps({"total": {"lines": {"pct": 0}, "statements": {"pct": 0}, "branches": {"pct": 0}, "functions": {"pct": 0}}}),
        encoding="utf-8",
    )
    payload = json.loads(scorecard.read_text(encoding="utf-8"))
    payload["coverage"]["frontendVitest"] = {
        "linePercent": 93,
        "statementsPercent": 93,
        "branchPercent": 93,
        "functionsPercent": 93,
    }
    payload["inputArtifacts"].append(
        {
            "path": "frontend/coverage/coverage-summary.json",
            "sizeBytes": summary.stat().st_size,
            "sha256": hashlib.sha256(summary.read_bytes()).hexdigest(),
        }
    )
    scorecard.write_text(json.dumps(payload), encoding="utf-8")
    issues = validate_scorecard(scorecard, root=tmp_path, expected_head="abc123")
    assert "coverage.frontendVitest.linePercent=93 does not match evidence 0" in issues
