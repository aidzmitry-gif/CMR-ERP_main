"""Build a loss-prevention inventory for CRM-GIT-001.

The output is evidence only: this script never stages, moves, or deletes files.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / ".harness" / "work" / "CRM-GIT-001.inventory.json"


def git_bytes(*args: str, cwd: Path = ROOT) -> bytes:
    return subprocess.check_output(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=cwd,
        stderr=subprocess.DEVNULL,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def classify(path: str) -> tuple[str, str, str]:
    lower = path.lower()
    name = Path(path).name.lower()
    suffix = Path(path).suffix.lower()

    if lower.startswith(".harness/"):
        return "goal-control", "commit-candidate", "codex-primary"
    if lower == "agents.md":
        return "governance", "commit-candidate", "repository-owner"
    if lower.startswith("coordination/"):
        if any(token in lower for token in ("/.daily-review-data/", "__pycache__", ".migration-reservations.local")):
            return "local-runtime", "retain-ignore-candidate", "local-operator"
        return "coordination", "preserve-review", "claude-coordinator"
    if lower.startswith("obsidian/"):
        return "knowledge-base", "preserve-review", "repository-owner"
    if lower.startswith("artifact/") or lower.startswith("_sales-mockups-share/"):
        return "artifacts", "retain-local-review", "repository-owner"
    if lower.startswith("marketing-prototype/"):
        return "prototype", "preserve-review", "repository-owner"
    if any(token in lower for token in ("/__pycache__/", "/.next/", "/.pytest", "/node_modules/")) or name.endswith((".pyc", ".pyo")):
        return "local-runtime", "retain-ignore-candidate", "local-operator"
    if lower.startswith(".codex/") or name in {
        "cov-backend.json",
        "migstate.json",
        "docker-compose.override.yml",
        "docker-compose.isolated.yml",
    }:
        return "local-runtime", "retain-ignore-candidate", "local-operator"
    if lower in {"config/settings.py", "core/services/__init__.py", "pyproject.toml", "requirements.txt"}:
        return "mixed-bank-gsheets", "split-hunks", "codex-primary"
    if lower == "scripts/next_migration.py":
        return "migration-allocator", "commit-candidate", "codex-primary"
    if lower == "migrations/versions/0087_leads_init.py":
        return "migration-0087-gate", "hold-for-proof", "codex-primary"
    if lower == "migrations/versions/0105_office_doc_deal_id.py":
        return "office-deal-link", "commit-candidate", "codex-primary"
    if lower == "migrations/versions/0106_finance_bank_transaction.py":
        return "bank-import", "commit-candidate", "codex-primary"
    if lower.startswith("modules/finance") or lower == "tests/test_finance.py":
        return "finance-claims", "submodule-or-parent-commit", "codex-primary"
    if lower in {"core/services/bank.py", "modules/integrations/alfa.py", "tests/test_finance_bank.py"}:
        return "bank-import", "commit-candidate", "codex-primary"
    if lower == "core/services/gsheets.py":
        return "google-sheets", "commit-candidate", "codex-primary"
    if lower.startswith("modules/office/") or lower in {"tests/test_office.py", "tests/unit/test_office_events.py"}:
        return "office-deal-link", "commit-candidate", "codex-primary"
    if lower.startswith("modules/sales") or lower in {"tests/test_touch_history.py", "tests/test_sales_touch_history.py"}:
        return "sales-touch-history", "submodule-or-parent-commit", "codex-primary"
    if lower.startswith("modules/leads") or lower == "tests/unit/test_leads_planning.py":
        return "leads-planning", "submodule-or-parent-commit", "codex-primary"
    if lower == "core/services/reference_import.py":
        return "reference-import", "commit-candidate", "codex-primary"
    if lower.startswith("modules/integrations/") or lower == "tests/test_integrations_auth.py":
        return "integrations-auth-intake", "split-or-commit-candidate", "codex-primary"
    if lower in {
        "frontend/src/app/api/[...path]/route.ts",
        "frontend/src/lib/access.ts",
        "frontend/src/lib/api-proxy-headers.ts",
    }:
        return "oidc-proxy", "commit-candidate", "codex-primary"
    if lower.startswith("frontend/src/"):
        return "frontend-tests-ui", "commit-review", "codex-primary"
    if lower.startswith("tests/"):
        return "test-support", "attach-to-feature", "codex-primary"
    if lower.startswith("scripts/") and name.startswith("_probe_1c"):
        return "local-probes", "retain-local-review", "local-operator"
    if lower.startswith("_docs_out/") or suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".html", ".pptx", ".docx", ".xlsx", ".zip"}:
        return "artifacts", "retain-local-review", "repository-owner"
    if suffix in {".md", ".txt", ".json"}:
        return "root-docs", "preserve-review", "repository-owner"
    return "other", "preserve-review", "repository-owner"


def parse_status(*, cwd: Path = ROOT) -> list[tuple[str, str]]:
    raw = git_bytes("status", "--porcelain=v1", "-z", "--untracked-files=all", cwd=cwd)
    items = raw.split(b"\0")
    records: list[tuple[str, str]] = []
    index = 0
    while index < len(items):
        item = items[index]
        if not item:
            index += 1
            continue
        status = item[:2].decode("ascii", errors="replace")
        path = os.fsdecode(item[3:])
        records.append((status, path.replace("\\", "/")))
        if status[0] in {"R", "C"}:
            index += 1
        index += 1
    return records


def record_for(status: str, relative: str, *, absolute: Path | None = None, scope: str = "root") -> dict[str, object]:
    absolute = ROOT / relative if absolute is None else absolute
    group, disposition, owner = classify(relative)
    record: dict[str, object] = {
        "status": status,
        "path": relative,
        "group": group,
        "disposition": disposition,
        "owner": owner,
        "scope": scope,
        "kind": "missing",
        "size": None,
        "sha256": None,
    }
    if absolute.is_file():
        record.update(kind="file", size=absolute.stat().st_size, sha256=sha256_file(absolute))
    elif absolute.is_dir():
        try:
            head = git_bytes("rev-parse", "HEAD", cwd=absolute).decode().strip()
            inner = git_bytes("status", "--porcelain=v1", "-z", "--untracked-files=all", cwd=absolute)
            record.update(
                kind="submodule",
                head=head,
                innerStatusSha256=hashlib.sha256(inner).hexdigest(),
                innerStatusEntries=sum(1 for item in inner.split(b"\0") if item),
            )
        except (OSError, subprocess.CalledProcessError):
            record.update(kind="directory")
    return record


def main() -> None:
    root_status = parse_status()
    records: list[dict[str, object]] = []
    inner_status_entries = 0
    for code, path in root_status:
        parent = record_for(code, path)
        records.append(parent)
        if parent["kind"] != "submodule":
            continue
        submodule_root = ROOT / path
        inner_status = parse_status(cwd=submodule_root)
        inner_status_entries += len(inner_status)
        for inner_code, inner_path in inner_status:
            full_path = f"{path}/{inner_path}"
            records.append(
                record_for(
                    inner_code,
                    full_path,
                    absolute=submodule_root / inner_path,
                    scope=path,
                )
            )
    groups = Counter(str(item["group"]) for item in records)
    dispositions = Counter(str(item["disposition"]) for item in records)
    payload = {
        "schemaVersion": 1,
        "chainId": "CRM-GIT-001",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "repository": {
            "root": str(ROOT).replace("\\", "/"),
            "branch": git_bytes("branch", "--show-current").decode().strip(),
            "head": git_bytes("rev-parse", "HEAD").decode().strip(),
        },
        "coverage": {
            "rootStatusEntries": len(root_status),
            "submoduleInnerStatusEntries": inner_status_entries,
            "statusEntries": len(root_status) + inner_status_entries,
            "manifestEntries": len(records),
            "complete": len(root_status) + inner_status_entries == len(records),
        },
        "groupCounts": dict(sorted(groups.items())),
        "dispositionCounts": dict(sorted(dispositions.items())),
        "records": records,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in ("repository", "coverage", "groupCounts", "dispositionCounts")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
