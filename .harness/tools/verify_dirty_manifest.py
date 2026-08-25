"""Verify that the protected CRM-GIT-001 inventory still exists unchanged."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / ".harness" / "work" / "CRM-GIT-001.inventory.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    checked = 0
    failures: list[str] = []
    for item in payload["records"]:
        if item.get("kind") != "file" or item.get("group") == "goal-control":
            continue
        checked += 1
        path = ROOT / item["path"]
        if not path.is_file():
            failures.append(f"missing:{item['path']}")
        elif sha256_file(path) != item["sha256"]:
            failures.append(f"changed:{item['path']}")
    print(f"checked={checked}")
    print(f"failures={len(failures)}")
    for failure in failures[:20]:
        print(failure)
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
