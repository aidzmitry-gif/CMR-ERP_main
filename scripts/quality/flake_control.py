"""Fail-closed validation for the CRM-QA-001 flake policy.

The policy deliberately does not implement a test retry. A retry may be used by a
caller for diagnosis, but a required CI check remains failed until the original
failure is fixed. Quarantine is an explicit, short-lived exception with an owner
and issue reference; it is never a green bypass.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ALLOWED_MODES = {"diagnostic_only"}
MAX_QUARANTINE_DAYS = 14


def policy_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load_policy(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("policy must be a JSON object")
    return value


def _validate_entry(entry: Any, index: int, today: date) -> list[str]:
    issues: list[str] = []
    if not isinstance(entry, dict):
        return [f"quarantine[{index}] must be an object"]
    required = ("testId", "owner", "issue", "reason", "expiresAt")
    for field in required:
        if not isinstance(entry.get(field), str) or not entry[field].strip():
            issues.append(f"quarantine[{index}].{field} is required")
    raw_expiry = entry.get("expiresAt")
    try:
        expiry = date.fromisoformat(raw_expiry) if isinstance(raw_expiry, str) else None
    except ValueError:
        expiry = None
    if expiry is None:
        issues.append(f"quarantine[{index}].expiresAt must be YYYY-MM-DD")
    elif expiry <= today:
        issues.append(f"quarantine[{index}] is expired: {raw_expiry}")
    elif expiry > today + timedelta(days=MAX_QUARANTINE_DAYS):
        issues.append(
            f"quarantine[{index}] expiry exceeds {MAX_QUARANTINE_DAYS}-day maximum"
        )
    if entry.get("mode", "diagnostic_only") not in ALLOWED_MODES:
        issues.append(f"quarantine[{index}].mode must be diagnostic_only")
    if entry.get("passOnRetry", False) is not False:
        issues.append(f"quarantine[{index}].passOnRetry must be false")
    retries = entry.get("maxRetries", 0)
    if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0:
        issues.append(f"quarantine[{index}].maxRetries must be a non-negative integer")
    return issues


def validate_policy(policy: dict[str, Any], *, today: date | None = None) -> list[str]:
    today = today or date.today()
    issues: list[str] = []
    if policy.get("schemaVersion") != 1:
        issues.append("schemaVersion must be 1")
    if policy.get("chainId") != "CRM-QA-001":
        issues.append("chainId must be CRM-QA-001")
    defaults = policy.get("defaults")
    if not isinstance(defaults, dict):
        issues.append("defaults must be an object")
        defaults = {}
    if defaults.get("mode") not in ALLOWED_MODES:
        issues.append("defaults.mode must be diagnostic_only")
    if defaults.get("passOnRetry") is not False:
        issues.append("defaults.passOnRetry must be false")
    max_retries = defaults.get("maxRetries")
    if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
        issues.append("defaults.maxRetries must be a non-negative integer")
    quarantine = policy.get("quarantine")
    if not isinstance(quarantine, list):
        issues.append("quarantine must be an array")
        quarantine = []
    test_ids: set[str] = set()
    for index, entry in enumerate(quarantine):
        issues.extend(_validate_entry(entry, index, today))
        if isinstance(entry, dict):
            test_id = entry.get("testId")
            if isinstance(test_id, str) and test_id:
                if test_id in test_ids:
                    issues.append(f"duplicate quarantine testId: {test_id}")
                test_ids.add(test_id)
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="CRM-QA-001 flake policy gate")
    parser.add_argument("action", choices=("validate", "self-test"))
    parser.add_argument("--policy", default=".harness/policy/flake-policy.json")
    args = parser.parse_args()

    if args.action == "self-test":
        valid = {
            "schemaVersion": 1,
            "chainId": "CRM-QA-001",
            "defaults": {"maxRetries": 0, "mode": "diagnostic_only", "passOnRetry": False},
            "quarantine": [],
        }
        expired = {
            **valid,
            "quarantine": [
                {
                    "testId": "backend:pytest:test_x::test_y",
                    "owner": "qa",
                    "issue": "QA-1",
                    "reason": "temporary external dependency",
                    "expiresAt": "2020-01-01",
                }
            ],
        }
        retry_bypass = {**valid, "defaults": {"maxRetries": 1, "mode": "retry", "passOnRetry": True}}
        checks = [
            ("valid policy", not validate_policy(valid, today=date(2026, 1, 1))),
            ("expired quarantine fails", bool(validate_policy(expired, today=date(2026, 1, 1)))),
            ("retry bypass fails", bool(validate_policy(retry_bypass, today=date(2026, 1, 1)))),
        ]
        if not all(result for _, result in checks):
            for name, result in checks:
                print(f"{'PASS' if result else 'FAIL'} {name}")
            return 1
        print("FLAKE POLICY SELF-TEST PASS")
        for name, _ in checks:
            print(f"PASS {name}")
        return 0

    try:
        policy = load_policy(policy_path(args.policy))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"FLAKE POLICY FAIL CLOSED: {exc}")
        return 1
    issues = validate_policy(policy)
    if issues:
        print("FLAKE POLICY FAIL CLOSED")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("FLAKE POLICY PASS: retries are diagnostic-only and no quarantine bypass is active")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
