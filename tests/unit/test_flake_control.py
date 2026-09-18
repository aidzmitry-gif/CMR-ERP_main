from __future__ import annotations

from datetime import date

import pytest

from scripts.quality.flake_control import validate_policy

pytestmark = pytest.mark.unit


def _valid_policy() -> dict:
    return {
        "schemaVersion": 1,
        "chainId": "CRM-QA-001",
        "defaults": {"maxRetries": 0, "mode": "diagnostic_only", "passOnRetry": False},
        "quarantine": [],
    }


def test_policy_accepts_diagnostic_only_defaults():
    assert validate_policy(_valid_policy(), today=date(2026, 1, 1)) == []


def test_policy_rejects_retry_as_a_green_bypass():
    policy = _valid_policy()
    policy["defaults"] = {"maxRetries": 1, "mode": "retry", "passOnRetry": True}
    issues = validate_policy(policy, today=date(2026, 1, 1))
    assert "defaults.mode must be diagnostic_only" in issues
    assert "defaults.passOnRetry must be false" in issues


def test_policy_requires_live_owner_issue_and_expiry_for_quarantine():
    policy = _valid_policy()
    policy["quarantine"] = [
        {
            "testId": "backend:pytest:test_x::test_y",
            "owner": "qa",
            "issue": "QA-1",
            "reason": "temporary dependency",
            "expiresAt": "2026-01-02",
        }
    ]
    assert validate_policy(policy, today=date(2026, 1, 1)) == []
    assert validate_policy(policy, today=date(2026, 1, 2))


def test_policy_rejects_long_lived_quarantine():
    policy = _valid_policy()
    policy["quarantine"] = [
        {
            "testId": "backend:pytest:test_x::test_y",
            "owner": "qa",
            "issue": "QA-1",
            "reason": "temporary dependency",
            "expiresAt": "2026-02-01",
        }
    ]
    assert validate_policy(policy, today=date(2026, 1, 1))
