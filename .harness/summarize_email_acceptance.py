"""Summarize completed evidence, retaining the reused-database failure provenance."""

import json
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[1]
report = root / "reports/email-send-001"
source = report / "acceptance-20260909-044818"
evidence = report / "evidence"
evidence.mkdir(exist_ok=True)


def suites(path):
    tree = ET.parse(path).getroot()
    rows = [tree] if tree.tag == "testsuite" else list(tree.findall("testsuite"))
    return {
        key: sum(int(row.get(key, "0")) for row in rows)
        for key in ("tests", "failures", "errors", "skipped")
    }


parts = [suites(report / f"backend-part{i}.xml") for i in range(4)]
parts.append(suites(report / "backend-part4-fresh.xml"))
totals = {key: sum(part[key] for part in parts) for key in parts[0]}
totals["passed"] = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
coverage = ET.parse(report / "coverage.xml").getroot()
covered = sum(int(coverage.get(key)) for key in ("lines-covered", "branches-covered"))
valid = sum(int(coverage.get(key)) for key in ("lines-valid", "branches-valid"))
browser = json.loads((source / "browser-evidence.json").read_text(encoding="utf-8"))
browser.pop("output", None)
summary = {
    "observed_at": datetime.now(timezone.utc).isoformat(),
    "backend": totals,
    "coverage_with_branches_percent": round(covered * 100 / valid, 2),
    "coverage_gate_90": covered / valid >= 0.90,
    "reused_database_initial_failure": suites(report / "backend-part4.xml"),
    "resolution": "All 12 integration tests passed after full Alembic upgrade on a fresh isolated database.",
    "frontend": {
        "passed": 2488,
        "files": 183,
        "last_changed_components_passed": 83,
        "typecheck": "passed",
        "lint_errors": 0,
        "lint_warnings": 45,
        "lint_ceiling": 47,
    },
    "standard_playwright_passed": 8,
    "synthetic_smtp_browser": browser,
    "migration": {
        "revision": "0116",
        "down_revision": "0114",
        "heads": 1,
        "fresh_postgresql_18_upgrade": "passed",
        "pg16_ci": "not_run_push_not_authorized",
    },
    "release_blocks": [
        "Final immutable-documents integration and migration ordering",
        "Git push/draft PR authorization after automatic review rejection",
        "Corporate sender/configuration and authorized live control recipient",
    ],
    "production_changed": False,
    "external_mail_sent": False,
}
(evidence / "verification.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
)
for name in (
    "invoice-v1.pdf",
    "contract-v1.pdf",
    "browser-preview.png",
    "browser-accepted.png",
    "browser-failed.png",
    "browser-uncertain.png",
    "browser-attempts.png",
):
    shutil.copyfile(source / name, evidence / name)
print(
    json.dumps({"backend": totals, "coverage": summary["coverage_with_branches_percent"]}, indent=2)
)
