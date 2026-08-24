"""Classify every currently visible CRM-GIT-001 change for final integration.

This tool is read-only except for its Goal evidence JSON. It never stages,
moves, deletes, or edits a repository-owned file.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / ".harness" / "work" / "CRM-GIT-001.final-classification.json"


def status_rows() -> list[tuple[str, str]]:
    raw = subprocess.check_output(
        ["git", "-c", "core.quotepath=false", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=ROOT,
    )
    return [
        (item[:2].decode("ascii", errors="replace"), os.fsdecode(item[3:]).replace("\\", "/"))
        for item in raw.split(b"\0")
        if item
    ]


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def classify(path: str) -> tuple[str, str, str]:
    lower = path.lower()
    name = Path(path).name.lower()

    if lower.startswith(".harness/"):
        if name.endswith((".before", ".patch")):
            return "retain-local", "local-goal-backups", "rollback or staging scratch; not repository source"
        return "commit", "goal-evidence", "reproducible Goal passport, evidence, and local acceptance tools"

    if lower.startswith("coordination/"):
        relative = lower.removeprefix("coordination/")
        local_names = {
            ".mockup-shot.png", ".quality-log.jsonl", ".shot-mockup.mjs",
            "active-sessions.md", "push-log.md", "reports.md", "riftek-360.md",
        }
        if name in local_names or relative.startswith("_"):
            reason = "runtime/raw/sensitive coordination material retained on disk"
            return "retain-local", "local-coordination", reason
        if name in {"status.md", "pitfalls.md", "readiness.json", "chat-onboarding.md", "fleet.md", "metrics.md"}:
            return "commit", "fleet-governance", "canonical fleet readiness or operating guidance"
        if name == ".daily-review-launcher.ps1" or name.startswith("shift-plan-"):
            return "commit", "fleet-governance", "fleet operating source or approved schedule record"
        task_prefixes = (
            "daily-review/", "first-msgs/", "handoff-", "integration-reports/",
            "orchestrator-answers/", "orchestrator-", "task-cursor-",
        )
        if relative.startswith(task_prefixes) or name.endswith(("-scope.md", "-status.md")):
            return "commit", "fleet-task-records", "bounded task scope, handoff, status, or acceptance record"
        return "commit", "project-design-records", "project architecture, process, or implementation record"

    if lower.startswith("obsidian/.obsidian/"):
        return "retain-local", "local-obsidian", "local Obsidian application preferences"
    if lower.startswith("obsidian/"):
        return "commit", "knowledge-vault", "canonical project knowledge note"
    if lower.startswith("marketing-prototype/"):
        return "commit", "marketing-prototype", "coherent local marketing UI prototype"

    project_plans = {
        ".claude/cloude-code-toolbox-mcp-skills-awareness.md",
        "1c-cost-price-plan.md", "1c-live-connect-tz.md", "1c-office-checklist.md",
        "_pr9_ci_handoff.md", "концепция_личный_ai_ассистент.md",
        "тз_внутренний_чат_мессенджер.md", "тз_личный_ai_ассистент_шаг1.md",
    }
    if lower in project_plans:
        return "commit", "project-plans", "project specification, checklist, or historical handoff"

    return "retain-local", "local-artifacts", "raw data, browser snapshot, local probe, backup, or helper"


def main() -> None:
    current_rows = status_rows()
    records_by_path: dict[str, dict[str, object]] = {}
    if OUTPUT.exists():
        previous = json.loads(OUTPUT.read_text(encoding="utf-8"))
        records_by_path = {str(item["path"]): item for item in previous["records"]}
    for status, relative in current_rows:
        action, bundle, reason = classify(relative)
        path = ROOT / relative
        records_by_path[relative] = {
            "status": status,
            "path": relative,
            "action": action,
            "bundle": bundle,
            "reason": reason,
            "size": path.stat().st_size if path.is_file() else None,
            "sha256": sha256(path),
        }
    records = [records_by_path[path] for path in sorted(records_by_path)]
    payload = {
        "schemaVersion": 1,
        "chainId": "CRM-GIT-001",
        "records": records,
        "coverage": {
            "visibleStatusEntries": len(current_rows),
            "protectedEntries": len(records),
            "classifiedEntries": len(records),
            "complete": True,
        },
        "actionCounts": dict(sorted(Counter(item["action"] for item in records).items())),
        "bundleCounts": dict(sorted(Counter(item["bundle"] for item in records).items())),
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in ("coverage", "actionCounts", "bundleCounts")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
