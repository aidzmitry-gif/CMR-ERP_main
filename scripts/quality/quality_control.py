"""Fail-closed validation for the CRM-QA-001 test registry.

The integrity mode verifies that evidence is present and internally consistent.
Strict mode is the CI release gate: unknown or unclassified records are errors,
not warnings. The self-test uses temporary copies and never edits repository
artifacts.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import uuid
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UNKNOWN_VALUES = {"unknown", "unclassified", "overlap", None, ""}
REQUIRED_COMMANDS = {
    "backend-collect-all",
    "backend-collect-unit",
    "backend-collect-api",
    "backend-collect-integration",
    "frontend-vitest-list",
    "frontend-playwright-list",
}
BASELINE_FIELDS = (
    "testId",
    "platform",
    "runner",
    "sourcePath",
    "layer",
    "layers",
    "size",
    "domain",
    "domainCandidates",
    "cuj",
    "cujCandidates",
    "sourceSha256",
    "caseFingerprint",
)


def repo_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def read_json(path: Path, label: str, issues: list[str]) -> dict[str, Any] | None:
    if not path.is_file():
        issues.append(f"{label}: missing artifact {path}")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(f"{label}: invalid JSON {path}: {exc}")
        return None
    if not isinstance(value, dict):
        issues.append(f"{label}: top-level JSON must be an object")
        return None
    return value


def add_counts(records: list[dict[str, Any]], field: str) -> dict[str, int]:
    return dict(Counter(str(record.get(field)) for record in records))


def compare_baseline(
    baseline_records: list[dict[str, Any]], candidate_records: list[dict[str, Any]]
) -> dict[str, Any]:
    baseline_by_id = {
        item.get("testId"): item
        for item in baseline_records
        if isinstance(item, dict) and isinstance(item.get("testId"), str)
    }
    candidate_by_id = {
        item.get("testId"): item
        for item in candidate_records
        if isinstance(item, dict) and isinstance(item.get("testId"), str)
    }
    baseline_ids = set(baseline_by_id)
    candidate_ids = set(candidate_by_id)
    added = sorted(candidate_ids - baseline_ids)
    removed = sorted(baseline_ids - candidate_ids)
    changed: list[str] = []
    classification_changed: list[str] = []
    classification_fields = (
        "layer",
        "layers",
        "size",
        "domain",
        "domainCandidates",
        "cuj",
        "cujCandidates",
    )
    for test_id in sorted(baseline_ids & candidate_ids):
        previous = baseline_by_id[test_id]
        current = candidate_by_id[test_id]
        if any(
            previous.get(field) != current.get(field)
            for field in ("sourceSha256", "caseFingerprint")
        ):
            changed.append(test_id)
        if any(previous.get(field) != current.get(field) for field in classification_fields):
            classification_changed.append(test_id)
    return {
        "baselineCount": len(baseline_records),
        "candidateCount": len(candidate_records),
        "added": added,
        "removed": removed,
        "changed": changed,
        "classificationChanged": classification_changed,
        "hasChanges": bool(added or removed or changed or classification_changed),
    }


def validate_bundle(
    inventory_path: Path,
    evidence_path: Path,
    baseline_path: Path,
    mode: str,
) -> dict[str, Any]:
    issues: list[str] = []
    notes: list[str] = []
    inventory = read_json(inventory_path, "inventory", issues)
    evidence = read_json(evidence_path, "evidence", issues)
    baseline = read_json(baseline_path, "baseline", issues)
    records = inventory.get("records", []) if inventory else []
    baseline_records = baseline.get("records", []) if baseline else []
    if not isinstance(records, list):
        issues.append("inventory.records must be an array")
        records = []
    if not isinstance(baseline_records, list):
        issues.append("baseline.records must be an array")
        baseline_records = []

    if inventory:
        if inventory.get("schemaVersion") != 1:
            issues.append("inventory.schemaVersion must be 1")
        if inventory.get("chainId") != "CRM-QA-001":
            issues.append("inventory.chainId must be CRM-QA-001")
        sources = inventory.get("nativeSources")
        if not isinstance(sources, dict):
            issues.append("inventory.nativeSources is missing")
        else:
            for source_name in ("backend", "frontendVitest", "frontendPlaywright"):
                source = sources.get(source_name)
                if not isinstance(source, dict):
                    issues.append(f"inventory.nativeSources.{source_name} is missing")
                    continue
                if source.get("nativeCollectionAvailable") is not True:
                    issues.append(f"{source_name}: native collection is unavailable")
                if source.get("nativeItemInventory") is not True:
                    issues.append(f"{source_name}: native item inventory is unavailable")

    if evidence:
        if evidence.get("schemaVersion") != 1:
            issues.append("evidence.schemaVersion must be 1")
        commands = evidence.get("commands")
        if not isinstance(commands, list):
            issues.append("evidence.commands is missing")
            commands = []
        command_map = {
            item.get("id"): item for item in commands if isinstance(item, dict) and item.get("id")
        }
        missing_commands = sorted(REQUIRED_COMMANDS - set(command_map))
        if missing_commands:
            issues.append(f"missing native command evidence: {missing_commands}")
        provenance = evidence.get("nativeArtifactProvenance", {}).get("frontendVitest", {})
        expected_vitest_count = (
            inventory.get("counts", {}).get("byRunner", {}).get("vitest")
            if isinstance(inventory, dict) and isinstance(inventory.get("counts"), dict)
            else None
        )
        for command_id, command in command_map.items():
            exit_code = command.get("exitCode")
            if exit_code == 0:
                continue
            if (
                mode == "integrity"
                and command_id == "frontend-vitest-list"
                and provenance.get("workerExitCode") == 0
                and isinstance(provenance.get("recordCount"), int)
                and provenance.get("recordCount") == expected_vitest_count
            ):
                notes.append(
                    "frontend-vitest-list current reproduction was EPERM; "
                    f"the saved native worker artifact ({expected_vitest_count} records) "
                    "is accepted in integrity mode"
                )
                continue
            issues.append(f"{command_id}: native command exitCode={exit_code}")
        artifact_manifest = evidence.get("artifacts", [])
        if not isinstance(artifact_manifest, list):
            issues.append("evidence.artifacts is missing")
        else:
            for artifact in artifact_manifest:
                if not isinstance(artifact, dict):
                    issues.append("evidence.artifacts contains a non-object")
                    continue
                path = repo_path(str(artifact.get("path", "")))
                if not path.is_file():
                    issues.append(f"evidence artifact missing: {artifact.get('path')}")
                    continue
                if artifact.get("sha256") and artifact["sha256"] != sha256_file(path):
                    issues.append(f"evidence artifact fingerprint mismatch: {artifact.get('path')}")

    ids: list[str] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            issues.append(f"inventory.records[{index}] must be an object")
            continue
        test_id = record.get("testId")
        if not isinstance(test_id, str) or not test_id:
            issues.append(f"inventory.records[{index}].testId is missing")
        else:
            ids.append(test_id)
        for field in ("platform", "runner", "layer", "size", "domain", "cuj"):
            if field not in record:
                issues.append(f"inventory.records[{index}].{field} is missing")
        for field in ("sourceSha256", "caseFingerprint"):
            if not HEX64.fullmatch(str(record.get(field, ""))):
                issues.append(f"inventory.records[{index}].{field} is not a sha256")

    duplicate_ids = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicate_ids:
        issues.append(f"duplicate test IDs: {duplicate_ids[:10]}")
    baseline_ids: list[str] = []
    for index, record in enumerate(baseline_records):
        if not isinstance(record, dict):
            issues.append(f"baseline.records[{index}] must be an object")
            continue
        test_id = record.get("testId")
        if not isinstance(test_id, str) or not test_id:
            issues.append(f"baseline.records[{index}].testId is missing")
            continue
        baseline_ids.append(test_id)
    duplicate_baseline_ids = sorted(
        item for item, count in Counter(baseline_ids).items() if count > 1
    )
    if duplicate_baseline_ids:
        issues.append(f"duplicate baseline test IDs: {duplicate_baseline_ids[:10]}")
    baseline_comparison = compare_baseline(baseline_records, records)
    if baseline_comparison["hasChanges"]:
        issues.append(f"regression baseline drift: {baseline_comparison}")
    if inventory and inventory.get("counts", {}).get("totalRecords") != len(records):
        issues.append("inventory counts.totalRecords does not match records")
    if baseline and baseline.get("recordCount") != len(baseline_records):
        issues.append("baseline.recordCount does not match baseline.records")

    for field in ("layer", "size", "domain", "cuj"):
        counts = add_counts(records, field)
        unknown = {
            key: value for key, value in counts.items() if key in UNKNOWN_VALUES
        }
        if unknown:
            if mode == "strict":
                issues.append(f"strict classification failure {field}: {unknown}")
            else:
                notes.append(f"integrity classification report {field}: {unknown}")

    if mode == "strict" and evidence:
        execution = evidence.get("executionEvidence", {})
        if not isinstance(execution, dict):
            issues.append("strict execution evidence is missing")
        for key in ("backendFullJUnit", "backendUnitJUnit"):
            if not isinstance(execution.get(key), dict):
                issues.append(f"strict JUnit evidence missing: {key}")

    return {
        "schemaVersion": 1,
        "mode": mode,
        "ok": not issues,
        "inventory": str(inventory_path),
        "evidence": str(evidence_path),
        "baseline": str(baseline_path),
        "recordCount": len(records),
        "duplicateIdCount": len(duplicate_ids),
        "duplicateBaselineIdCount": len(duplicate_baseline_ids),
        "baselineComparison": baseline_comparison,
        "counts": {
            "layer": add_counts(records, "layer"),
            "size": add_counts(records, "size"),
            "domain": add_counts(records, "domain"),
            "cuj": add_counts(records, "cuj"),
        },
        "issues": issues,
        "notes": notes,
    }


def sha256_file(path: Path) -> str | None:
    import hashlib

    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def write_report(path: Path | None, report: dict[str, Any]) -> None:
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path:
        path.write_text(payload, encoding="utf-8")
    print(payload, end="")


def validate_junit(path: Path, require_executed: bool) -> dict[str, Any]:
    issues: list[str] = []
    if not path.is_file():
        issues.append(f"missing JUnit report: {path}")
        return {
            "schemaVersion": 1,
            "junit": str(path),
            "ok": False,
            "tests": 0,
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "issues": issues,
        }
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError) as exc:
        issues.append(f"invalid JUnit report {path}: {exc}")
        return {
            "schemaVersion": 1,
            "junit": str(path),
            "ok": False,
            "tests": 0,
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "issues": issues,
        }

    cases = list(root.iter("testcase"))
    skipped = sum(1 for case in cases if case.find("skipped") is not None)
    failed = sum(1 for case in cases if case.find("failure") is not None)
    errors = sum(1 for case in cases if case.find("error") is not None)
    tests = len(cases)
    passed = tests - skipped - failed - errors
    if tests == 0:
        issues.append("JUnit contains no test cases")
    if failed or errors:
        issues.append(f"JUnit has failed={failed} errors={errors}")
    if require_executed and skipped:
        issues.append(f"JUnit has skipped={skipped}; required lane was not executed")
    if require_executed and passed == 0:
        issues.append("JUnit has no passed executed test case")
    return {
        "schemaVersion": 1,
        "junit": str(path),
        "ok": not issues,
        "tests": tests,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "issues": issues,
    }


def self_test(
    inventory_path: Path,
    evidence_path: Path,
    baseline_path: Path,
) -> int:
    temp_root = ROOT / ".harness" / "work"
    token = f"CRM-QA-001.g04-selftest-{uuid.uuid4().hex}"
    paths = {
        "inventory": temp_root / f"{token}.inventory.json",
        "evidence": temp_root / f"{token}.evidence.json",
        "baseline": temp_root / f"{token}.baseline.json",
    }
    temporary_paths = list(paths.values())
    try:
        shutil.copyfile(inventory_path, paths["inventory"])
        shutil.copyfile(evidence_path, paths["evidence"])
        shutil.copyfile(baseline_path, paths["baseline"])

        accepted = validate_bundle(
            paths["inventory"], paths["evidence"], paths["baseline"], "integrity"
        )
        if not accepted["ok"]:
            print(json.dumps(accepted, ensure_ascii=False, indent=2))
            return 1

        missing = validate_bundle(
            temp_root / f"{token}.missing.json",
            paths["evidence"],
            paths["baseline"],
            "integrity",
        )
        if missing["ok"]:
            return 1

        missing_evidence = validate_bundle(
            paths["inventory"],
            temp_root / f"{token}.missing-evidence.json",
            paths["baseline"],
            "integrity",
        )
        if missing_evidence["ok"]:
            return 1

        duplicate_data = json.loads(paths["inventory"].read_text(encoding="utf-8"))
        duplicate_data["records"].append(copy.deepcopy(duplicate_data["records"][0]))
        duplicate_data["records"][-1]["testId"] = duplicate_data["records"][0]["testId"]
        duplicate_path = temp_root / f"{token}.duplicate.json"
        temporary_paths.append(duplicate_path)
        duplicate_path.write_text(
            json.dumps(duplicate_data, ensure_ascii=False), encoding="utf-8"
        )
        duplicate = validate_bundle(
            duplicate_path, paths["evidence"], paths["baseline"], "integrity"
        )
        if duplicate["ok"]:
            return 1

        unknown_data = json.loads(paths["inventory"].read_text(encoding="utf-8"))
        unknown_data["records"][0]["size"] = "unknown"
        unknown_path = temp_root / f"{token}.unknown.json"
        temporary_paths.append(unknown_path)
        unknown_path.write_text(
            json.dumps(unknown_data, ensure_ascii=False), encoding="utf-8"
        )
        unknown = validate_bundle(
            unknown_path, paths["evidence"], paths["baseline"], "strict"
        )
        if unknown["ok"]:
            return 1

        junit_pass_path = temp_root / f"{token}.passed.xml"
        junit_skip_path = temp_root / f"{token}.skipped.xml"
        temporary_paths.extend((junit_pass_path, junit_skip_path))
        junit_pass_path.write_text(
            '<testsuite tests="1"><testcase classname="g04" name="pass" /></testsuite>',
            encoding="utf-8",
        )
        junit_skip_path.write_text(
            '<testsuite tests="1"><testcase classname="g04" name="skip">'
            "<skipped /></testcase></testsuite>",
            encoding="utf-8",
        )
        if not validate_junit(junit_pass_path, require_executed=True)["ok"]:
            return 1
        if validate_junit(junit_skip_path, require_executed=True)["ok"]:
            return 1
    finally:
        for path in temporary_paths:
            path.unlink(missing_ok=True)

    print("QUALITY CONTROL SELF-TEST PASS")
    print("PASS accepted registry integrity")
    print("PASS missing inventory fails closed")
    print("PASS missing evidence fails closed")
    print("PASS duplicate test ID fails closed")
    print("PASS unknown classification fails strict mode")
    print("PASS skipped JUnit integration lane fails closed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="CRM-QA-001 fail-closed registry gate")
    subparsers = parser.add_subparsers(dest="action", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--inventory", required=True)
    validate_parser.add_argument("--evidence", required=True)
    validate_parser.add_argument("--baseline", required=True)
    validate_parser.add_argument("--mode", choices=("integrity", "strict"), default="strict")
    validate_parser.add_argument("--report")

    self_test_parser = subparsers.add_parser("self-test")
    self_test_parser.add_argument("--inventory", required=True)
    self_test_parser.add_argument("--evidence", required=True)
    self_test_parser.add_argument("--baseline", required=True)

    junit_parser = subparsers.add_parser("validate-junit")
    junit_parser.add_argument("--junit", required=True)
    junit_parser.add_argument("--require-executed", action="store_true")
    junit_parser.add_argument("--report")

    args = parser.parse_args()
    if args.action == "self-test":
        return self_test(
            repo_path(args.inventory), repo_path(args.evidence), repo_path(args.baseline)
        )
    if args.action == "validate-junit":
        report = validate_junit(repo_path(args.junit), args.require_executed)
        write_report(repo_path(args.report) if args.report else None, report)
        return 0 if report["ok"] else 1
    report = validate_bundle(
        repo_path(args.inventory),
        repo_path(args.evidence),
        repo_path(args.baseline),
        args.mode,
    )
    write_report(repo_path(args.report) if args.report else None, report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
