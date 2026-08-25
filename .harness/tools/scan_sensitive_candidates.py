"""Report sensitive-data indicators without printing matched values.

The scan is read-only and covers currently changed text files outside Goal
control. It intentionally reports only path, line number, and indicator name.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / ".harness" / "work" / "CRM-GIT-001.sensitive-scan.json"
MAX_BYTES = 10 * 1024 * 1024
BINARY_SUFFIXES = {
    ".avif", ".doc", ".docx", ".gif", ".ico", ".jpeg", ".jpg",
    ".pdf", ".png", ".ppt", ".pptx", ".webp", ".xls", ".xlsx", ".zip",
}
PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    "bearer-token": re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.I),
    "credential-assignment": re.compile(
        r"(?i)\b(?:api[_-]?key|client[_-]?secret|password|passwd|token|auth[_-]?key)\b"
        r"\s*[:=]\s*['\"]?(?!example|placeholder|change[_-]?me|<|\$\{|\*{3})[^\s'\"]{8,}"
    ),
    "email": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    "belarus-phone": re.compile(r"(?<!\d)(?:\+?375|80)[\s()\-]*\d{2}[\s()\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)"),
}


def changed_paths() -> list[str]:
    raw = subprocess.check_output(
        ["git", "-c", "core.quotepath=false", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=ROOT,
    )
    return [os.fsdecode(item[3:]).replace("\\", "/") for item in raw.split(b"\0") if item]


def main() -> None:
    findings: list[dict[str, object]] = []
    scanned = 0
    skipped = Counter()
    for relative in changed_paths():
        if relative.startswith(".harness/"):
            skipped["goal-control"] += 1
            continue
        path = ROOT / relative
        if not path.is_file():
            skipped["not-file"] += 1
            continue
        if path.suffix.lower() in BINARY_SUFFIXES:
            skipped["binary-suffix"] += 1
            continue
        if path.stat().st_size > MAX_BYTES:
            skipped["too-large"] += 1
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            skipped["non-utf8"] += 1
            continue
        scanned += 1
        for line_no, line in enumerate(text.splitlines(), start=1):
            for indicator, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append({"path": relative, "line": line_no, "indicator": indicator})
    payload = {
        "schemaVersion": 1,
        "chainId": "CRM-GIT-001",
        "redacted": True,
        "scannedTextFiles": scanned,
        "skipped": dict(sorted(skipped.items())),
        "findingCounts": dict(sorted(Counter(item["indicator"] for item in findings).items())),
        "findings": findings,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in ("scannedTextFiles", "skipped", "findingCounts")}, ensure_ascii=False, indent=2))
    for item in findings:
        print(f"{item['indicator']}\t{item['path']}:{item['line']}")


if __name__ == "__main__":
    main()
