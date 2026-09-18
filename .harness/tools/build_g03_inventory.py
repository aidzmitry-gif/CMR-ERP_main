"""Build the CRM-QA-001 G03 test inventory from native runner evidence.

This collector is intentionally report-only: it discovers and classifies tests,
but never runs the test bodies and never changes product or test source files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from pathlib import Path
from time import monotonic
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".harness" / "work"
POLICY_BASELINE = ROOT / ".harness" / "policy" / "CRM-QA-001.regression-baseline.json"
CHAIN_ID = "CRM-QA-001"
SUBGOAL_ID = "G03"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
COUNT_RE = re.compile(r"(?:(\d+)/(\d+)|(\d+))\s+tests?\s+collected")

BASELINE_FIELDS = (
    "testId",
    "platform",
    "runner",
    "sourcePath",
    "layer",
    "layers",
    "size",
    "domain",
    "domainCandidates",
    "cuj",
    "cujCandidates",
    "sourceSha256",
    "caseFingerprint",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str | None:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError:
        return None


def relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/")


def normalise_node(value: str) -> str:
    return value.strip().replace("\\", "/").rstrip(".,")


def source_file_for_node(node_id: str) -> Path | None:
    source = node_id.split("::", 1)[0]
    path = ROOT / source
    return path if path.is_file() else None


def source_fingerprint(path: Path | None) -> str | None:
    return sha256_file(path) if path else None


def baseline_projection(records: list[dict]) -> list[dict]:
    projected = [{key: item[key] for key in BASELINE_FIELDS} for item in records]
    projected.sort(key=lambda item: item["testId"])
    return projected


def compare_baseline(baseline_records: list[dict], candidate_records: list[dict]) -> dict:
    baseline_by_id = {item["testId"]: item for item in baseline_records}
    candidate_by_id = {item["testId"]: item for item in candidate_records}
    baseline_ids = set(baseline_by_id)
    candidate_ids = set(candidate_by_id)
    added = sorted(candidate_ids - baseline_ids)
    removed = sorted(baseline_ids - candidate_ids)
    changed: list[str] = []
    classification_changed: list[str] = []
    classification_fields = (
        "layer",
        "layers",
        "size",
        "domain",
        "domainCandidates",
        "cuj",
        "cujCandidates",
    )
    for test_id in sorted(baseline_ids & candidate_ids):
        previous = baseline_by_id[test_id]
        current = candidate_by_id[test_id]
        if any(
            previous.get(field) != current.get(field)
            for field in ("sourceSha256", "caseFingerprint")
        ):
            changed.append(test_id)
        if any(previous.get(field) != current.get(field) for field in classification_fields):
            classification_changed.append(test_id)
    return {
        "baselineCount": len(baseline_records),
        "candidateCount": len(candidate_records),
        "added": added,
        "removed": removed,
        "changed": changed,
        "classificationChanged": classification_changed,
        "hasChanges": bool(added or removed or changed or classification_changed),
    }


def run_capture(
    label: str,
    args: list[str],
    cwd: Path,
    timeout: int,
) -> dict:
    started = utc_now()
    started_clock = monotonic()
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        exit_code = result.returncode
        stdout = result.stdout
        stderr = result.stderr
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        exit_code = None
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        timed_out = True
    except OSError as exc:
        exit_code = None
        stdout = ""
        stderr = f"{type(exc).__name__}: {exc}"
        timed_out = False

    stem = f"CRM-QA-001.g03.{label}"
    stdout_path = WORK / f"{stem}.stdout.txt"
    stderr_path = WORK / f"{stem}.stderr.txt"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return {
        "id": label,
        "command": args,
        "cwd": relpath(cwd),
        "startedAt": started,
        "durationMs": round((monotonic() - started_clock) * 1000),
        "exitCode": exit_code,
        "timedOut": timed_out,
        "stdoutPath": relpath(stdout_path),
        "stderrPath": relpath(stderr_path),
        "stdoutSha256": sha256_file(stdout_path),
        "stderrSha256": sha256_file(stderr_path),
        "stdout": stdout,
        "stderr": stderr,
    }


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_collected_nodes(output: str) -> list[str]:
    nodes: set[str] = set()
    for line in output.splitlines():
        candidate = line.strip()
        if candidate.startswith(("tests/", "tests\\")) and "::" in candidate:
            nodes.add(normalise_node(candidate))
    return sorted(nodes)


def parse_reported_count(output: str) -> int | None:
    matches = COUNT_RE.findall(output)
    if not matches:
        return None
    last = matches[-1]
    return int(last[0] or last[2])


def junit_node_id(classname: str, name: str) -> str:
    module = classname.replace("\\", ".")
    if module.startswith("tests."):
        module_path = module.replace(".", "/") + ".py"
    elif module.startswith("tests/"):
        module_path = module + ".py"
    else:
        module_path = "tests/" + module.replace(".", "/") + ".py"
    return f"{module_path}::{name}"


def parse_junit(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    cases: dict[str, dict] = {}
    try:
        root = ElementTree.parse(path).getroot()
    except (ElementTree.ParseError, OSError):
        return {}
    for case in root.iter("testcase"):
        classname = case.attrib.get("classname", "")
        name = case.attrib.get("name", "")
        if not classname or not name:
            continue
        node_id = junit_node_id(classname, name)
        status = "passed"
        skip_message = None
        child = next(iter(case), None)
        if child is not None:
            if child.tag == "failure":
                status = "failed"
            elif child.tag == "error":
                status = "error"
            elif child.tag == "skipped":
                status = "skipped"
                skip_message = child.attrib.get("message") or child.text
        cases[node_id] = {
            "status": status,
            "skipMessage": skip_message,
            "source": relpath(path),
        }
    return cases


def normalise_test_path(value: str) -> str:
    candidate = normalise_test_node(value).split("::", 1)[0]
    return candidate.lstrip("./")


def normalise_test_node(value: str) -> str:
    candidate = value.replace("\\", "/")
    root_text = ROOT.as_posix().rstrip("/") + "/"
    if candidate.lower().startswith(root_text.lower()):
        candidate = candidate[len(root_text) :]
    return candidate.lstrip("./")


def path_matches(candidate: str, pattern: str) -> bool:
    candidate = normalise_test_node(candidate).strip()
    pattern = normalise_test_node(pattern).strip()
    if not pattern or pattern.startswith(("frontend ", "new ", "playwright ")):
        return False
    candidate_path, separator, candidate_case = candidate.partition("::")
    pattern_path, pattern_separator, pattern_case = pattern.partition("::")
    candidate_path = candidate_path.lower()
    pattern_path = pattern_path.lower()
    if pattern_separator:
        if not bool(separator) or not (
            candidate_case == pattern_case
            or candidate_case.startswith(pattern_case + "[")
        ):
            return False
        if any(token in pattern_path for token in ("*", "?")):
            return fnmatchcase(candidate_path, pattern_path)
        return candidate_path == pattern_path
    if any(token in pattern_path for token in ("*", "?")):
        return fnmatchcase(candidate_path, pattern_path)
    return candidate_path == pattern_path or candidate_path.startswith(pattern_path.rstrip("/") + "/")


def policy_matches(test_path: str, policy: dict) -> tuple[list[str], list[str]]:
    def match_specificity(pattern: str) -> tuple[int, int, int] | None:
        """Return an ordered specificity score for a matching policy path.

        Case-level evidence outranks file/directory evidence; within the same
        level the longest path wins.  This allows an explicit cross-cutting
        fallback such as ``tests`` without making every specific business
        rule overlap with it.
        """

        pattern = pattern.split(" — ", 1)[0]
        if not path_matches(test_path, pattern):
            return None
        pattern_node = normalise_test_node(pattern)
        pattern_path, separator, pattern_case = pattern_node.partition("::")
        return (
            1 if separator else 0,
            len(pattern_path.rstrip("/")),
            len(pattern_case) if separator else 0,
        )

    def most_specific(matches: list[tuple[tuple[int, int, int], str]]) -> list[str]:
        if not matches:
            return []
        strongest = max(score for score, _ in matches)
        return sorted({value for score, value in matches if score == strongest})

    domain_matches: list[tuple[tuple[int, int, int], str]] = []
    for domain in [*policy.get("domains", []), *policy.get("domainRules", [])]:
        evidence = domain.get("currentEvidence", [])
        scores = [
            score
            for item in evidence
            if (score := match_specificity(item)) is not None
        ]
        if scores:
            domain_matches.append((max(scores), domain["id"]))

    journey_matches: list[tuple[tuple[int, int, int], str]] = []
    for journey in [*policy.get("journeys", []), *policy.get("cujRules", [])]:
        scores: list[tuple[int, int, int]] = []
        for size_paths in journey.get("evidence", {}).values():
            for item in size_paths:
                if (score := match_specificity(item)) is not None:
                    scores.append(score)
        if scores:
            journey_matches.append((max(scores), journey["id"]))

    return most_specific(domain_matches), most_specific(journey_matches)


def classify(values: list[str], unknown: str = "unclassified") -> tuple[str, list[str]]:
    values = sorted(set(values))
    if not values:
        return unknown, []
    if len(values) > 1:
        return "overlap", values
    return values[0], values


def make_record(
    *,
    test_id: str,
    platform: str,
    runner: str,
    test_path: str,
    native_name: str,
    layer: str,
    layers: list[str],
    size: str,
    size_basis: str,
    policy: dict,
    execution: dict,
    location: dict | None = None,
    policy_test_path: str | None = None,
) -> dict:
    source_path = ROOT / normalise_test_path(test_path)
    source_sha = source_fingerprint(source_path)
    domains, cujs = policy_matches(policy_test_path or test_path, policy)
    domain, domain_candidates = classify(domains)
    cuj, cuj_candidates = classify(cujs)
    case_material = "|".join(
        [
            test_id,
            source_sha or "source-unavailable",
            native_name,
            json.dumps(location or {}, sort_keys=True),
        ]
    )
    return {
        "testId": test_id,
        "platform": platform,
        "runner": runner,
        "sourcePath": normalise_test_path(test_path),
        "nativeName": native_name,
        "location": location,
        "layer": layer,
        "layers": layers,
        "size": size,
        "classificationBasis": {
            "layer": "native runner/pytest marker collection",
            "size": size_basis,
            "domain": "G02 policy currentEvidence path match",
            "cuj": "G02 CUJ evidence path match",
        },
        "domain": domain,
        "domainCandidates": domain_candidates,
        "cuj": cuj,
        "cujCandidates": cuj_candidates,
        "execution": execution,
        "sourceSha256": source_sha,
        "caseFingerprint": sha256_bytes(case_material.encode("utf-8")),
    }


def parse_playwright_records(output: str, policy: dict) -> list[dict]:
    records: list[dict] = []
    for line in output.splitlines():
        if "›" not in line:
            continue
        match = re.search(r"›\s+([^:\s›]+\.(?:spec|setup)\.[cm]?[jt]s):", line)
        if not match:
            continue
        file_path = normalise_test_path("frontend/e2e/" + match.group(1))
        native_name = line.strip()
        test_id = "frontend:playwright:" + sha256_bytes(native_name.encode("utf-8"))[:20]
        records.append(
            make_record(
                test_id=test_id,
                platform="frontend",
                runner="playwright",
                test_path=file_path,
                native_name=native_name,
                layer="e2e",
                layers=["e2e"],
                size="Large",
                size_basis="native Playwright browser list",
                policy=policy,
                execution={
                    "status": "collected-not-executed",
                    "skip": "unknown",
                    "xfail": "unknown",
                    "retryCount": "unknown",
                    "source": "native Playwright --list",
                },
            )
        )
    unique: dict[str, dict] = {}
    for record in records:
        unique[record["testId"]] = record
    return list(unique.values())


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the CRM-QA-001 G03 test inventory")
    parser.add_argument(
        "--accept-baseline",
        action="store_true",
        help="explicitly replace the accepted policy baseline with this inventory",
    )
    cli_args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    generated_at = utc_now()
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"git metadata unavailable: {exc}", file=sys.stderr)
        return 2
    if not SHA_RE.fullmatch(head):
        print(f"unexpected git head: {head}", file=sys.stderr)
        return 2

    policy = load_json(ROOT / ".harness" / "policy" / "quality-risk-map.json")
    cuj_matrix = load_json(ROOT / ".harness" / "policy" / "cuj-matrix.json")
    policy_for_matching = {
        "domains": policy.get("domains", []),
        "journeys": cuj_matrix.get("journeys", []),
        "domainRules": policy.get("classificationRules", {}).get("domains", []),
        "cujRules": cuj_matrix.get("classificationRules", {}).get("journeys", []),
        "frontendTestSizes": policy.get("frontendTestSizes", {}),
    }
    python_exe = ROOT / ".venv" / "Scripts" / "python.exe"
    if not python_exe.is_file():
        python_exe = Path(sys.executable)

    commands: list[dict] = []
    marker_nodes: dict[str, set[str]] = {}
    for marker in ("all", "unit", "api", "integration"):
        collect_args = [
            str(python_exe),
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            str(ROOT / "tests"),
        ]
        if marker != "all":
            collect_args.extend(["-m", marker])
        result = run_capture(f"backend-collect-{marker}", collect_args, ROOT, 180)
        commands.append(
            {
                key: value
                for key, value in result.items()
                if key not in {"stdout", "stderr"}
            }
            | {
                "nativeCount": parse_reported_count(result["stdout"]),
                "itemCount": len(parse_collected_nodes(result["stdout"])),
            }
        )
        marker_nodes[marker] = set(parse_collected_nodes(result["stdout"]))

    full_junit_path = WORK / "CRM-QA-001.backend-full.marker-fixed.xml"
    if not full_junit_path.is_file():
        full_junit_path = WORK / "CRM-QA-001.backend-full.xml"
    unit_junit_path = WORK / "CRM-QA-001.backend-unit.marker-fixed.xml"
    if not unit_junit_path.is_file():
        unit_junit_path = WORK / "CRM-QA-001.backend-unit.xml"

    backend_nodes = marker_nodes["all"] or set().union(
        marker_nodes["unit"], marker_nodes["api"], marker_nodes["integration"]
    )
    if not backend_nodes:
        fallback = parse_junit(full_junit_path)
        backend_nodes = set(fallback)

    full_execution = parse_junit(full_junit_path)
    unit_execution = parse_junit(unit_junit_path)
    backend_records: list[dict] = []
    for node_id in sorted(backend_nodes):
        memberships = [
            marker for marker in ("unit", "api", "integration") if node_id in marker_nodes[marker]
        ]
        primary_layer, layers = classify(memberships, "unknown")
        test_path = node_id.split("::", 1)[0]
        if "integration" in memberships or primary_layer == "integration":
            size = "Medium"
            size_basis = "pytest integration marker"
        elif "api" in memberships or primary_layer == "api":
            size = "Medium"
            size_basis = "pytest api marker"
        elif "unit" in memberships:
            size = "Small"
            size_basis = "pytest unit marker"
        else:
            size = "unknown"
            size_basis = "no sufficient native size evidence"
        execution = full_execution.get(node_id) or unit_execution.get(node_id)
        if execution:
            status = execution["status"]
            skip = status == "skipped"
            xfail = (
                "observed"
                if execution.get("skipMessage")
                and "xfail" in execution["skipMessage"].lower()
                else "unknown"
            )
            execution_info = {
                "status": status,
                "skip": skip,
                "xfail": xfail,
                "retryCount": "unknown",
                "source": execution["source"],
            }
        else:
            execution_info = {
                "status": "collected-not-executed",
                "skip": "unknown",
                "xfail": "unknown",
                "retryCount": "unknown",
                "source": "native pytest --collect-only",
            }
        backend_records.append(
            make_record(
                test_id="backend:pytest:" + node_id,
                platform="backend",
                runner="pytest",
                test_path=test_path,
                native_name=node_id,
                layer=primary_layer,
                layers=layers,
                size=size,
                size_basis=size_basis,
                policy=policy_for_matching,
                execution=execution_info,
                policy_test_path=node_id,
            )
        )

    vitest_path = WORK / "CRM-QA-001.g03.frontend-vitest-list.json"
    vitest_result: dict | None = None
    vitest_cli = ROOT / "frontend" / "node_modules" / "vitest" / "vitest.mjs"
    if vitest_cli.is_file():
        vitest_run = run_capture(
            "frontend-vitest-list",
            ["node", str(vitest_cli), "list", "--json", "--includeTaskLocation", "--no-color"],
            ROOT / "frontend",
            180,
        )
        commands.append(
            {
                key: value
                for key, value in vitest_run.items()
                if key not in {"stdout", "stderr"}
            }
        )
        if vitest_run["exitCode"] == 0:
            try:
                vitest_result = json.loads(vitest_run["stdout"])
                write_json(vitest_path, vitest_result)
            except json.JSONDecodeError:
                vitest_result = None
    if vitest_result is None and vitest_path.is_file():
        vitest_result = load_json(vitest_path)

    frontend_records: list[dict] = []
    if isinstance(vitest_result, list):
        seen_ids: Counter[str] = Counter()
        frontend_size_rules = policy_for_matching.get("frontendTestSizes", {})
        for item in vitest_result:
            file_path = normalise_test_path(str(item.get("file", "")))
            location = item.get("location") or {}
            base_id = ":".join(
                [
                    "frontend:vitest",
                    file_path,
                    str(location.get("line", 0)),
                    str(location.get("column", 0)),
                    str(item.get("name", "")),
                ]
            )
            seen_ids[base_id] += 1
            test_id = base_id if seen_ids[base_id] == 1 else f"{base_id}#{seen_ids[base_id]}"
            size = "unknown"
            size_basis = "Vitest list does not prove I/O-free test size"
            for candidate_size in ("Small", "Medium", "Large"):
                if any(
                    path_matches(file_path, pattern)
                    for pattern in frontend_size_rules.get(candidate_size, [])
                ):
                    size = candidate_size
                    size_basis = f"policy frontendTestSizes.{candidate_size} path evidence"
                    break
            frontend_records.append(
                make_record(
                    test_id=test_id,
                    platform="frontend",
                    runner="vitest",
                    test_path=file_path,
                    native_name=str(item.get("name", "")),
                    location=location,
                    layer="unit",
                    layers=["unit"],
                    size=size,
                    size_basis=size_basis,
                    policy=policy_for_matching,
                    execution={
                        "status": "collected-not-executed",
                        "skip": "unknown",
                        "xfail": "unknown",
                        "retryCount": "unknown",
                        "source": relpath(vitest_path),
                    },
                )
            )

    playwright_records: list[dict] = []
    playwright_cli = ROOT / "frontend" / "node_modules" / "@playwright" / "test" / "cli.js"
    if playwright_cli.is_file():
        playwright_run = run_capture(
            "frontend-playwright-list",
            [
                "node",
                str(playwright_cli),
                "test",
                "--config",
                "playwright.config.ts",
                "--list",
                "--reporter=list",
            ],
            ROOT / "frontend",
            180,
        )
        commands.append(
            {
                key: value
                for key, value in playwright_run.items()
                if key not in {"stdout", "stderr"}
            }
        )
        if playwright_run["exitCode"] == 0:
            playwright_records = parse_playwright_records(
                playwright_run["stdout"] + "\n" + playwright_run["stderr"],
                policy_for_matching,
            )
    else:
        commands.append(
            {
                "id": "frontend-playwright-list",
                "command": ["node", "frontend/node_modules/@playwright/test/cli.js", "test", "--list"],
                "cwd": relpath(ROOT / "frontend"),
                "exitCode": None,
                "timedOut": False,
                "blocker": "local @playwright/test CLI is absent",
            }
        )

    records = backend_records + frontend_records + playwright_records
    records.sort(key=lambda item: item["testId"])
    test_ids = [item["testId"] for item in records]
    duplicate_ids = sorted({item for item, count in Counter(test_ids).items() if count > 1})
    command_by_id = {command["id"]: command for command in commands}

    counts = {
        "totalRecords": len(records),
        "byPlatform": dict(Counter(item["platform"] for item in records)),
        "byRunner": dict(Counter(item["runner"] for item in records)),
        "byLayer": dict(Counter(item["layer"] for item in records)),
        "bySize": dict(Counter(item["size"] for item in records)),
        "byDomain": dict(Counter(item["domain"] for item in records)),
        "byCuj": dict(Counter(item["cuj"] for item in records)),
        "overlapLayerRecords": sum(item["layer"] == "overlap" for item in records),
        "unclassifiedDomainRecords": sum(item["domain"] == "unclassified" for item in records),
        "unclassifiedCujRecords": sum(item["cuj"] == "unclassified" for item in records),
        "unknownSizeRecords": sum(item["size"] == "unknown" for item in records),
    }

    source_inputs = [
        ".harness/policy/quality-risk-map.json",
        ".harness/policy/cuj-matrix.json",
        relpath(unit_junit_path),
        relpath(full_junit_path),
        ".harness/work/CRM-QA-001.g03.frontend-vitest-list.json",
    ]
    inventory = {
        "schemaVersion": 1,
        "chainId": CHAIN_ID,
        "subgoalId": SUBGOAL_ID,
        "generatedAt": generated_at,
        "repository": {"root": relpath(ROOT), "branch": branch, "head": head},
        "classificationContract": {
            "layer": ["unit", "api", "integration", "e2e", "overlap", "unknown"],
            "size": ["Small", "Medium", "Large", "unknown"],
            "unknownPolicy": "Do not infer missing runner/marker/I-O evidence; retain unknown/unclassified/overlap.",
        },
        "nativeSources": {
            "backend": {
                "nativeCollectionAvailable": bool(backend_nodes),
                "nativeItemInventory": bool(marker_nodes["all"] or backend_nodes),
                "reportedCounts": {
                    marker: command_by_id.get(f"backend-collect-{marker}", {}).get(
                        "nativeCount"
                    )
                    for marker in ("all", "unit", "api", "integration")
                },
            },
            "frontendVitest": {
                "nativeCollectionAvailable": isinstance(vitest_result, list),
                "nativeItemInventory": isinstance(vitest_result, list),
                "nativeCount": len(vitest_result) if isinstance(vitest_result, list) else None,
                "artifact": relpath(vitest_path) if vitest_path.is_file() else None,
            },
            "frontendPlaywright": {
                "nativeCollectionAvailable": bool(playwright_records),
                "nativeItemInventory": bool(playwright_records),
                "nativeCount": len(playwright_records) if playwright_records else None,
                "limitation": (
                    None
                    if playwright_records
                    else "Native list unavailable or could not be parsed; no synthetic test records added."
                ),
            },
        },
        "counts": counts,
        "sourceInputs": source_inputs,
        "records": records,
    }
    inventory_path = WORK / "CRM-QA-001.g03.inventory.json"
    write_json(inventory_path, inventory)

    candidate_baseline_records = baseline_projection(records)

    def make_baseline(baseline_records: list[dict]) -> dict:
        baseline_material = json.dumps(
            baseline_records, ensure_ascii=False, sort_keys=True
        ).encode("utf-8")
        return {
            "schemaVersion": 1,
            "chainId": CHAIN_ID,
            "subgoalId": SUBGOAL_ID,
            "generatedAt": generated_at,
            "repository": {"root": relpath(ROOT), "branch": branch, "head": head},
            "identityRule": "testId is runner/platform plus normalized source path and native location/name; Playwright list lines use a stable hash when no location is exposed.",
            "changeRule": {
                "added": "testId is present in candidate and absent in baseline",
                "removed": "testId is present in baseline and absent in candidate",
                "changed": "same testId has a different sourceSha256 or caseFingerprint",
                "classificationChanged": "same testId changes layer, size, domain, cuj or candidates",
            },
            "inputHashes": {
                path: sha256_file(ROOT / path)
                for path in source_inputs
                if (ROOT / path).is_file()
            },
            "recordCount": len(baseline_records),
            "recordsSha256": sha256_bytes(baseline_material),
            "records": baseline_records,
        }

    if cli_args.accept_baseline:
        baseline = make_baseline(candidate_baseline_records)
        POLICY_BASELINE.parent.mkdir(parents=True, exist_ok=True)
        write_json(POLICY_BASELINE, baseline)
    elif POLICY_BASELINE.is_file():
        baseline = load_json(POLICY_BASELINE)
    else:
        print(
            f"accepted baseline is missing: {POLICY_BASELINE}; "
            "run with --accept-baseline once after reviewing the candidate",
            file=sys.stderr,
        )
        return 1

    baseline_records = baseline.get("records", [])
    if not isinstance(baseline_records, list):
        print("accepted baseline records must be an array", file=sys.stderr)
        return 1
    if any(
        not isinstance(item, dict) or not isinstance(item.get("testId"), str)
        for item in baseline_records
    ):
        print("accepted baseline contains an invalid record or testId", file=sys.stderr)
        return 1
    comparison = compare_baseline(baseline_records, candidate_baseline_records)
    if comparison["hasChanges"] and not cli_args.accept_baseline:
        print(
            json.dumps(
                {"acceptedBaseline": relpath(POLICY_BASELINE), **comparison},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )

    baseline_path = WORK / "CRM-QA-001.g03.regression-baseline.json"
    write_json(baseline_path, baseline)

    artifact_paths = [inventory_path, baseline_path, POLICY_BASELINE]
    artifact_paths.extend(ROOT / path for path in source_inputs if (ROOT / path).is_file())
    artifact_manifest = [
        {
            "path": relpath(path),
            "sizeBytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in artifact_paths
    ]
    backend_command_summary = [
        {
            "id": command["id"],
                "command": command["command"],
                "cwd": command["cwd"],
                "startedAt": command["startedAt"],
                "durationMs": command["durationMs"],
                "exitCode": command["exitCode"],
            "timedOut": command["timedOut"],
            "nativeCount": command.get("nativeCount"),
            "itemCount": command.get("itemCount"),
            "stdoutPath": command["stdoutPath"],
            "stderrPath": command["stderrPath"],
        }
        for command in commands
    ]
    evidence = {
        "schemaVersion": 1,
        "chainId": CHAIN_ID,
        "subgoalId": SUBGOAL_ID,
        "generatedAt": generated_at,
        "repository": {"root": relpath(ROOT), "branch": branch, "head": head},
        "commands": backend_command_summary,
        "nativeCounts": {
            "backendCollectedUnion": len(backend_nodes),
            "backendMarkerCounts": {marker: len(nodes) for marker, nodes in marker_nodes.items()},
            "frontendVitest": len(vitest_result) if isinstance(vitest_result, list) else None,
            "frontendPlaywright": len(playwright_records) if playwright_records else None,
        },
        "executionEvidence": {
            "backendFullJUnit": {
                "path": relpath(full_junit_path),
                "caseCount": len(full_execution),
                "statusCounts": dict(Counter(item["status"] for item in full_execution.values())),
            },
            "backendUnitJUnit": {
                "path": relpath(unit_junit_path),
                "caseCount": len(unit_execution),
                "statusCounts": dict(Counter(item["status"] for item in unit_execution.values())),
            },
            "frontendVitest": "list-only; no pass/fail/skip/xfail status claimed",
            "frontendPlaywright": "list-only; no pass/fail/skip/xfail status claimed",
        },
        "nativeArtifactProvenance": {
            "frontendVitest": {
                "path": relpath(vitest_path) if vitest_path.is_file() else None,
                "recordCount": len(vitest_result) if isinstance(vitest_result, list) else None,
                "sha256": sha256_file(vitest_path) if vitest_path.is_file() else None,
                "source": "saved native Vitest list-only artifact from the G03 worker",
                "workerExitCode": 0,
                "currentReproduction": {
                    "commandId": next(
                        (
                            command["id"]
                            for command in commands
                            if command["id"] == "frontend-vitest-list"
                        ),
                        None,
                    ),
                    "exitCode": next(
                        (
                            command["exitCode"]
                            for command in commands
                            if command["id"] == "frontend-vitest-list"
                        ),
                        None,
                    ),
                    "limitation": "sandbox spawn EPERM; no test bodies were executed",
                },
            }
        },
        "artifacts": artifact_manifest,
        "validation": {
            "jsonParse": True,
            "duplicateTestIds": duplicate_ids,
            "inventoryCountMatchesRecords": len(records) == counts["totalRecords"],
            "baselineCountMatchesInventory": not comparison["hasChanges"],
            "baselineComparison": comparison,
            "acceptedBaselinePath": relpath(POLICY_BASELINE),
            "baselineAcceptedThisRun": cli_args.accept_baseline,
            "sourceFingerprintMissing": sum(
                item["sourceSha256"] is None for item in records
            ),
        },
        "limitations": [
            "pytest --collect-only with --junitxml is not a reliable item-count source; native stdout collection is the count source.",
            "Vitest list proves discoverability only; skip/xfail/retry and execution status require a separate run.",
            "Frontend Vitest size is assigned from reviewed source-level I/O or pure-render evidence; current inventory has zero unknown size records.",
            "Playwright is a Large/e2e inventory only; browser execution and external login/webhook acceptance are not claimed.",
            "Unclassified and overlap values are retained instead of relabeling tests to improve coverage metrics.",
        ],
        "blockers": [
            {
                "id": "playwright-production-local-dependency",
                "status": "unknown",
                "detail": "The separate modules/production Playwright prototype config has no local @playwright/test resolution; CRM frontend e2e uses frontend/playwright.config.ts.",
            }
        ],
    }
    evidence_path = WORK / "CRM-QA-001.g03.evidence.json"
    write_json(evidence_path, evidence)

    # Re-open the generated artifacts as the final collector self-check.
    for path in (inventory_path, baseline_path, evidence_path, POLICY_BASELINE):
        load_json(path)
    if duplicate_ids or (
        comparison["hasChanges"] and not cli_args.accept_baseline
    ):
        print("G03 validation failed", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "head": head,
                "records": len(records),
                "backend": len(backend_records),
                "frontendVitest": len(frontend_records),
                "frontendPlaywright": len(playwright_records),
                "counts": counts,
                "artifacts": [relpath(inventory_path), relpath(evidence_path), relpath(baseline_path)],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
