"""Offline comparison of normalized OSV exports; never imports ledger records."""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import re
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from modules.accounting import service
from modules.accounting.models import (
    ReconciliationIssue,
    ReconciliationIssueItem,
    ReconciliationReceipt,
)

HEADERS = ["Тип строки", "Юрлицо ID", "С", "По", "Статус", "Не проведено документов", "Счёт", "Название", "Аналитика JSON", "Валюта исходных сумм", "Забалансовый", "Сальдо начальное BYN", "Дебет BYN", "Кредит BYN", "Сальдо конечное BYN", "Сальдо начальное в валюте", "Дебет в валюте", "Кредит в валюте", "Сальдо конечное в валюте", "Количество начальное", "Количество дебет", "Количество кредит", "Количество конечное"]
FIELDS = ["opening", "debit", "credit", "closing", "original_opening", "original_debit", "original_credit", "original_closing", "quantity_opening", "quantity_debit", "quantity_credit", "quantity_closing"]


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate analytical identifier")
        result[key] = value
    return result


def parse_snapshot(raw: bytes):
    if len(raw) > 10_000_000:
        raise ValueError("Snapshot exceeds 10 MB")
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), delimiter=";", strict=True))
    if len(rows) < 2 or rows[0] != HEADERS or any(len(row) != len(HEADERS) for row in rows):
        raise ValueError("Expected normalized OSV CSV with 23 columns")
    meta = rows[1]
    if meta[0] != "report" or any(meta[6:]):
        raise ValueError("Expected one report metadata row")
    if not re.fullmatch(r"[1-9][0-9]*", meta[1]) or not re.fullmatch(r"[0-9]+", meta[5]):
        raise ValueError("Invalid organization or pending document count")
    if meta[4] not in {"preliminary", "closed_periods"}:
        raise ValueError("Unknown report status")
    for value in meta[2:4]:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("Use ISO dates")
    if meta[2] > meta[3]:
        raise ValueError("End precedes start")
    balances = {}
    for row in rows[2:]:
        if row[0] != "balance" or row[1:6] != meta[1:6]:
            raise ValueError("Mixed report metadata or unknown record type")
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", row[6]) or not re.fullmatch(r"[A-Z]{3}", row[9]) or row[10] not in {"Да", "Нет"}:
            raise ValueError("Invalid account, currency or off-balance marker")
        dimensions = json.loads(row[8], object_pairs_hook=unique_object)
        if not isinstance(dimensions, dict) or any(not isinstance(k, str) or not k or not isinstance(v, str) or not v for k, v in dimensions.items()):
            raise ValueError("Analytical identifiers must be nonempty strings")
        key = (row[6], json.dumps(dimensions, ensure_ascii=False, sort_keys=True), row[9], row[10])
        if key in balances:
            raise ValueError("Duplicate account/analytics/currency row; normalize explicitly")
        values = []
        for index, value in enumerate(row[11:]):
            scale = 6 if index >= 8 else 2
            if not re.fullmatch(rf"-?[0-9]{{1,24}}(?:\.[0-9]{{1,{scale}}})?", value):
                raise ValueError("Missing or invalid exact amount/quantity")
            values.append(Decimal(value))
        with localcontext() as ctx:
            ctx.prec = 64
            for offset in (0, 4, 8):
                opening, debit, credit, closing = values[offset:offset + 4]
                if debit < 0 or credit < 0 or opening + debit - credit != closing:
                    raise ValueError("Invalid turnover or closing arithmetic")
        balances[key] = values
    return {"sha256": hashlib.sha256(raw).hexdigest(), "organization_id": meta[1], "from": meta[2], "to": meta[3], "status": meta[4], "pending_documents": int(meta[5]), "balances": balances}


def compare(left_raw: bytes, right_raw: bytes):
    left, right = parse_snapshot(left_raw), parse_snapshot(right_raw)
    if any(left[field] != right[field] for field in ("organization_id", "from", "to")):
        raise ValueError("Normalize to the same approved organization and period before comparing")
    differences = []
    with localcontext() as ctx:
        ctx.prec = 64
        for key in sorted(left["balances"].keys() | right["balances"].keys()):
            a, b = left["balances"].get(key), right["balances"].get(key)
            if a == b:
                continue
            differences.append({"account": key[0], "dimensions": json.loads(key[1]), "currency": key[2], "off_balance": key[3] == "Да",
                                "presence": "both" if a is not None and b is not None else "left_only" if a is not None else "right_only",
                                "fields": {field: {"left": format(a[i], "f") if a is not None else None,
                                                   "right": format(b[i], "f") if b is not None else None,
                                                   "right_minus_left": format(b[i] - a[i], "f") if a is not None and b is not None else None}
                                           for i, field in enumerate(FIELDS) if a is None or b is None or a[i] != b[i]}})
    blockers = []
    if differences:
        blockers.append("numeric_differences")
    if left["status"] != "closed_periods" or right["status"] != "closed_periods":
        blockers.append("reports_not_closed")
    if left["pending_documents"] != 0 or right["pending_documents"] != 0:
        blockers.append("pending_documents")
    return {"format": "crm-osv-comparison-v1", "status": "differences" if differences else "no_numeric_differences",
            "accepted_by_accountant": False, "cutover_ready": not blockers,
            "eligibility_blockers": blockers,
            "left": {k: v for k, v in left.items() if k != "balances"},
            "right": {k: v for k, v in right.items() if k != "balances"},
            "left_rows": len(left["balances"]), "right_rows": len(right["balances"]), "differences": differences}


def _decode_uploads(left_base64: str, right_base64: str) -> tuple[bytes, bytes]:
    decoded = []
    for encoded in (left_base64, right_base64):
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > 2_000_000:
            raise ValueError("Файл превышает ограничение 2 МБ")
        decoded.append(raw)
    return decoded[0], decoded[1]


def _compare_uploads(org_id: int, left_base64: str, right_base64: str) -> tuple[bytes, bytes, dict]:
    left_raw, right_raw = _decode_uploads(left_base64, right_base64)
    result = compare(left_raw, right_raw)
    if result["left"]["organization_id"] != str(org_id):
        raise ValueError("Юрлицо в файлах не соответствует выбранной книге")
    return left_raw, right_raw, result


def compare_uploads(org_id: int, left_base64: str, right_base64: str):
    """Preview only: compare source bytes without writing an accounting record."""
    return _compare_uploads(org_id, left_base64, right_base64)[2]


async def erp_snapshot(session, org_id: int, start: date, end: date) -> bytes:
    """Render a normalized OSV from this book's current immutable ledger lines."""
    from modules.accounting import reports

    report = await reports.report(session, org_id, start, end)
    if (report["organization_id"] != org_id or report["from"] != start.isoformat()
            or report["to"] != end.isoformat()):
        raise service.AccountingError("ERP report belongs to another book or period")
    metadata = [str(org_id), start.isoformat(), end.isoformat(), report["status"],
                str(report["pending_documents"])]
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow(HEADERS)
    writer.writerow(["report", *metadata, *([""] * 17)])
    for row in report["trial_balance"]:
        title = str(row["title"])
        if title.startswith(("=", "+", "-", "@", "\t", "\r")):
            title = "'" + title
        writer.writerow([
            "balance", *metadata, row["account"], title,
            json.dumps(row["dimensions"], ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            row["currency"], "Да" if row["off_balance"] else "Нет",
            *(row[field] for field in FIELDS),
        ])
    raw = output.getvalue().encode("utf-8-sig")
    if len(raw) > 2_000_000:
        raise service.AccountingError("ERP OSV exceeds the 2 MB reconciliation limit")
    # The same parser used for uploads catches an unsupported ledger shape.
    parsed = parse_snapshot(raw)
    if parsed["organization_id"] != str(org_id):
        raise service.AccountingError("ERP OSV scope changed during export")
    return raw


async def verify_erp_snapshot(session, org_id: int, right_raw: bytes, protocol: dict) -> dict:
    right = protocol["right"]
    current = await erp_snapshot(session, org_id, date.fromisoformat(right["from"]),
                                 date.fromisoformat(right["to"]))
    verified = current == right_raw
    blockers = list(protocol["eligibility_blockers"])
    if not verified and "erp_snapshot_mismatch" not in blockers:
        blockers.append("erp_snapshot_mismatch")
    return {**protocol, "erp_ledger_verified": verified,
            "erp_ledger_sha256": hashlib.sha256(current).hexdigest(),
            "eligibility_blockers": blockers, "cutover_ready": not blockers}


def prepare_queue_uploads(org_id: int, left_base64: str, right_base64: str) -> tuple[bytes, bytes, dict]:
    """Decode and compare a queue candidate before its async database write."""
    return _compare_uploads(org_id, left_base64, right_base64)


def _command_digest(left_raw: bytes, right_raw: bytes, evidence: str) -> str:
    payload = {
        "left_sha256": hashlib.sha256(left_raw).hexdigest(),
        "right_sha256": hashlib.sha256(right_raw).hexdigest(),
        "evidence": evidence,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _queue_command_digest(left_raw: bytes, right_raw: bytes, responsible: str, evidence: str) -> str:
    payload = {
        "kind": "crm-osv-reconciliation-issue-v1",
        "left_sha256": hashlib.sha256(left_raw).hexdigest(),
        "right_sha256": hashlib.sha256(right_raw).hexdigest(),
        "responsible": responsible,
        "evidence": evidence,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _json_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _receipt_result(receipt: ReconciliationReceipt) -> dict:
    erp_verified = receipt.snapshot.get("erp_ledger_verified") is True
    return {
        "organization_id": receipt.organization_id,
        "receipt_id": receipt.id,
        "request_key": receipt.request_key,
        "period_from": receipt.period_from.isoformat(),
        "period_to": receipt.period_to.isoformat(),
        "left_digest": receipt.left_digest,
        "right_digest": receipt.right_digest,
        "command_digest": receipt.command_digest,
        "evidence": receipt.evidence,
        "snapshot": receipt.snapshot,
        "digest": receipt.digest,
        "actor": receipt.actor,
        "created_at": receipt.created_at,
        "accepted_by_accountant": True,
        "erp_ledger_verified": erp_verified,
        "cutover_ready": erp_verified,
        "already_confirmed": False,
    }


async def confirm_uploads(session, org_id: int, left_base64: str, right_base64: str,
                          request_key: UUID, evidence: str, actor: str) -> dict:
    """Persist an eligible comparison without creating ledger movements."""
    left_raw, right_raw, protocol = _compare_uploads(org_id, left_base64, right_base64)
    command_digest = _command_digest(left_raw, right_raw, evidence)
    await service.lock_organization(session, org_id)
    existing = await session.scalar(select(ReconciliationReceipt).where(
        ReconciliationReceipt.organization_id == org_id,
        ReconciliationReceipt.request_key == str(request_key),
    ))
    if existing is not None:
        if existing.command_digest != command_digest:
            raise service.AccountingError("Ключ сверки уже использован с другим протоколом")
        return {**_receipt_result(existing), "already_confirmed": True}
    protocol = await verify_erp_snapshot(session, org_id, right_raw, protocol)
    if not protocol["cutover_ready"]:
        blockers = ", ".join(protocol["eligibility_blockers"])
        raise ValueError(f"Сверка не готова к подтверждению: {blockers}")
    duplicate = await session.scalar(select(ReconciliationReceipt).where(
        ReconciliationReceipt.organization_id == org_id,
        ReconciliationReceipt.command_digest == command_digest,
    ))
    if duplicate is not None:
        raise service.AccountingError("Этот протокол сверки уже подтверждён другим ключом")
    duplicate_source = await session.scalar(select(ReconciliationReceipt).where(
        ReconciliationReceipt.organization_id == org_id,
        ReconciliationReceipt.left_digest == protocol["left"]["sha256"],
        ReconciliationReceipt.right_digest == protocol["right"]["sha256"],
    ))
    if duplicate_source is not None:
        raise service.AccountingError("Эта пара ОСВ уже подтверждена другим протоколом")
    snapshot = {
        "format": protocol["format"],
        "status": protocol["status"],
        "left": protocol["left"],
        "right": protocol["right"],
        "left_rows": protocol["left_rows"],
        "right_rows": protocol["right_rows"],
        "difference_count": len(protocol["differences"]),
        "eligibility_blockers": protocol["eligibility_blockers"],
        "erp_ledger_verified": protocol["erp_ledger_verified"],
        "erp_ledger_sha256": protocol["erp_ledger_sha256"],
    }
    payload = {
        "organization_id": org_id,
        "request_key": str(request_key),
        "command_digest": command_digest,
        "snapshot": snapshot,
        "evidence": evidence,
        "actor": actor,
    }
    receipt = ReconciliationReceipt(
        organization_id=org_id,
        request_key=str(request_key),
        period_from=date.fromisoformat(protocol["left"]["from"]),
        period_to=date.fromisoformat(protocol["left"]["to"]),
        left_digest=protocol["left"]["sha256"],
        right_digest=protocol["right"]["sha256"],
        left_status=protocol["left"]["status"],
        right_status=protocol["right"]["status"],
        left_pending_documents=protocol["left"]["pending_documents"],
        right_pending_documents=protocol["right"]["pending_documents"],
        left_rows=protocol["left_rows"],
        right_rows=protocol["right_rows"],
        difference_count=len(protocol["differences"]),
        command_digest=command_digest,
        evidence=evidence,
        snapshot=snapshot,
        digest=hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode("utf-8")).hexdigest(),
        actor=actor,
    )
    session.add(receipt)
    await session.flush()
    service.audit(session, org_id, actor, "reconciliation_confirmed", {
        "receipt_id": receipt.id,
        "request_key": receipt.request_key,
        "command_digest": command_digest,
        "left_digest": receipt.left_digest,
        "right_digest": receipt.right_digest,
        "period_from": receipt.period_from.isoformat(),
        "period_to": receipt.period_to.isoformat(),
    })
    return _receipt_result(receipt)


def _issue_snapshot(protocol: dict) -> dict:
    """Retain compare evidence, never the uploaded file bytes themselves."""
    return {
        "format": protocol["format"],
        "status": protocol["status"],
        "left": protocol["left"],
        "right": protocol["right"],
        "left_rows": protocol["left_rows"],
        "right_rows": protocol["right_rows"],
        "difference_count": len(protocol["differences"]),
        "eligibility_blockers": protocol["eligibility_blockers"],
        "erp_ledger_verified": protocol["erp_ledger_verified"],
        "erp_ledger_sha256": protocol["erp_ledger_sha256"],
    }


def _issue_item_snapshot(row: dict) -> dict:
    return {
        "account": row["account"],
        "dimensions": row["dimensions"],
        "currency": row["currency"],
        "off_balance": row["off_balance"],
        "presence": row["presence"],
        "fields": row["fields"],
    }


def _issue_result(issue: ReconciliationIssue, *, already_queued: bool = False) -> dict:
    return {
        "organization_id": issue.organization_id,
        "issue_id": issue.id,
        "request_key": issue.request_key,
        "period_from": issue.period_from.isoformat(),
        "period_to": issue.period_to.isoformat(),
        "left_digest": issue.left_digest,
        "right_digest": issue.right_digest,
        "left_status": issue.left_status,
        "right_status": issue.right_status,
        "left_pending_documents": issue.left_pending_documents,
        "right_pending_documents": issue.right_pending_documents,
        "left_rows": issue.left_rows,
        "right_rows": issue.right_rows,
        "difference_count": issue.difference_count,
        "eligibility_blockers": issue.eligibility_blockers,
        "responsible": issue.responsible,
        "evidence": issue.evidence,
        "command_digest": issue.command_digest,
        "snapshot": issue.snapshot,
        "digest": issue.digest,
        "actor": issue.actor,
        "created_at": issue.created_at,
        "already_queued": already_queued,
        # An owner may repair source data, but only a fresh zero-difference,
        # closed comparison can later become an accountant acceptance.
        "requires_fresh_comparison": True,
        "accepted_by_accountant": False,
        "cutover_ready": False,
    }


def _issue_item_result(item: ReconciliationIssueItem) -> dict:
    return {
        "item_id": item.id,
        "item_key": item.item_key,
        "account": item.account,
        "dimensions": item.dimensions,
        "currency": item.currency,
        "off_balance": item.off_balance,
        "presence": item.presence,
        "fields": item.fields,
        "digest": item.digest,
        "created_at": item.created_at,
    }


async def queue_uploads(session, org_id: int, left_base64: str, right_base64: str,
                        request_key: UUID, responsible: str, evidence: str, actor: str,
                        prepared: tuple[bytes, bytes, dict] | None = None) -> dict:
    """Persist every unmatched row and blocker as a non-accepting work queue.

    The queue exists for review and assignment.  It is deliberately distinct
    from ``ReconciliationReceipt``: a recorded issue cannot be promoted or
    edited into an accepted reconciliation.
    """
    left_raw, right_raw, protocol = prepared or prepare_queue_uploads(org_id, left_base64, right_base64)
    command_digest = _queue_command_digest(left_raw, right_raw, responsible, evidence)
    await service.lock_organization(session, org_id)
    existing = await session.scalar(select(ReconciliationIssue).where(
        ReconciliationIssue.organization_id == org_id,
        ReconciliationIssue.request_key == str(request_key),
    ))
    if existing is not None:
        if existing.command_digest != command_digest:
            raise service.AccountingError("Ключ очереди сверки уже использован с другими файлами или ответственным")
        return _issue_result(existing, already_queued=True)
    protocol = await verify_erp_snapshot(session, org_id, right_raw, protocol)
    if protocol["cutover_ready"]:
        raise ValueError("Совпадающую закрытую ОСВ не помещают в очередь; подтвердите протокол бухгалтером")
    duplicate = await session.scalar(select(ReconciliationIssue).where(
        ReconciliationIssue.organization_id == org_id,
        ReconciliationIssue.command_digest == command_digest,
    ))
    if duplicate is not None:
        raise service.AccountingError("Эта команда очереди сверки уже сохранена другим ключом")
    duplicate_source = await session.scalar(select(ReconciliationIssue).where(
        ReconciliationIssue.organization_id == org_id,
        ReconciliationIssue.left_digest == protocol["left"]["sha256"],
        ReconciliationIssue.right_digest == protocol["right"]["sha256"],
    ))
    if duplicate_source is not None:
        raise service.AccountingError("Эта пара ОСВ уже находится в очереди сверки")
    snapshot = _issue_snapshot(protocol)
    payload = {
        "organization_id": org_id,
        "request_key": str(request_key),
        "command_digest": command_digest,
        "responsible": responsible,
        "evidence": evidence,
        "snapshot": snapshot,
        "actor": actor,
    }
    issue = ReconciliationIssue(
        organization_id=org_id,
        request_key=str(request_key),
        period_from=date.fromisoformat(protocol["left"]["from"]),
        period_to=date.fromisoformat(protocol["left"]["to"]),
        left_digest=protocol["left"]["sha256"],
        right_digest=protocol["right"]["sha256"],
        left_status=protocol["left"]["status"],
        right_status=protocol["right"]["status"],
        left_pending_documents=protocol["left"]["pending_documents"],
        right_pending_documents=protocol["right"]["pending_documents"],
        left_rows=protocol["left_rows"],
        right_rows=protocol["right_rows"],
        difference_count=len(protocol["differences"]),
        eligibility_blockers=protocol["eligibility_blockers"],
        responsible=responsible,
        evidence=evidence,
        command_digest=command_digest,
        snapshot=snapshot,
        digest=_json_digest(payload),
        actor=actor,
    )
    session.add(issue)
    await session.flush()
    items = []
    for row in protocol["differences"]:
        item_snapshot = _issue_item_snapshot(row)
        item_key = _json_digest(item_snapshot)
        items.append(ReconciliationIssueItem(
            organization_id=org_id,
            issue_id=issue.id,
            item_key=item_key,
            account=row["account"],
            dimensions=row["dimensions"],
            currency=row["currency"],
            off_balance=row["off_balance"],
            presence=row["presence"],
            fields=row["fields"],
            digest=_json_digest({"issue_id": issue.id, "item_key": item_key, "snapshot": item_snapshot}),
        ))
    session.add_all(items)
    await session.flush()
    service.audit(session, org_id, actor, "reconciliation_issue_queued", {
        "issue_id": issue.id,
        "request_key": issue.request_key,
        "command_digest": command_digest,
        "difference_count": issue.difference_count,
        "eligibility_blockers": issue.eligibility_blockers,
        "responsible": responsible,
    })
    return _issue_result(issue)


async def list_issues(session, org_id: int, after_id: int | None = None, limit: int = 20) -> dict:
    await service.lock_organization(session, org_id)
    query = select(ReconciliationIssue).where(ReconciliationIssue.organization_id == org_id)
    if after_id is not None:
        query = query.where(ReconciliationIssue.id < after_id)
    rows = (await session.scalars(query.order_by(ReconciliationIssue.id.desc()).limit(limit + 1))).all()
    page, extra = rows[:limit], rows[limit:]
    return {
        "organization_id": org_id,
        "rows": [_issue_result(row) for row in page],
        "next_after_id": page[-1].id if extra and page else None,
    }


async def issue_detail(session, org_id: int, issue_id: int, after_item_id: int | None = None,
                       limit: int = 50) -> dict:
    await service.lock_organization(session, org_id)
    issue = await session.scalar(select(ReconciliationIssue).where(
        ReconciliationIssue.organization_id == org_id, ReconciliationIssue.id == issue_id,
    ))
    if issue is None:
        raise service.AccountingError("Очередь сверки не найдена")
    query = select(ReconciliationIssueItem).where(
        ReconciliationIssueItem.organization_id == org_id,
        ReconciliationIssueItem.issue_id == issue_id,
    )
    if after_item_id is not None:
        query = query.where(ReconciliationIssueItem.id > after_item_id)
    rows = (await session.scalars(query.order_by(ReconciliationIssueItem.id).limit(limit + 1))).all()
    page, extra = rows[:limit], rows[limit:]
    return {
        "organization_id": org_id,
        "issue": _issue_result(issue),
        "items": [_issue_item_result(row) for row in page],
        "next_after_item_id": page[-1].id if extra and page else None,
    }


async def list_receipts(session, org_id: int) -> list[dict]:
    await service.lock_organization(session, org_id)
    rows = (await session.scalars(select(ReconciliationReceipt).where(
        ReconciliationReceipt.organization_id == org_id,
    ).order_by(ReconciliationReceipt.id.desc()).limit(100))).all()
    return [_receipt_result(row) for row in rows]


def main():
    parser = argparse.ArgumentParser(description="Compare two normalized OSV CSV files without database access")
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    args = parser.parse_args()
    try:
        result = compare(args.left.read_bytes(), args.right.read_bytes())
    except (ValueError, OSError, csv.Error) as exc:
        parser.exit(2, f"Cannot compare: {exc}\n")
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 1 if result["differences"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
