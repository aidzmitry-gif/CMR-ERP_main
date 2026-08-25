"""Verify the final CRM-GIT-001 classification without exposing file data."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLASSIFICATION = ROOT / ".harness" / "work" / "CRM-GIT-001.final-classification.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_ok(*args: str) -> bool:
    return subprocess.run(
        ["git", *args], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
    ).returncode == 0


def main() -> None:
    payload = json.loads(CLASSIFICATION.read_text(encoding="utf-8"))
    failures: list[str] = []
    retained = 0
    committed = 0
    for item in payload["records"]:
        relative = str(item["path"])
        path = ROOT / relative
        if item["action"] == "retain-local":
            retained += 1
            if not path.is_file():
                failures.append(f"retained-missing:{relative}")
            elif path.stat().st_size != item["size"] or sha256(path) != item["sha256"]:
                failures.append(f"retained-changed:{relative}")
            if not git_ok("check-ignore", "-q", "--", relative):
                failures.append(f"retained-visible:{relative}")
        elif item["action"] == "commit" and not relative.startswith(".harness/"):
            committed += 1
            if not git_ok("ls-files", "--error-unmatch", "--", relative):
                failures.append(f"commit-not-tracked:{relative}")
    cached = subprocess.check_output(["git", "diff", "--cached", "--name-only"], cwd=ROOT, text=True)
    if cached.strip():
        failures.append("index-not-empty")
    print(f"retained_checked={retained}")
    print(f"committed_checked={committed}")
    print(f"failures={len(failures)}")
    for failure in failures:
        print(failure)
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
