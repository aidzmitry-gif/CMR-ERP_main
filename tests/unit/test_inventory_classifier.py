"""Executable tests for the evidence classifier used by the Harness inventory."""

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COLLECTOR = runpy.run_path(ROOT / ".harness" / "tools" / "build_g03_inventory.py")
path_matches = COLLECTOR["path_matches"]
policy_matches = COLLECTOR["policy_matches"]
normalise_test_path = COLLECTOR["normalise_test_path"]


def test_case_level_policy_matches_only_the_named_pytest_case():
    assert path_matches(
        "tests/test_leads.py::test_rbac_sales_manager_full_funnel",
        "tests/test_leads.py::test_rbac_sales_manager_full_funnel",
    )
    assert not path_matches(
        "tests/test_leads.py::test_lead_convert_creates_deal",
        "tests/test_leads.py::test_rbac_sales_manager_full_funnel",
    )


def test_case_level_policy_matches_parameterised_pytest_case():
    assert path_matches(
        "tests/test_access.py::test_role_matrix[manager-sales]",
        "tests/test_access.py::test_role_matrix",
    )


def test_directory_policy_still_matches_a_test_node():
    assert path_matches(
        "tests/unit/modules/leads/test_lead_routing_rules.py::test_balanced_assignment",
        "tests/unit/modules/leads",
    )


def test_glob_policy_matches_prefixed_test_files_without_matching_unrelated_names():
    assert path_matches("tests/test_logistics_core.py::test_one", "tests/test_logistics_*.py")
    assert not path_matches("tests/test_logistics.py::test_one", "tests/test_logistics_*.py")


def test_route_group_brackets_remain_literal_path_segments():
    assert path_matches(
        "frontend/src/app/api/[...path]/route.test.ts",
        "frontend/src/app/api/[...path]/route.test.ts",
    )


def test_exact_cuj_evidence_overrides_broad_file_evidence():
    policy = {
        "domains": [],
        "journeys": [
            {
                "id": "identity",
                "evidence": {
                    "Medium": [
                        "tests/test_leads.py::test_rbac_sales_manager_full_funnel"
                    ]
                },
            },
            {
                "id": "lead-deal",
                "evidence": {"Medium": ["tests/test_leads.py"]},
            },
        ],
    }
    assert policy_matches(
        "tests/test_leads.py::test_rbac_sales_manager_full_funnel", policy
    )[1] == ["identity"]


def test_specific_domain_evidence_overrides_cross_cutting_fallback():
    policy = {
        "domains": [
            {"id": "fallback", "currentEvidence": ["tests"]},
            {"id": "specific", "currentEvidence": ["tests/unit/modules/leads"]},
        ],
        "journeys": [],
    }
    assert policy_matches(
        "tests/unit/modules/leads/test_rules.py::test_one", policy
    )[0] == ["specific"]


def test_specific_cuj_directory_overrides_cross_cutting_fallback():
    policy = {
        "domains": [],
        "journeys": [
            {"id": "fallback", "evidence": {"Small": ["tests"]}},
            {
                "id": "specific",
                "evidence": {"Small": ["tests/unit/modules/leads"]},
            },
        ],
    }
    assert policy_matches(
        "tests/unit/modules/leads/test_rules.py::test_one", policy
    )[1] == ["specific"]


def test_source_path_normalisation_drops_only_the_case_suffix():
    assert normalise_test_path(
        "D:/workspace/tests/test_leads.py::test_lead_convert_creates_deal"
    ).endswith("tests/test_leads.py")
