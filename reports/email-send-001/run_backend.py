"""Disjoint full-suite groups with separate coverage data; synthetic local DB only."""

import concurrent.futures
import json
import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
os.chdir(root)
out = root / "reports/email-send-001"
files = sorted(
    (p for p in Path("tests").rglob("test_*.py") if "integration" not in p.parts),
    key=lambda p: p.stat().st_size,
    reverse=True,
)
groups, sizes = [[] for _ in range(4)], [0] * 4
for path in files:
    index = sizes.index(min(sizes))
    groups[index].append(str(path))
    sizes[index] += path.stat().st_size
groups.append(["tests/integration"])
(out / "test-groups.json").write_text(json.dumps(groups, indent=2), encoding="utf-8")


def run(index):
    env = dict(
        os.environ, PYTHONDONTWRITEBYTECODE="1", COVERAGE_FILE=str(out / f".coverage.part{index}")
    )
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *groups[index],
        "-q",
        "--tb=short",
        "--cov",
        "--cov-report=",
        f"--junitxml={out / f'backend-part{index}.xml'}",
        "--durations=5",
    ]
    with (out / f"backend-part{index}.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(cmd, env=env, stdout=log, stderr=subprocess.STDOUT)
    print(f"Group {index}: exit {result.returncode}", flush=True)
    return {"group": index, "exit_code": result.returncode, "files": len(groups[index])}


with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
    results = list(pool.map(run, range(5)))
(out / "backend-results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
env = dict(os.environ, COVERAGE_FILE=str(out / ".coverage.combined"))
subprocess.run(
    [
        sys.executable,
        "-m",
        "coverage",
        "combine",
        "--keep",
        *[str(out / f".coverage.part{i}") for i in range(5)],
    ],
    env=env,
    check=True,
)
subprocess.run(
    [sys.executable, "-m", "coverage", "xml", "-o", str(out / "coverage.xml")], env=env, check=True
)
with (out / "coverage.log").open("w", encoding="utf-8") as log:
    gate = subprocess.run(
        [sys.executable, "-m", "coverage", "report", "--precision=2", "--fail-under=90"],
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
print("Coverage gate:", gate.returncode, flush=True)
sys.exit(max([r["exit_code"] for r in results] + [gate.returncode]))
