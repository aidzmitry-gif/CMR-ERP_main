"""Organization-locked draft catalog and budget commands; no postings or imports."""

import hashlib
import json
import re
from calendar import monthrange
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from modules.accounting import service
from modules.accounting.expense_models import (
    ExpenseArticle,
    ExpenseBudget,
    ExpenseBudgetApproval,
    ExpenseBudgetLine,
    ExpenseCatalog,
    ExpenseArticleAttribution,
    ExpenseCommandReceipt,
    ExpenseGroup,
)
from modules.accounting.models import Entry, Line, Period, Policy

APPROVAL_BLOCKER = "Утверждение доступно только главному бухгалтеру после проверки версии бюджета."


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class Conflict(ValueError):
    pass


def _expense_article_id(value):
    """Read a strict article id from JSON dimensions.

    The posting API transports dimension values as strings, while older direct
    model fixtures stored integers. Support both representations without
    guessing from booleans, zero, signed or non-decimal values.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value):
        return int(value)
    return None


def verified_receipt(row):
    receipt = row.receipt
    if not isinstance(receipt, dict):
        raise Conflict("Сохранённая квитанция не прошла проверку целостности")
    unsigned = {k: v for k, v in receipt.items() if k != "receipt_digest"}
    if (
        receipt.get("organization_id") != row.organization_id
        or receipt.get("principal") != row.actor
        or receipt.get("kind") != row.kind
        or receipt.get("request_key") != row.request_key
        or receipt.get("command_hash") != row.command_hash
        or digest(receipt.get("command")) != row.command_hash
        or digest(unsigned) != receipt.get("receipt_digest")
        or digest(receipt.get("result")) != receipt.get("result_digest")
    ):
        raise Conflict("Сохранённая квитанция не прошла проверку целостности")
    return receipt


async def catalog(session, org_id):
    head = await session.get(ExpenseCatalog, org_id, populate_existing=True)
    groups = (
        await session.scalars(
            select(ExpenseGroup)
            .where(ExpenseGroup.organization_id == org_id)
            .order_by(ExpenseGroup.id)
            .execution_options(populate_existing=True)
        )
    ).all()
    articles = (
        await session.scalars(
            select(ExpenseArticle)
            .where(ExpenseArticle.organization_id == org_id)
            .order_by(ExpenseArticle.id)
            .execution_options(populate_existing=True)
        )
    ).all()
    return {
        "revision": head.revision if head else 0,
        "groups": [
            {"id": g.id, "code": g.code, "title": g.title, "active": g.active} for g in groups
        ],
        "articles": [
            {
                "id": a.id,
                "group_id": a.group_id,
                "code": a.code,
                "title": a.title,
                "active": a.active,
            }
            for a in articles
        ],
    }


async def budget_payload(session, budget):
    lines = (
        await session.scalars(
            select(ExpenseBudgetLine)
            .where(ExpenseBudgetLine.budget_id == budget.id)
            .order_by(ExpenseBudgetLine.article_id)
        )
    ).all()
    return {
        "id": budget.id,
        "year": budget.year,
        "currency": budget.currency,
        "basis": budget.basis,
        "revision": budget.revision,
        "state": budget.state,
        "catalog_revision": budget.catalog_revision,
        "actor": budget.actor,
        "evidence": budget.evidence,
        "lines": [
            {
                "article_id": row.article_id,
                "months": row.months,
                "article_snapshot": row.article_snapshot,
            }
            for row in lines
        ],
    }


async def budgets(session, org_id, year, currency, basis):
    rows = (
        await session.scalars(
            select(ExpenseBudget)
            .where(
                ExpenseBudget.organization_id == org_id,
                ExpenseBudget.year == year,
                ExpenseBudget.currency == currency,
                ExpenseBudget.basis == basis,
            )
            .order_by(ExpenseBudget.revision.desc())
            .execution_options(populate_existing=True)
        )
    ).all()
    return [await budget_payload(session, row) for row in rows]


def _approval_result(approval):
    """Serialize the immutable approval without re-reading mutable state."""
    return {
        "budget_id": approval.budget_id,
        "budget_revision": approval.budget_revision,
        "approved_by": approval.actor,
        "approved_at": approval.approved_at.isoformat() if approval.approved_at else None,
        "evidence": approval.evidence,
        "approval_digest": approval.approval_digest,
        "budget": approval.budget_snapshot,
    }


async def approved_budget(session, org_id, year, currency, basis):
    """Return the newest approved version for an exact organization/book."""
    row = (
        await session.execute(
            select(ExpenseBudgetApproval)
            .join(
                ExpenseBudget,
                (ExpenseBudget.organization_id == ExpenseBudgetApproval.organization_id)
                & (ExpenseBudget.id == ExpenseBudgetApproval.budget_id),
            )
            .where(
                ExpenseBudgetApproval.organization_id == org_id,
                ExpenseBudget.year == year,
                ExpenseBudget.currency == currency,
                ExpenseBudget.basis == basis,
            )
            .order_by(ExpenseBudget.revision.desc(), ExpenseBudgetApproval.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return _approval_result(row) if row else None


def _month_bounds(year, month):
    try:
        first = date(year, month, 1)
    except (TypeError, ValueError) as exc:
        raise Conflict("Месяц должен быть от 1 до 12") from exc
    return first, first.replace(day=monthrange(year, month)[1])


def _money(value: Decimal) -> str:
    return format(value, ".2f")


def _expense_source_snapshot(entry, line):
    dimensions = line.dimensions if isinstance(line.dimensions, dict) else {}
    return {
        "entry_id": entry.id,
        "source": entry.source,
        "source_version": entry.source_version,
        "operation": entry.operation,
        "posting_date": entry.posting_date.isoformat(),
        "policy_id": entry.policy_id,
        "entry_digest": entry.digest,
        "line_id": line.id,
        "account_code": line.account_code,
        "account_title": line.account_title,
        "category": line.category,
        "cash": line.cash,
        "side": line.side,
        "amount": _money(line.amount),
        "currency": line.currency,
        "dimensions": dimensions,
    }


def _article_snapshot(article, group):
    return {
        "id": article["id"],
        "code": article["code"],
        "title": article["title"],
        "group_id": article["group_id"],
        "group": (
            {
                "id": group["id"],
                "code": group["code"],
                "title": group["title"],
                "active": group["active"],
            }
            if group is not None
            else None
        ),
    }


def verified_attribution_receipt(row):
    """Reject a corrupted attribution before it changes a reporting view."""
    receipt = row.receipt
    result = receipt.get("result") if isinstance(receipt, dict) else None
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_digest"} if isinstance(receipt, dict) else None
    if (
        not isinstance(result, dict)
        or receipt.get("organization_id") != row.organization_id
        or receipt.get("principal") != row.actor
        or receipt.get("kind") != "expense_article_attribution"
        or receipt.get("request_key") != row.request_key
        or receipt.get("command_hash") != row.command_hash
        or digest(receipt.get("command")) != row.command_hash
        or digest(unsigned) != receipt.get("receipt_digest")
        or digest(result) != receipt.get("result_digest")
        or result.get("source_entry_id") != row.source_entry_id
        or result.get("source_line_id") != row.source_line_id
        or result.get("article_id") != row.article_id
        or result.get("supersedes_id") != row.supersedes_id
        or result.get("basis_digest") != row.basis_digest
        or result.get("effective_date") != row.effective_date.isoformat()
        or result.get("evidence") != row.evidence
        or result.get("explanation") != row.explanation
        or result.get("source_snapshot") != row.source_snapshot
        or result.get("article_snapshot") != row.article_snapshot
    ):
        raise Conflict("Сохранённая квитанция атрибуции не прошла проверку целостности")
    return receipt


async def _latest_attributions(session, org_id, line_ids):
    if not line_ids:
        return {}
    rows = (
        await session.scalars(
            select(ExpenseArticleAttribution)
            .where(
                ExpenseArticleAttribution.organization_id == org_id,
                ExpenseArticleAttribution.source_line_id.in_(set(line_ids)),
            )
            .order_by(
                ExpenseArticleAttribution.source_line_id,
                ExpenseArticleAttribution.id.desc(),
            )
            .execution_options(populate_existing=True)
        )
    ).all()
    latest = {}
    for row in rows:
        latest.setdefault(row.source_line_id, row)
    return latest


async def _attribution_basis(session, org_id, data):
    row = (
        await session.execute(
            select(Entry, Line)
            .join(Line, Line.entry_id == Entry.id)
            .where(Entry.organization_id == org_id, Line.id == data.source_line_id)
        )
    ).one_or_none()
    if row is None:
        raise Conflict("Строка расхода не найдена в выбранной организации")
    entry, line = row
    if line.category != "expense" or line.currency != "BYN":
        raise Conflict("Атрибуция доступна только для расходной строки в BYN")
    if data.effective_date != entry.posting_date:
        raise Conflict("Дата атрибуции должна совпадать с датой отражения исходной проводки")
    policy = await session.scalar(
        select(Policy).where(
            Policy.id == entry.policy_id,
            Policy.organization_id == org_id,
            Policy.effective_from <= entry.posting_date,
        )
    )
    if policy is None:
        raise Conflict("Для исходной строки не найдена применимая учётная политика")
    month = entry.posting_date.strftime("%Y-%m")
    period = await session.scalar(
        select(Period).where(Period.organization_id == org_id, Period.month == month)
    )
    if period is not None and period.closed:
        raise Conflict("Период исходной строки закрыт")
    current = await catalog(session, org_id)
    articles = {item["id"]: item for item in current["articles"]}
    groups = {item["id"]: item for item in current["groups"]}
    article = articles.get(data.article_id)
    group = groups.get(article["group_id"]) if article is not None else None
    if article is None or group is None or not article["active"] or not group["active"]:
        raise Conflict("Статья расходов недоступна в выбранной организации")
    latest = await _latest_attributions(session, org_id, [line.id])
    prior = latest.get(line.id)
    dimensions = line.dimensions if isinstance(line.dimensions, dict) else {}
    direct_article_id = _expense_article_id(dimensions.get("expense_article_id"))
    if direct_article_id in articles and prior is None:
        raise Conflict("Исходная строка уже имеет явную статью расходов")
    source_snapshot = _expense_source_snapshot(entry, line)
    article_snapshot = _article_snapshot(article, group)
    basis_digest = digest(
        {
            "source_snapshot": source_snapshot,
            "article_snapshot": article_snapshot,
            "catalog_revision": current["revision"],
            "supersedes_id": prior.id if prior is not None else None,
        }
    )
    return {
        "entry": entry,
        "line": line,
        "prior": prior,
        "source_snapshot": source_snapshot,
        "article_snapshot": article_snapshot,
        "basis_digest": basis_digest,
    }


async def preview_attribution(session, org_id, data):
    """Return a no-write snapshot a user must present on confirmation."""
    await service.lock_organization(session, org_id)
    basis = await _attribution_basis(session, org_id, data)
    return {
        "source_entry_id": basis["entry"].id,
        "source_line_id": basis["line"].id,
        "article_id": data.article_id,
        "supersedes_id": basis["prior"].id if basis["prior"] is not None else None,
        "effective_date": data.effective_date.isoformat(),
        "basis_digest": basis["basis_digest"],
        "source_snapshot": basis["source_snapshot"],
        "article_snapshot": basis["article_snapshot"],
    }


async def confirm_attribution(session, org_id, actor, data):
    """Append one attribution receipt without mutating its source posting."""
    await service.lock_organization(session, org_id)
    command = data.model_dump(mode="json")
    checksum = digest(command)
    prior_request = await session.scalar(
        select(ExpenseArticleAttribution).where(
            ExpenseArticleAttribution.organization_id == org_id,
            ExpenseArticleAttribution.request_key == str(data.request_key),
        )
    )
    if prior_request is not None:
        if prior_request.actor != actor or prior_request.command_hash != checksum:
            raise Conflict("UUID уже использован другой командой или пользователем")
        receipt = verified_attribution_receipt(prior_request)
        if receipt.get("command") != command:
            raise Conflict("Сохранённая квитанция атрибуции не прошла проверку целостности")
        return receipt
    basis = await _attribution_basis(session, org_id, data)
    if data.expected_basis_digest != basis["basis_digest"]:
        raise Conflict("Основание атрибуции изменилось. Обновите предварительный просмотр")
    result = {
        "source_entry_id": basis["entry"].id,
        "source_line_id": basis["line"].id,
        "article_id": data.article_id,
        "supersedes_id": basis["prior"].id if basis["prior"] is not None else None,
        "effective_date": data.effective_date.isoformat(),
        "basis_digest": basis["basis_digest"],
        "evidence": data.evidence,
        "explanation": data.explanation,
        "source_snapshot": basis["source_snapshot"],
        "article_snapshot": basis["article_snapshot"],
    }
    receipt = {
        "organization_id": org_id,
        "principal": actor,
        "kind": "expense_article_attribution",
        "request_key": str(data.request_key),
        "command": command,
        "command_hash": checksum,
        "result": result,
        "result_digest": digest(result),
    }
    receipt["receipt_digest"] = digest(receipt)
    session.add(
        ExpenseArticleAttribution(
            organization_id=org_id,
            source_entry_id=basis["entry"].id,
            source_line_id=basis["line"].id,
            article_id=data.article_id,
            supersedes_id=basis["prior"].id if basis["prior"] is not None else None,
            request_key=str(data.request_key),
            actor=actor,
            command_hash=checksum,
            basis_digest=basis["basis_digest"],
            effective_date=data.effective_date,
            evidence=data.evidence,
            explanation=data.explanation,
            source_snapshot=basis["source_snapshot"],
            article_snapshot=basis["article_snapshot"],
            receipt=receipt,
        )
    )
    service.audit(
        session,
        org_id,
        actor,
        "expense_article_attribution",
        {"request_key": str(data.request_key), "receipt_digest": receipt["receipt_digest"]},
    )
    await session.flush()
    return receipt


async def attribution_receipt(session, org_id, actor, request_key):
    row = await session.scalar(
        select(ExpenseArticleAttribution).where(
            ExpenseArticleAttribution.organization_id == org_id,
            ExpenseArticleAttribution.request_key == str(request_key),
        )
    )
    if row is None or row.actor != actor:
        return None
    return verified_attribution_receipt(row)


async def _resolved_expense_articles(session, org_id, lines, current):
    articles = {item["id"]: item for item in current["articles"]}
    groups = {item["id"]: item for item in current["groups"]}
    latest = await _latest_attributions(session, org_id, [line.id for line in lines])
    resolved = {}
    for line in lines:
        attribution = latest.get(line.id)
        if attribution is not None:
            receipt = verified_attribution_receipt(attribution)
            snapshot = receipt["result"].get("article_snapshot")
            if not isinstance(snapshot, dict):
                raise Conflict("Сохранённая квитанция атрибуции не прошла проверку целостности")
            resolved[line.id] = snapshot
            continue
        dimensions = line.dimensions if isinstance(line.dimensions, dict) else {}
        article = articles.get(_expense_article_id(dimensions.get("expense_article_id")))
        if article is not None:
            resolved[line.id] = _article_snapshot(article, groups.get(article["group_id"]))
    return resolved


async def actuals(session, org_id, year, month, basis):
    """Return only expense lines with direct or immutable receipt-bound articles.

    A missing ``expense_article_id`` is evidence of incomplete analytical
    coverage unless a reviewed attribution receipt exists; neither path infers
    an article from the account or counterparty.
    Cash actuals use the same rule, additionally requiring the explicit
    ``Line.cash`` flag so a bank movement is never guessed to be an expense.
    """
    first, last = _month_bounds(year, month)
    current = await catalog(session, org_id)
    conditions = [
        Entry.organization_id == org_id,
        Entry.posting_date >= first,
        Entry.posting_date <= last,
        Line.category == "expense",
        Line.currency == "BYN",
    ]
    if basis == "cash":
        conditions.append(Line.cash.is_(True))
    rows = (
        await session.execute(
            select(Entry, Line)
            .join(Line, Line.entry_id == Entry.id)
            .where(*conditions)
            .order_by(Entry.id, Line.id)
        )
    ).all()
    resolved = await _resolved_expense_articles(session, org_id, [line for _entry, line in rows], current)
    grouped = {}
    unmatched = 0
    matched = 0
    for _entry, line in rows:
        article = resolved.get(line.id)
        if article is None:
            unmatched += 1
            continue
        article_id = article["id"]
        amount = line.amount if line.side == "debit" else -line.amount
        item = grouped.setdefault(
            article_id, {"amount": Decimal("0"), "lines": 0, "article": article}
        )
        item["amount"] += amount
        item["lines"] += 1
        matched += 1
    if not matched:
        reason = (
            "За месяц нет денежных расходов с явной аналитикой статьи или квитанцией атрибуции"
            if basis == "cash"
            else "За месяц нет начислений с явной аналитикой статьи или квитанцией атрибуции"
        )
        return {
            "year": year, "month": month, "currency": "BYN", "basis": basis,
            "amount": None, "coverage": "unknown", "matched_lines": 0,
            "unmatched_lines": unmatched, "rows": [], "reason": reason,
        }
    result_rows = []
    total = Decimal("0")
    for article_id, item in grouped.items():
        article = item["article"]
        amount = item["amount"]
        total += amount
        group = article.get("group") if isinstance(article, dict) else None
        result_rows.append({
            "article_id": article_id,
            "article_code": article["code"],
            "article_title": article["title"],
            "group_id": article["group_id"],
            "group_title": group.get("title") if isinstance(group, dict) else None,
            "amount": _money(amount),
            "lines": item["lines"],
        })
    return {
        "year": year, "month": month, "currency": "BYN", "basis": basis,
        "amount": _money(total),
        "coverage": "complete" if unmatched == 0 else "partial",
        "matched_lines": matched,
        "unmatched_lines": unmatched, "rows": result_rows,
        "reason": (
            (
                "Все денежные строки расходов имеют явную аналитику статьи или квитанцию атрибуции и cash=true; сверка с выпиской и первичными документами всё равно обязательна"
                if basis == "cash"
                else "Все строки начисленных расходов имеют явную аналитику статьи или квитанцию атрибуции; сверка с первичными документами всё равно обязательна"
            )
            if unmatched == 0
            else "Учтены только проводки с явной аналитикой статьи или квитанцией атрибуции; покрытие требует сверки с выпиской/первичными документами"
        ),
    }


async def unmatched_actuals(session, org_id, year, month, basis, after_line_id=None, limit=50):
    """Read-only keyset register of the exact lines excluded by ``actuals``."""
    first, last = _month_bounds(year, month)
    current = await catalog(session, org_id)
    articles = {row["id"] for row in current["articles"]}
    conditions = [Entry.organization_id == org_id, Entry.posting_date >= first, Entry.posting_date <= last,
                  Line.category == "expense", Line.currency == "BYN"]
    if basis == "cash":
        conditions.append(Line.cash.is_(True))
    items = []
    cursor = after_line_id
    exhausted = False
    while len(items) < limit and not exhausted:
        query = select(Entry, Line).join(Line, Line.entry_id == Entry.id).where(*conditions)
        if cursor is not None:
            query = query.where(Line.id > cursor)
        chunk = (await session.execute(query.order_by(Line.id).limit(100))).all()
        if not chunk:
            exhausted = True
            break
        resolved = await _resolved_expense_articles(session, org_id, [line for _entry, line in chunk], current)
        for entry, line in chunk:
            cursor = line.id
            if line.id in resolved:
                continue
            dimensions = line.dimensions if isinstance(line.dimensions, dict) else {}
            article_id = _expense_article_id(dimensions.get("expense_article_id"))
            items.append({"entry_id": entry.id, "line_id": line.id, "posting_date": entry.posting_date.isoformat(),
                "source": entry.source, "operation": entry.operation, "account_code": line.account_code, "side": line.side,
                "amount": _money(line.amount), "dimensions": dimensions,
                "reason": "нет статьи" if article_id is None else "статья отсутствует в текущем справочнике"})
            if len(items) == limit:
                break
        exhausted = len(chunk) < 100
    next_after_line_id = None
    if items:
        probe = items[-1]["line_id"]
        while True:
            query = select(Line).join(Entry, Line.entry_id == Entry.id).where(*conditions, Line.id > probe)
            chunk = (await session.scalars(query.order_by(Line.id).limit(100))).all()
            if not chunk:
                break
            resolved = await _resolved_expense_articles(session, org_id, chunk, current)
            for line in chunk:
                if line.id not in resolved:
                    next_after_line_id = items[-1]["line_id"]
                    break
            if next_after_line_id is not None or len(chunk) < 100:
                break
            probe = chunk[-1].id
    return {"year": year, "month": month, "currency": "BYN", "basis": basis, "items": items,
            "next_after_line_id": next_after_line_id}


async def execute(session, org_id, actor, kind, data):
    # HTTP member has acquired this same organization lock and rechecked membership.
    await service.lock_organization(session, org_id)
    command = data.model_dump(mode="json")
    checksum = digest(command)
    prior = await session.scalar(
        select(ExpenseCommandReceipt).where(
            ExpenseCommandReceipt.organization_id == org_id,
            ExpenseCommandReceipt.request_key == str(data.request_key),
        )
    )
    if prior:
        if prior.actor != actor or prior.kind != kind or prior.command_hash != checksum:
            raise Conflict("UUID уже использован другой командой или пользователем")
        receipt = verified_receipt(prior)
        if receipt.get("command") != command:
            raise Conflict("Сохранённая квитанция не прошла проверку целостности")
        return receipt
    current = await catalog(session, org_id)
    if kind == "catalog":
        if current["revision"] != data.expected_revision:
            raise Conflict("Справочник изменился. Обновите сведения")
        await change_catalog(session, org_id, current, data)
        head = await session.get(ExpenseCatalog, org_id)
        if head is None:
            head = ExpenseCatalog(organization_id=org_id, revision=0)
            session.add(head)
        head.revision += 1
        await session.flush()
        result = await catalog(session, org_id)
    else:
        if current["revision"] != data.expected_catalog_revision:
            raise Conflict("Справочник изменился. Обновите сведения")
        versions = await budgets(session, org_id, data.year, data.currency, data.basis)
        previous = versions[0] if versions else None
        if data.expected_revision != (previous["revision"] if previous else 0):
            raise Conflict("Появилась новая версия бюджета. Обновите сведения")
        articles = {row["id"]: row for row in current["articles"]}
        groups = {row["id"]: row for row in current["groups"]}
        old_lines = {row["article_id"]: row for row in previous["lines"]} if previous else {}
        incoming = {row.article_id: row for row in data.lines}
        # Archived lines remain intact in subsequent versions; history cannot disappear silently.
        for article_id, old in old_lines.items():
            if not articles[article_id]["active"] and (
                article_id not in incoming or incoming[article_id].months != old["months"]
            ):
                raise Conflict("Архивная статья должна сохранять прежние месячные значения")
        for row in data.lines:
            a = articles.get(row.article_id)
            if (
                a is None
                or (not a["active"] and row.article_id not in old_lines)
                or not groups[a["group_id"]]["active"]
                and a["active"]
            ):
                raise Conflict("Статья недоступна в выбранной организации")
        budget = ExpenseBudget(
            organization_id=org_id,
            year=data.year,
            currency=data.currency,
            basis=data.basis,
            revision=data.expected_revision + 1,
            catalog_revision=current["revision"],
            actor=actor,
            evidence=data.evidence,
        )
        session.add(budget)
        await session.flush()
        for row in data.lines:
            a = articles[row.article_id]
            snap = (
                old_lines[row.article_id]["article_snapshot"]
                if not a["active"]
                else {**a, "group": groups[a["group_id"]]}
            )
            session.add(
                ExpenseBudgetLine(
                    organization_id=org_id,
                    budget_id=budget.id,
                    article_id=row.article_id,
                    months=row.months,
                    article_snapshot=snap,
                )
            )
        await session.flush()
        result = await budget_payload(session, budget)
    receipt = {
        "organization_id": org_id,
        "principal": actor,
        "kind": kind,
        "request_key": str(data.request_key),
        "command": command,
        "command_hash": checksum,
        "result": result,
        "result_digest": digest(result),
    }
    receipt["receipt_digest"] = digest(receipt)
    session.add(
        ExpenseCommandReceipt(
            organization_id=org_id,
            request_key=str(data.request_key),
            actor=actor,
            kind=kind,
            command_hash=checksum,
            receipt=receipt,
        )
    )
    service.audit(
        session,
        org_id,
        actor,
        "expense_" + kind,
        {"request_key": str(data.request_key), "receipt_digest": receipt["receipt_digest"]},
    )
    await session.flush()
    return receipt


async def approve(session, org_id, actor, data):
    """Create an immutable approval receipt for one exact latest draft.

    Approval is deliberately a separate append-only fact.  The budget row
    remains a draft so historical versions never change after approval.
    """
    await service.lock_organization(session, org_id)
    command = data.model_dump(mode="json")
    checksum = digest(command)
    prior = await session.scalar(
        select(ExpenseCommandReceipt).where(
            ExpenseCommandReceipt.organization_id == org_id,
            ExpenseCommandReceipt.request_key == str(data.request_key),
        )
    )
    if prior:
        if prior.actor != actor or prior.kind != "budget_approval" or prior.command_hash != checksum:
            raise Conflict("UUID уже использован другой командой или пользователем")
        receipt = verified_receipt(prior)
        if receipt.get("command") != command:
            raise Conflict("Сохранённая квитанция не прошла проверку целостности")
        return receipt

    budget = await session.scalar(
        select(ExpenseBudget).where(
            ExpenseBudget.organization_id == org_id,
            ExpenseBudget.id == data.budget_id,
            ExpenseBudget.revision == data.expected_revision,
            ExpenseBudget.state == "draft",
        )
    )
    if budget is None:
        raise Conflict("Версия бюджета не найдена или уже устарела")
    latest_id = await session.scalar(
        select(ExpenseBudget.id)
        .where(
            ExpenseBudget.organization_id == org_id,
            ExpenseBudget.year == budget.year,
            ExpenseBudget.currency == budget.currency,
            ExpenseBudget.basis == budget.basis,
        )
        .order_by(ExpenseBudget.revision.desc())
        .limit(1)
    )
    if latest_id != budget.id:
        raise Conflict("Утвердить можно только последнюю версию бюджета")
    if await session.scalar(
        select(ExpenseBudgetApproval.id).where(
            ExpenseBudgetApproval.organization_id == org_id,
            ExpenseBudgetApproval.budget_id == budget.id,
        )
    ):
        raise Conflict("Эта версия бюджета уже утверждена")

    snapshot = await budget_payload(session, budget)
    approved_at = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    approval_body = {
        "budget_id": budget.id,
        "budget_revision": budget.revision,
        "approved_by": actor,
        "approved_at": approved_at.isoformat(),
        "evidence": data.evidence,
        "budget": snapshot,
    }
    approval_digest = digest(approval_body)
    approval = ExpenseBudgetApproval(
        organization_id=org_id,
        budget_id=budget.id,
        budget_revision=budget.revision,
        actor=actor,
        evidence=data.evidence,
        request_key=str(data.request_key),
        budget_snapshot=snapshot,
        approval_digest=approval_digest,
        approved_at=approved_at,
    )
    session.add(approval)
    await session.flush()
    result = {**approval_body, "approval_digest": approval_digest}
    receipt = {
        "organization_id": org_id,
        "principal": actor,
        "kind": "budget_approval",
        "request_key": str(data.request_key),
        "command": command,
        "command_hash": checksum,
        "result": result,
        "result_digest": digest(result),
    }
    receipt["receipt_digest"] = digest(receipt)
    session.add(
        ExpenseCommandReceipt(
            organization_id=org_id,
            request_key=str(data.request_key),
            actor=actor,
            kind="budget_approval",
            command_hash=checksum,
            receipt=receipt,
        )
    )
    service.audit(
        session,
        org_id,
        actor,
        "expense_budget_approval",
        {"request_key": str(data.request_key), "receipt_digest": receipt["receipt_digest"]},
    )
    await session.flush()
    return receipt


async def change_catalog(session, org_id, current, data):
    async def add_group(code, title):
        row = ExpenseGroup(organization_id=org_id, code=code, title=title)
        session.add(row)
        await session.flush()
        return row

    if data.action == "template":
        if current["groups"] or current["articles"]:
            raise Conflict("Шаблон доступен только для пустого справочника")
        for group in TEMPLATE:
            row = await add_group(group["code"], group["title"])
            session.add_all(
                [
                    ExpenseArticle(organization_id=org_id, group_id=row.id, **a)
                    for a in group["articles"]
                ]
            )
    elif data.action == "create_group":
        if any(g["code"] == data.code for g in current["groups"]):
            raise Conflict("Код группы уже существует, включая архив")
        await add_group(data.code, data.title)
    elif data.action == "create_article":
        if not any(g["id"] == data.group_id and g["active"] for g in current["groups"]):
            raise Conflict("Группа недоступна в выбранной организации")
        if any(a["code"] == data.code for a in current["articles"]):
            raise Conflict("Код статьи уже существует, включая архив")
        session.add(
            ExpenseArticle(
                organization_id=org_id, group_id=data.group_id, code=data.code, title=data.title
            )
        )
    else:
        model = ExpenseGroup if data.action == "archive_group" else ExpenseArticle
        row = await session.scalar(
            select(model).where(model.organization_id == org_id, model.id == data.target_id)
        )
        if row is None or not row.active:
            raise Conflict("Объект отсутствует или уже архивирован")
        if model is ExpenseGroup and any(
            a["group_id"] == row.id and a["active"] for a in current["articles"]
        ):
            raise Conflict("Сначала архивируйте активные статьи группы")
        row.active = False


def envelope(org_id, actor, payload):
    result = {"organization_id": org_id, "principal": actor, **payload}
    return {**result, "digest": digest(result)}


TEMPLATE = [
    {
        "code": "communications",
        "title": "Связь",
        "articles": [
            {"code": "mobile", "title": "Мобильная связь"},
            {"code": "fixed", "title": "Стационарная связь"},
            {"code": "internet", "title": "Интернет"},
        ],
    },
    {
        "code": "post",
        "title": "Почтовые услуги",
        "articles": [
            {"code": "mail", "title": "Отправка корреспонденции"},
            {"code": "mail_subscription", "title": "Абонемент и доставка почты"},
        ],
    },
    {
        "code": "premises",
        "title": "Помещения",
        "articles": [
            {"code": "office_rent", "title": "Аренда офиса"},
            {"code": "warehouse_rent", "title": "Аренда склада"},
            {"code": "utilities", "title": "Коммунальные услуги"},
        ],
    },
    {
        "code": "office",
        "title": "Обеспечение офиса",
        "articles": [
            {"code": "water", "title": "Питьевая вода"},
            {"code": "food", "title": "Кофе и продукты"},
            {"code": "forms", "title": "Бланки ТН/ТТН"},
            {"code": "stationery", "title": "Канцелярские товары"},
        ],
    },
    {
        "code": "it",
        "title": "ИТ и оргтехника",
        "articles": [
            {"code": "equipment_service", "title": "Обслуживание и расходные материалы оргтехники"},
            {"code": "backup", "title": "Резервное копирование и хранение данных"},
        ],
    },
    {
        "code": "delivery",
        "title": "Логистика продаж",
        "articles": [{"code": "customer_delivery", "title": "Доставка покупателям"}],
    },
]
