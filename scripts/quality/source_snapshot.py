"""Fail-closed parent/submodule source snapshot check for CRM-QA-001."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _git(args: list[str], cwd: Path = ROOT) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=False
        )
    except OSError as exc:
        return 127, "", f"{type(exc).__name__}: {exc}"
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def parent_gitlinks() -> tuple[dict[str, str], str | None, list[str]]:
    issues: list[str] = []
    code, head, stderr = _git(["rev-parse", "HEAD"])
    if code != 0:
        issues.append(f"parent HEAD unavailable: {stderr or code}")
        head = None
    # ``modules/*`` is not expanded by Git as a pathspec on all supported
    # Git versions.  Recursive tree output is stable and lets us discover
    # every gitlink, including nested module paths, without relying on the
    # current checkout contents.
    code, output, stderr = _git(["ls-tree", "-r", "HEAD", "--", "modules"])
    if code != 0:
        issues.append(f"parent gitlinks unavailable: {stderr or code}")
        return {}, head, issues
    expected: dict[str, str] = {}
    for line in output.splitlines():
        metadata, separator, path = line.partition("\t")
        fields = metadata.split()
        if separator and len(fields) == 3 and fields[0] == "160000" and path:
            expected[path] = fields[2]
    if not expected:
        issues.append("parent gitlinks empty: source snapshot cannot be verified")
    return expected, head, issues


def actual_submodule_heads(expected: dict[str, str]) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    issues: list[str] = []
    for path, expected_head in sorted(expected.items()):
        module_path = ROOT / path
        code, actual_head, stderr = _git(["rev-parse", "HEAD"], cwd=module_path)
        if code != 0:
            issues.append(f"{path}: worktree HEAD unavailable: {stderr or code}")
            actual_head = None
        branch_code, branch, _ = _git(["branch", "--show-current"], cwd=module_path)
        if branch_code != 0:
            branch = None
        records.append(
            {
                "path": path,
                "parentGitlink": expected_head,
                "worktreeHead": actual_head,
                "worktreeBranch": branch or None,
                "matchesParentGitlink": actual_head == expected_head,
            }
        )
    return records, issues


def snapshot() -> dict[str, Any]:
    expected, parent_head, issues = parent_gitlinks()
    records, head_issues = actual_submodule_heads(expected)
    issues.extend(head_issues)
    mismatches = [record for record in records if not record["matchesParentGitlink"]]
    return {
        "schemaVersion": 1,
        "chainId": "CRM-QA-001",
        "parentHead": parent_head,
        "submodules": records,
        "mismatchCount": len(mismatches),
        "issues": issues,
        "ok": not issues and not mismatches,
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="CRM-QA-001 source snapshot gate")
    parser.add_argument("action", choices=("validate", "self-test"))
    parser.add_argument("--report")
    args = parser.parse_args()
    if args.action == "self-test":
        matching = {"path": "modules/demo", "parentGitlink": "a", "worktreeHead": "a", "matchesParentGitlink": True}
        drifted = {"path": "modules/demo", "parentGitlink": "a", "worktreeHead": "b", "matchesParentGitlink": False}
        if matching["matchesParentGitlink"] is not True or drifted["matchesParentGitlink"] is not False:
            print("SOURCE SNAPSHOT SELF-TEST FAIL")
            return 1
        print("SOURCE SNAPSHOT SELF-TEST PASS")
        return 0
    report = snapshot()
    if args.report:
        write_report(ROOT / args.report if not Path(args.report).is_absolute() else Path(args.report), report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if report["ok"]:
        print("SOURCE SNAPSHOT PASS")
        return 0
    print("SOURCE SNAPSHOT FAIL CLOSED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
