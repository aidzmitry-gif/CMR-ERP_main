"""Validate a pilot accounting package locally, before any ERP import.

The command deliberately has no database, network, queue, or 1C dependency.  It
validates the accountable manifest, declared section ownership, the payroll
source mode, exact referenced files, the opening balance package, and a closed
matching OSV pair. It does not validate the meaning of unstructured files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.accounting.reconciliation import compare  # noqa: E402
from modules.accounting.schemas import ImportInput  # noqa: E402

PROTOCOL_VERSION = "belarus-pilot-input-v3"
REQUIRED_ARTIFACT_KINDS = frozenset({
    "opening_balances",
    "bank_statement",
    "inventory",
    "receivables",
    "vat",
    "fx",
    "primary_documents",
    "osv_left",
    "osv_right",
})
PAYROLL_ARTIFACT_BY_MODE = {
    "external_verified_import": "payroll_register",
    "no_accruals": "payroll_zero_activity",
}
PAYROLL_ARTIFACT_KINDS = frozenset(PAYROLL_ARTIFACT_BY_MODE.values())
RESPONSIBILITY_AREAS = frozenset({
    "sales", "procurement", "bank", "inventory", "settlements", "vat", "fx",
    "production", "repairs", "fixed_assets", "payroll",
})
SUPPORTING_ARTIFACT_KINDS = frozenset({"supporting_calculation"})
ALLOWED_ARTIFACT_KINDS = REQUIRED_ARTIFACT_KINDS | PAYROLL_ARTIFACT_KINDS | SUPPORTING_ARTIFACT_KINDS
SINGLE_ARTIFACT_KINDS = frozenset({"opening_balances", "osv_left", "osv_right"}) | PAYROLL_ARTIFACT_KINDS
EVIDENCE_ROLES = frozenset({"required_evidence", "supporting_calculation"})
SOURCE_CLASSES = frozenset({
    "bank_statement",
    "erp_control_export",
    "external_system_export",
    "official_rate",
    "operational_workbook",
    "primary_document",
    "source_register",
})
REQUIRED_SOURCE_CLASSES: dict[str, frozenset[str]] = {
    "opening_balances": frozenset({"erp_control_export", "external_system_export"}),
    "bank_statement": frozenset({"bank_statement"}),
    "inventory": frozenset({"external_system_export", "source_register"}),
    "receivables": frozenset({"external_system_export", "source_register"}),
    "vat": frozenset({"external_system_export", "source_register"}),
    "fx": frozenset({"official_rate"}),
    "primary_documents": frozenset({"primary_document"}),
    "payroll_register": frozenset({"external_system_export", "source_register"}),
    "payroll_zero_activity": frozenset({"primary_document", "source_register"}),
    "osv_left": frozenset({"erp_control_export", "external_system_export"}),
    "osv_right": frozenset({"erp_control_export", "external_system_export"}),
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MONTH = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")
PLACEHOLDERS = frozenset({"", "-", "n/a", "na", "none", "null", "tbd", "todo", "unknown", "неизвестно"})
MAX_MANIFEST_BYTES = 2_000_000
MAX_STRUCTURED_ARTIFACT_BYTES = 10_000_000


class PreflightError(ValueError):
    """The submitted pilot package is incomplete or internally inconsistent."""


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PreflightError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def _read_json(path: Path, *, limit: int) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PreflightError(f"Cannot read {path.name}") from exc
    if len(raw) > limit:
        raise PreflightError(f"{path.name} exceeds the allowed size")
    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_no_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, PreflightError) as exc:
        raise PreflightError(f"{path.name} must be valid JSON without duplicate fields") from exc
    if not isinstance(value, dict):
        raise PreflightError(f"{path.name} must contain a JSON object")
    return value


def _require_object(value: object, field: str, *, required: set[str], allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PreflightError(f"{field} must be an object")
    missing = sorted(required - value.keys())
    unknown = sorted(value.keys() - allowed)
    if missing:
        raise PreflightError(f"{field} is missing: {', '.join(missing)}")
    if unknown:
        raise PreflightError(f"{field} has unsupported fields: {', '.join(unknown)}")
    return value


def _text(value: object, field: str, *, minimum: int = 1) -> str:
    if not isinstance(value, str):
        raise PreflightError(f"{field} must be confirmed text")
    normalized = value.strip()
    if (len(normalized) < minimum or normalized.casefold() in PLACEHOLDERS
            or (normalized.startswith("<") and normalized.endswith(">"))):
        raise PreflightError(f"{field} must be explicitly confirmed")
    return normalized


def _iso_date(value: object, field: str) -> date:
    text = _text(value, field)
    try:
        result = date.fromisoformat(text)
    except ValueError as exc:
        raise PreflightError(f"{field} must use ISO date YYYY-MM-DD") from exc
    if result.isoformat() != text:
        raise PreflightError(f"{field} must use ISO date YYYY-MM-DD")
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise PreflightError(f"Cannot read {path.name}") from exc
    return digest.hexdigest()


def _relative_file(root: Path, value: object, field: str) -> Path:
    relative = _text(value, field)
    candidate = Path(relative)
    if candidate.is_absolute() or candidate.drive or ".." in candidate.parts:
        raise PreflightError(f"{field} must stay below the manifest directory")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PreflightError(f"{field} must stay below the manifest directory") from exc
    if not resolved.is_file():
        raise PreflightError(f"Artifact file is missing: {relative}")
    return resolved


def _validate_pilot(manifest: dict[str, Any]) -> tuple[str, date]:
    pilot = _require_object(
        manifest["pilot"],
        "pilot",
        required={"month", "cutover_date", "authorization_evidence"},
        allowed={"month", "cutover_date", "authorization_evidence"},
    )
    month = _text(pilot["month"], "pilot.month")
    if not MONTH.fullmatch(month):
        raise PreflightError("pilot.month must use YYYY-MM")
    cutover = _iso_date(pilot["cutover_date"], "pilot.cutover_date")
    if cutover.day != 1 or cutover.strftime("%Y-%m") != month:
        raise PreflightError("pilot.cutover_date must be the first day of pilot.month")
    _text(pilot["authorization_evidence"], "pilot.authorization_evidence", minimum=10)
    return month, cutover


def _validate_identity(manifest: dict[str, Any], cutover: date) -> str:
    organization = _require_object(
        manifest["organization"],
        "organization",
        required={"external_id", "name", "unp"},
        allowed={"external_id", "name", "unp"},
    )
    external_id = _text(organization["external_id"], "organization.external_id")
    _text(organization["name"], "organization.name")
    unp = _text(organization["unp"], "organization.unp")
    if not re.fullmatch(r"[0-9]{9}", unp):
        raise PreflightError("organization.unp must contain 9 digits")

    owners = _require_object(
        manifest["owners"],
        "owners",
        required={"chief_accountant", "accountant", "bank_operator"},
        allowed={"chief_accountant", "accountant", "bank_operator"},
    )
    for key in sorted(owners):
        _text(owners[key], f"owners.{key}")

    policy = _require_object(
        manifest["policy"],
        "policy",
        required={"effective_from", "effective_to", "revision", "order_reference", "responsible_id", "evidence"},
        allowed={"effective_from", "effective_to", "revision", "order_reference", "responsible_id", "evidence"},
    )
    effective_from = _iso_date(policy["effective_from"], "policy.effective_from")
    effective_to = _iso_date(policy["effective_to"], "policy.effective_to")
    if effective_from > effective_to or not effective_from <= cutover <= effective_to:
        raise PreflightError("policy effective period must include pilot.cutover_date")
    for key in ("revision", "order_reference", "responsible_id"):
        _text(policy[key], f"policy.{key}")
    _text(policy["evidence"], "policy.evidence", minimum=10)
    return external_id


def _validate_payroll(manifest: dict[str, Any]) -> tuple[str, str, str]:
    payroll = _require_object(
        manifest["payroll"], "payroll",
        required={"mode", "source_system", "verified_by", "evidence"},
        allowed={"mode", "source_system", "verified_by", "evidence"},
    )
    mode = _text(payroll["mode"], "payroll.mode")
    if mode not in PAYROLL_ARTIFACT_BY_MODE:
        raise PreflightError("payroll.mode requires external_verified_import or no_accruals")
    source_system = _text(payroll["source_system"], "payroll.source_system")
    verified_by = _text(payroll["verified_by"], "payroll.verified_by")
    if verified_by not in {
        manifest["owners"]["chief_accountant"], manifest["owners"]["accountant"],
    }:
        raise PreflightError("payroll.verified_by must identify this pilot's accountant or chief")
    _text(payroll["evidence"], "payroll.evidence", minimum=10)
    return mode, source_system, PAYROLL_ARTIFACT_BY_MODE[mode]


def _validate_responsibility(manifest: dict[str, Any], payroll_mode: str,
                             payroll_source_system: str) -> dict[str, dict[str, str | None]]:
    declared = _require_object(
        manifest["responsibility"], "responsibility",
        required=set(RESPONSIBILITY_AREAS), allowed=set(RESPONSIBILITY_AREAS),
    )
    result: dict[str, dict[str, str | None]] = {}
    for area in sorted(RESPONSIBILITY_AREAS):
        item = _require_object(
            declared[area], f"responsibility.{area}",
            required={"owner", "source_system", "evidence"},
            allowed={"owner", "source_system", "evidence"},
        )
        owner = _text(item["owner"], f"responsibility.{area}.owner")
        if owner not in {"erp", "external", "not_applicable"}:
            raise PreflightError(f"responsibility.{area}.owner is invalid")
        source_system = item["source_system"]
        if owner == "not_applicable":
            if source_system is not None:
                raise PreflightError(f"responsibility.{area}.source_system must be null")
        else:
            source_system = _text(source_system, f"responsibility.{area}.source_system")
        _text(item["evidence"], f"responsibility.{area}.evidence", minimum=10)
        result[area] = {"owner": owner, "source_system": source_system}
    payroll = result["payroll"]
    expected_owner = "external" if payroll_mode == "external_verified_import" else "not_applicable"
    if (payroll["owner"] != expected_owner
            or (expected_owner == "external"
                and payroll["source_system"] != payroll_source_system)):
        raise PreflightError("responsibility.payroll must match the declared payroll mode and source")
    return result


def _validate_artifacts(manifest: dict[str, Any], root: Path, *,
                        payroll_kind: str, payroll_source_system: str) -> dict[str, list[dict[str, Any]]]:
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise PreflightError("artifacts must contain the required evidence files")
    by_kind: dict[str, list[dict[str, Any]]] = {}
    source_keys: set[tuple[str, str]] = set()
    paths: set[Path] = set()
    for index, artifact_value in enumerate(artifacts, start=1):
        field = f"artifacts[{index}]"
        artifact = _require_object(
            artifact_value,
            field,
            required={"kind", "evidence_role", "source_class", "source_system", "source_id", "path", "sha256", "evidence"},
            allowed={"kind", "evidence_role", "source_class", "source_system", "source_id", "path", "sha256", "evidence"},
        )
        kind = _text(artifact["kind"], f"{field}.kind")
        if kind not in ALLOWED_ARTIFACT_KINDS:
            raise PreflightError(f"{field}.kind is not supported for this pilot")
        evidence_role = _text(artifact["evidence_role"], f"{field}.evidence_role")
        if evidence_role not in EVIDENCE_ROLES:
            raise PreflightError(f"{field}.evidence_role is invalid")
        source_class = _text(artifact["source_class"], f"{field}.source_class")
        if source_class not in SOURCE_CLASSES:
            raise PreflightError(f"{field}.source_class is invalid")
        if kind in REQUIRED_ARTIFACT_KINDS or kind == payroll_kind:
            if evidence_role != "required_evidence":
                raise PreflightError(f"{field} cannot satisfy required {kind} as supporting_calculation")
            if source_class not in REQUIRED_SOURCE_CLASSES[kind]:
                raise PreflightError(f"{field}.source_class cannot satisfy required {kind}")
        elif kind in PAYROLL_ARTIFACT_KINDS:
            raise PreflightError(f"{field}.kind contradicts payroll.mode")
        elif evidence_role != "supporting_calculation":
            raise PreflightError(f"{field} must use supporting_calculation evidence_role")
        source_system = _text(artifact["source_system"], f"{field}.source_system")
        if kind == payroll_kind and source_system != payroll_source_system:
            raise PreflightError("Payroll artifact source_system must match payroll.source_system")
        source_id = _text(artifact["source_id"], f"{field}.source_id")
        source_key = (source_system, source_id)
        if source_key in source_keys:
            raise PreflightError("Artifact source_system/source_id must be unique")
        source_keys.add(source_key)
        expected_hash = _text(artifact["sha256"], f"{field}.sha256")
        if not SHA256.fullmatch(expected_hash):
            raise PreflightError(f"{field}.sha256 must be a lowercase SHA-256")
        _text(artifact["evidence"], f"{field}.evidence", minimum=10)
        path = _relative_file(root, artifact["path"], f"{field}.path")
        if kind in REQUIRED_ARTIFACT_KINDS or kind == payroll_kind:
            try:
                if path.stat().st_size == 0:
                    raise PreflightError(f"Required artifact file is empty: {path.name}")
            except OSError as exc:
                raise PreflightError(f"Cannot read {path.name}") from exc
        if path in paths:
            raise PreflightError("Each artifact path must be used once")
        paths.add(path)
        actual_hash = _sha256(path)
        if actual_hash != expected_hash:
            raise PreflightError(f"Artifact SHA-256 does not match: {path.name}")
        by_kind.setdefault(kind, []).append({
            "path": path,
            "source_system": source_system,
            "source_id": source_id,
            "sha256": actual_hash,
        })
    required_kinds = REQUIRED_ARTIFACT_KINDS | {payroll_kind}
    missing = sorted(required_kinds - by_kind.keys())
    if missing:
        raise PreflightError(f"Missing required artifact kinds: {', '.join(missing)}")
    for kind in SINGLE_ARTIFACT_KINDS & required_kinds:
        if len(by_kind[kind]) != 1:
            raise PreflightError(f"Exactly one {kind} artifact is required")
    return by_kind


def _validate_opening(artifact: dict[str, Any], cutover: date) -> ImportInput:
    package_data = _read_json(artifact["path"], limit=MAX_STRUCTURED_ARTIFACT_BYTES)
    try:
        package = ImportInput.model_validate(package_data)
    except Exception as exc:  # Pydantic error text can contain private submitted values.
        raise PreflightError("Opening-balance package does not conform to opening-balance-v1") from exc
    if package.source_system != artifact["source_system"]:
        raise PreflightError("Opening-balance source_system must match its manifest artifact")
    if package.cutover_date != cutover:
        raise PreflightError("Opening-balance cutover_date must match pilot.cutover_date")
    return package


def _read_structured_artifact(path: Path) -> bytes:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PreflightError(f"Cannot read {path.name}") from exc
    if len(raw) > MAX_STRUCTURED_ARTIFACT_BYTES:
        raise PreflightError(f"{path.name} exceeds the allowed size")
    return raw


def _validate_osv(left: dict[str, Any], right: dict[str, Any], month: str, cutover: date) -> dict[str, Any]:
    try:
        result = compare(_read_structured_artifact(left["path"]), _read_structured_artifact(right["path"]))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PreflightError("OSV artifacts are not a compatible normalized pair") from exc
    if not result["cutover_ready"]:
        blockers = ", ".join(result["eligibility_blockers"])
        raise PreflightError(f"OSV pair is not eligible for cutover: {blockers}")
    if result["left"]["from"] != cutover.isoformat() or result["left"]["to"][:7] != month:
        raise PreflightError("OSV pair must cover pilot.month from pilot.cutover_date")
    return result


def _unverified_intake(manifest_path: Path) -> dict[str, Any] | None:
    """Return only an untrusted inventory of declared artifact kinds.

    This intentionally does not validate an artifact or read any referenced
    file.  It lets a preparer see which required folders of evidence are absent
    after the strict preflight has rejected the package, without turning an
    incomplete manifest into evidence of a valid source.
    """
    try:
        manifest = _read_json(manifest_path.resolve(), limit=MAX_MANIFEST_BYTES)
    except (OSError, PreflightError):
        return None
    artifacts = manifest.get("artifacts")
    declared: set[str] = set()
    if isinstance(artifacts, list):
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            kind = artifact.get("kind")
            if isinstance(kind, str) and kind.strip() in ALLOWED_ARTIFACT_KINDS:
                declared.add(kind.strip())
    payroll = manifest.get("payroll")
    payroll_mode = payroll.get("mode") if isinstance(payroll, dict) else None
    payroll_kind = PAYROLL_ARTIFACT_BY_MODE.get(payroll_mode) if isinstance(payroll_mode, str) else None
    required_kinds = REQUIRED_ARTIFACT_KINDS | ({payroll_kind} if payroll_kind else set())
    required = sorted(required_kinds)
    return {
        "status": "unverified_artifact_kind_inventory",
        "required_artifact_kinds": required,
        "declared_candidate_artifact_kinds": sorted(declared),
        "missing_required_artifact_kinds": sorted(required_kinds - declared),
        "payroll_mode_candidate": payroll_mode if payroll_kind else None,
        "payroll_kind_candidates": sorted(PAYROLL_ARTIFACT_KINDS),
    }


def preflight(manifest_path: Path) -> dict[str, Any]:
    """Validate one explicit manifest and return evidence metadata only."""
    manifest_path = manifest_path.resolve()
    manifest = _read_json(manifest_path, limit=MAX_MANIFEST_BYTES)
    manifest = _require_object(
        manifest,
        "manifest",
        required={"protocol_version", "pilot", "organization", "owners", "policy", "payroll", "responsibility", "artifacts"},
        allowed={"protocol_version", "pilot", "organization", "owners", "policy", "payroll", "responsibility", "artifacts"},
    )
    if _text(manifest["protocol_version"], "protocol_version") != PROTOCOL_VERSION:
        raise PreflightError(f"protocol_version must be {PROTOCOL_VERSION}")
    month, cutover = _validate_pilot(manifest)
    external_id = _validate_identity(manifest, cutover)
    payroll_mode, payroll_source_system, payroll_kind = _validate_payroll(manifest)
    responsibility = _validate_responsibility(manifest, payroll_mode, payroll_source_system)
    artifacts = _validate_artifacts(
        manifest, manifest_path.parent,
        payroll_kind=payroll_kind, payroll_source_system=payroll_source_system,
    )
    opening = _validate_opening(artifacts["opening_balances"][0], cutover)
    osv = _validate_osv(artifacts["osv_left"][0], artifacts["osv_right"][0], month, cutover)
    return {
        "ok": True,
        "protocol_version": PROTOCOL_VERSION,
        "pilot": {"month": month, "cutover_date": cutover.isoformat()},
        "organization_external_id": external_id,
        "artifact_count": sum(len(rows) for rows in artifacts.values()),
        "required_artifact_count": sum(len(artifacts[kind]) for kind in REQUIRED_ARTIFACT_KINDS | {payroll_kind}),
        "supporting_artifact_count": len(artifacts.get("supporting_calculation", [])),
        "payroll": {
            "mode": payroll_mode,
            "source_system": payroll_source_system,
            "artifact_kind": payroll_kind,
            "file_sha256": artifacts[payroll_kind][0]["sha256"],
            "source_contents_verified": False,
            "statutory_payroll_certified": False,
        },
        "responsibility": {
            "pilot_month_only": month,
            "declared_areas": responsibility,
            "operational_ownership_verified": False,
        },
        "opening_import": {
            "entry_count": opening.expected_entry_count,
            "line_count": opening.expected_line_count,
            "source_system": opening.source_system,
            "source_digest": opening.source_digest,
            "file_sha256": artifacts["opening_balances"][0]["sha256"],
        },
        "osv": {
            "organization_id": osv["left"]["organization_id"],
            "period_from": osv["left"]["from"],
            "period_to": osv["left"]["to"],
            "left_sha256": osv["left"]["sha256"],
            "right_sha256": osv["right"]["sha256"],
            "row_count": osv["left_rows"],
        },
        "next": "Preflight passed. Import still requires accountant approval and a separate ERP action.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="Path to belarus-pilot-input-v3 JSON manifest")
    args = parser.parse_args(argv)
    try:
        result = preflight(args.manifest)
    except (OSError, PreflightError) as exc:
        result: dict[str, Any] = {"ok": False, "errors": [str(exc)]}
        intake = _unverified_intake(args.manifest)
        if intake is not None:
            result["intake"] = intake
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
