"""Install reversible, exact local Git excludes for CRM-GIT-001.

Only paths already classified as local artifacts/runtime are excluded. The
project .gitignore and all working files remain untouched.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / ".harness" / "work" / "CRM-GIT-001.inventory.json"
FINAL_CLASSIFICATION = ROOT / ".harness" / "work" / "CRM-GIT-001.final-classification.json"
EXCLUDE = ROOT / ".git" / "info" / "exclude"
BACKUP = ROOT / ".harness" / "work" / "CRM-GIT-001.git-info-exclude.before"
BEGIN = "# BEGIN CRM-GIT-001 managed local excludes"
END = "# END CRM-GIT-001 managed local excludes"
OBSIDIAN_JUNCTIONS = {
    "/obsidian/connectors/",
    "/obsidian/coordination/",
    "/obsidian/core/",
    "/obsidian/docs/",
    "/obsidian/modules/",
}
COLLAPSED_DIRS = {
    ".codex": "/.codex/",
    "_docs_out": "/_docs_out/",
    "_sales-mockups-share": "/_sales-mockups-share/",
}


def managed_paths() -> list[str]:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    selected: set[str] = set(OBSIDIAN_JUNCTIONS)
    for item in payload["records"]:
        if item.get("scope") != "root":
            continue
        path = str(item["path"]).replace("\\", "/")
        if item.get("group") == "artifacts" or item.get("disposition") == "retain-ignore-candidate":
            first = path.split("/", 1)[0]
            selected.add(COLLAPSED_DIRS.get(first, "/" + path))
    if FINAL_CLASSIFICATION.exists():
        final_payload = json.loads(FINAL_CLASSIFICATION.read_text(encoding="utf-8"))
        for item in final_payload["records"]:
            if item.get("action") == "retain-local":
                selected.add("/" + str(item["path"]).replace("\\", "/"))
    return sorted(selected)


def strip_managed_block(text: str) -> str:
    lines = text.splitlines()
    output: list[str] = []
    inside = False
    for line in lines:
        if line == BEGIN:
            inside = True
            continue
        if line == END:
            inside = False
            continue
        if not inside:
            output.append(line)
    return "\n".join(output).rstrip() + "\n"


def main() -> None:
    original = EXCLUDE.read_text(encoding="utf-8")
    if not BACKUP.exists():
        BACKUP.write_text(original, encoding="utf-8")
    block = "\n".join([BEGIN, *managed_paths(), END]) + "\n"
    EXCLUDE.write_text(strip_managed_block(original) + "\n" + block, encoding="utf-8")
    print(f"installed={len(managed_paths())}")
    print(f"backup={BACKUP.relative_to(ROOT).as_posix()}")
    for name in ("finance", "marketing", "procurement"):
        submodule = ROOT / "modules" / name
        exclude_path = Path(
            subprocess.check_output(
                ["git", "rev-parse", "--path-format=absolute", "--git-path", "info/exclude"],
                cwd=submodule,
                text=True,
            ).strip()
        )
        sub_original = exclude_path.read_text(encoding="utf-8")
        sub_backup = ROOT / ".harness" / "work" / f"CRM-GIT-001.{name}.git-info-exclude.before"
        if not sub_backup.exists():
            sub_backup.write_text(sub_original, encoding="utf-8")
        sub_block = "\n".join([BEGIN, "__pycache__/", "*.py[cod]", END]) + "\n"
        exclude_path.write_text(strip_managed_block(sub_original) + "\n" + sub_block, encoding="utf-8")
        print(f"submodule={name} backup={sub_backup.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
