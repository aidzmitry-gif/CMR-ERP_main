"""Read-only evidence summary for the month-closing workspace.

The snapshot joins existing immutable registers and queues.  It is deliberately
not a statutory approval and does not replace ``validate_close_period``: a
missing register or provisional cost is reported for review instead of being
silently treated as zero or as a blocker that the policy did not define.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date

from sqlalchemy import func, or_, select, text

from modules.accounting.models import (
    Entry,
    FixedAssetDepreciationReceipt,
    FixedAssetRegisterEntry,
    ForeignTradeRegisterEntry,
    Inbox,
    InputVatRegisterEntry,
    InventoryIssueReceipt,
    Line,
    OutputVatRegisterEntry,
    PayrollAccrualReceipt,
    PayrollStatutoryReceipt,
    Period,
    Policy,
    ProductionLaborReceipt,
    ProductionOutputTransferReceipt,
    ProductionOverheadReceipt,
    RepairAccountingReceipt,
    SourceControl,
)
from modules.accounting.service import AccountingError, lock_organization


def _bounds(month: str) -> tuple[date, date]:
    try:
        first = date.fromisoformat(month + "-01")
    except ValueError as exc:
        raise AccountingError("Month must be YYYY-MM") from exc
    if first.strftime("%Y-%m") != month:
        raise AccountingError("Month must be YYYY-MM")
    return first, first.replace(day=monthrange(first.year, first.month)[1])


async def _line_ids(session, org_id: int, first: date, last: date, prefix: str) -> list[int]:
    rows = (await session.execute(select(Line.id).join(Entry, Entry.id == Line.entry_id).where(
        Entry.organization_id == org_id,
        Entry.posting_date >= first,
        Entry.posting_date <= last,
        or_(Line.account_code == prefix, Line.account_code.like(prefix + ".%")),
    ).order_by(Line.id))).all()
    return [row[0] for row in rows]


async def snapshot(session, org_id: int, month: str) -> dict:
    first, last = _bounds(month)
    await lock_organization(session, org_id)
    period = await session.scalar(select(Period).where(
        Period.organization_id == org_id, Period.month == month,
    ))
    policy = await session.scalar(select(Policy).where(
        Policy.organization_id == org_id,
        Policy.effective_from <= first,
    ).order_by(Policy.effective_from.desc(), Policy.id.desc()))
    pending_inbox = await session.scalar(select(func.count(Inbox.id)).where(
        Inbox.organization_id == org_id, Inbox.month <= month, Inbox.entry_id.is_(None),
    )) or 0
    pending_sources = await session.scalar(select(func.count(SourceControl.id)).where(
        SourceControl.organization_id == org_id, SourceControl.month <= month, SourceControl.entry_id.is_(None),
    )) or 0

    from modules.accounting.bank_import import pending_count

    pending_bank = await pending_count(session, org_id, last)

    input_lines = await _line_ids(session, org_id, first, last, "18")
    input_registered = set()
    input_unresolved = 0
    if input_lines:
        input_registered = set((await session.scalars(select(InputVatRegisterEntry.line_id).where(
            InputVatRegisterEntry.organization_id == org_id,
            InputVatRegisterEntry.line_id.in_(input_lines),
        ))).all())
        input_statuses = (await session.execute(select(
            InputVatRegisterEntry.deduction_status, InputVatRegisterEntry.eschf_status,
        ).where(
            InputVatRegisterEntry.organization_id == org_id,
            InputVatRegisterEntry.line_id.in_(input_lines),
        ))).all()
        input_unresolved = sum(
            deduction in {"not_assessed", "pending"} or eschf in {"not_provided", "pending"}
            for deduction, eschf in input_statuses
        )
    output_lines = await _line_ids(session, org_id, first, last, "90.2")
    output_registered = set()
    output_unresolved = 0
    if output_lines:
        output_registered = set((await session.scalars(select(OutputVatRegisterEntry.line_id).where(
            OutputVatRegisterEntry.organization_id == org_id,
            OutputVatRegisterEntry.line_id.in_(output_lines),
        ))).all())
        output_statuses = (await session.execute(select(
            OutputVatRegisterEntry.tax_treatment, OutputVatRegisterEntry.eschf_status,
            OutputVatRegisterEntry.export_evidence,
        ).where(
            OutputVatRegisterEntry.organization_id == org_id,
            OutputVatRegisterEntry.line_id.in_(output_lines),
        ))).all()
        output_unresolved = sum(
            treatment in {"not_assessed", "pending"}
            or eschf in {"not_provided", "pending"}
            or (treatment == "zero_export" and not evidence)
            for treatment, eschf, evidence in output_statuses
        )

    assets = (await session.scalars(select(FixedAssetRegisterEntry.id).where(
        FixedAssetRegisterEntry.organization_id == org_id,
        FixedAssetRegisterEntry.depreciation_start <= last,
    ))).all()
    depreciation_assets = set((await session.scalars(select(FixedAssetDepreciationReceipt.asset_id).where(
        FixedAssetDepreciationReceipt.organization_id == org_id,
        FixedAssetDepreciationReceipt.month == month,
    ))).all())
    asset_without_receipt = [asset_id for asset_id in assets if asset_id not in depreciation_assets]

    repairs = await session.scalar(select(func.count(RepairAccountingReceipt.entry_id)).where(
        RepairAccountingReceipt.organization_id == org_id,
        RepairAccountingReceipt.month == month,
    )) or 0
    production_postings = await session.scalar(select(func.count(Entry.id)).where(
        Entry.organization_id == org_id,
        Entry.posting_date >= first,
        Entry.posting_date <= last,
        Entry.source.like("production:%"),
    )) or 0
    production_material_postings = await session.scalar(select(func.count(Entry.id)).where(
        Entry.organization_id == org_id,
        Entry.posting_date >= first,
        Entry.posting_date <= last,
        Entry.operation == "inventory_issue",
        Entry.source.like("production:material:%"),
    )) or 0
    production_material_receipts = await session.scalar(select(func.count(InventoryIssueReceipt.entry_id)).join(
        Entry, Entry.id == InventoryIssueReceipt.entry_id,
    ).where(
        InventoryIssueReceipt.organization_id == org_id,
        Entry.organization_id == org_id,
        Entry.posting_date >= first,
        Entry.posting_date <= last,
        Entry.operation == "inventory_issue",
        Entry.source.like("production:material:%"),
    )) or 0
    production_labor_postings = await session.scalar(select(func.count(Entry.id)).where(
        Entry.organization_id == org_id,
        Entry.posting_date >= first,
        Entry.posting_date <= last,
        Entry.operation == "production_labor_import",
        Entry.source.like("production:labor:%"),
    )) or 0
    production_labor_receipts = await session.scalar(select(func.count(ProductionLaborReceipt.entry_id)).where(
        ProductionLaborReceipt.organization_id == org_id,
        ProductionLaborReceipt.month == month,
    )) or 0
    production_overhead_postings = await session.scalar(select(func.count(Entry.id)).where(
        Entry.organization_id == org_id,
        Entry.posting_date >= first,
        Entry.posting_date <= last,
        Entry.operation == "production_overhead",
        Entry.source.like("production:overhead:%"),
    )) or 0
    production_overhead_receipts = await session.scalar(select(func.count(ProductionOverheadReceipt.entry_id)).where(
        ProductionOverheadReceipt.organization_id == org_id,
        ProductionOverheadReceipt.month == month,
    )) or 0
    production_output_postings = await session.scalar(select(func.count(Entry.id)).where(
        Entry.organization_id == org_id,
        Entry.posting_date >= first,
        Entry.posting_date <= last,
        Entry.operation == "production_output_transfer",
        Entry.source.like("production:output-transfer:%"),
    )) or 0
    production_output_receipts = await session.scalar(select(func.count(ProductionOutputTransferReceipt.entry_id)).where(
        ProductionOutputTransferReceipt.organization_id == org_id,
        ProductionOutputTransferReceipt.month == month,
    )) or 0
    from modules.accounting.production_output_transfer import output_transfer_source_state

    output_transfer_rows = (await session.scalars(select(ProductionOutputTransferReceipt).where(
        ProductionOutputTransferReceipt.organization_id == org_id,
        ProductionOutputTransferReceipt.month <= month,
    ).order_by(ProductionOutputTransferReceipt.month, ProductionOutputTransferReceipt.entry_id))).all()
    stale_output_transfers = []
    for row in output_transfer_rows:
        state = await output_transfer_source_state(session, row, month)
        if state != "unchanged":
            stale_output_transfers.append({"entry_id": row.entry_id, "order_id": row.order_id, "state": state})
    production_receipt_gap = sum((
        max(0, int(production_material_postings) - int(production_material_receipts)),
        max(0, int(production_labor_postings) - int(production_labor_receipts)),
        max(0, int(production_overhead_postings) - int(production_overhead_receipts)),
        max(0, int(production_output_postings) - int(production_output_receipts)),
    ))
    payroll_postings = await session.scalar(select(func.count(Entry.id)).where(
        Entry.organization_id == org_id,
        Entry.posting_date >= first,
        Entry.posting_date <= last,
        Entry.operation == "payroll_accrual_import",
        Entry.source.like("payroll:accrual:%"),
    )) or 0
    payroll_receipts = await session.scalar(select(func.count(PayrollAccrualReceipt.entry_id)).join(
        Entry, Entry.id == PayrollAccrualReceipt.entry_id,
    ).where(
        PayrollAccrualReceipt.organization_id == org_id,
        Entry.organization_id == org_id,
        Entry.posting_date >= first,
        Entry.posting_date <= last,
        Entry.operation == "payroll_accrual_import",
        Entry.source.like("payroll:accrual:%"),
    )) or 0
    payroll_receipt_gap = max(0, int(payroll_postings) - int(payroll_receipts))
    payroll_statutory_postings = await session.scalar(select(func.count(Entry.id)).where(
        Entry.organization_id == org_id,
        Entry.posting_date >= first,
        Entry.posting_date <= last,
        Entry.operation == "payroll_statutory_import",
        Entry.source.like("payroll:statutory:%"),
    )) or 0
    payroll_statutory_receipts = await session.scalar(select(func.count(PayrollStatutoryReceipt.entry_id)).join(
        Entry, Entry.id == PayrollStatutoryReceipt.entry_id,
    ).where(
        PayrollStatutoryReceipt.organization_id == org_id,
        Entry.organization_id == org_id,
        Entry.posting_date >= first,
        Entry.posting_date <= last,
        Entry.operation == "payroll_statutory_import",
        Entry.source.like("payroll:statutory:%"),
    )) or 0
    payroll_statutory_receipt_gap = max(0, int(payroll_statutory_postings) - int(payroll_statutory_receipts))
    late_cost_postings = await session.scalar(select(func.count(Entry.id)).where(
        Entry.organization_id == org_id,
        Entry.posting_date >= first,
        Entry.posting_date <= last,
        Entry.operation == "inventory_late_cost",
    )) or 0
    late_cost_receipts = await session.scalar(text("""
        SELECT count(*)
        FROM accounting.entry e
        WHERE e.organization_id=:org AND e.posting_date >= :first AND e.posting_date <= :last
          AND e.operation='inventory_late_cost'
          AND (
            EXISTS (SELECT 1 FROM accounting.late_cost_receipt receipt
              WHERE receipt.entry_id=e.id AND receipt.organization_id=e.organization_id)
            OR (
              e.rule_version='late-cost-pool-v3'
              AND EXISTS (
                SELECT 1 FROM accounting.late_pool_package package
                WHERE package.late_entry_id=e.id AND package.organization_id=e.organization_id
                  AND jsonb_typeof(package.calculation->'destinations')='array'
                  AND (SELECT count(*) FROM accounting.late_pool_inventory_value_link link
                    WHERE link.package_id=package.id) =
                    (SELECT count(*) FROM jsonb_array_elements(package.calculation->'destinations') destination
                     WHERE destination->>'kind'='inventory'
                       AND CASE WHEN coalesce(destination->>'delta_byn','') ~ '^-?[0-9]{1,16}[.][0-9]{2}$'
                                THEN (destination->>'delta_byn')::numeric END <> 0)
              )
            )
          )
    """), {"org": org_id, "first": first, "last": last}) or 0
    trade_entries = (await session.scalars(select(ForeignTradeRegisterEntry).where(
        ForeignTradeRegisterEntry.organization_id == org_id,
        ForeignTradeRegisterEntry.posting_date >= first,
        ForeignTradeRegisterEntry.posting_date <= last,
    ).order_by(ForeignTradeRegisterEntry.id))).all()
    trade_unresolved = sum(
        (row.trade_mode in {"eaeu_import", "third_country_import"} and not row.incoterms)
        or (row.trade_mode == "eaeu_import" and not row.eaeu_reference)
        or (row.trade_mode in {"third_country_import", "export"} and not row.customs_reference)
        or (row.trade_mode == "export" and not row.export_evidence)
        or (row.currency == "BYN" and any(value is not None for value in (
            row.original_amount, row.rate, row.rate_scale, row.rate_date, row.rate_source,
        )))
        or (row.currency != "BYN" and any(value is None for value in (
            row.original_amount, row.rate, row.rate_scale, row.rate_date, row.rate_source,
        )))
        or (row.trade_mode == "export" and (row.customs_duty or row.import_vat))
        for row in trade_entries
    )

    blockers = []
    if pending_inbox:
        blockers.append({"code": "unposted_inbox", "count": int(pending_inbox),
                         "message": "Есть документы в очереди «Не проведено»."})
    if pending_sources:
        blockers.append({"code": "unposted_source_controls", "count": int(pending_sources),
                         "message": "Есть первичные источники без бухгалтерской проводки."})
    if pending_bank:
        blockers.append({"code": "unposted_bank_imports", "count": int(pending_bank),
                         "message": "Есть закреплённые за юрлицом банковские строки без проводки (включая строки без даты)."})
    if policy is None:
        blockers.append({"code": "missing_policy", "count": 1,
                         "message": "На дату месяца нет применимой версии учётной политики."})
    review = []
    if policy is not None and not policy.normative_verified:
        review.append({"code": "policy_normative_basis", "count": 1,
                       "message": "Нормативная редакция учётной политики ещё не подтверждена."})
    if len(input_lines) - len(input_registered):
        review.append({"code": "input_vat_register", "count": len(input_lines) - len(input_registered),
                       "message": "Строки входного НДС требуют регистрации основания и ЭСЧФ."})
    if len(output_lines) - len(output_registered):
        review.append({"code": "output_vat_register", "count": len(output_lines) - len(output_registered),
                       "message": "Строки исходящего НДС требуют регистрации ставки, основания и ЭСЧФ."})
    if input_unresolved:
        review.append({"code": "input_vat_evidence", "count": int(input_unresolved),
                       "message": "Зарегистрированные строки входного НДС имеют незавершённый статус вычета или ЭСЧФ."})
    if output_unresolved:
        review.append({"code": "output_vat_evidence", "count": int(output_unresolved),
                       "message": "Зарегистрированные строки исходящего НДС имеют незавершённый статус ставки или ЭСЧФ."})
    if asset_without_receipt:
        review.append({"code": "depreciation_register", "count": len(asset_without_receipt),
                       "message": "У основных средств нет квитанции амортизации за выбранный месяц."})
    if production_postings:
        review.append({"code": "production_cost_provisional", "count": int(production_postings),
                       "message": "Производственные проводки остаются предварительными до финальной себестоимости."})
    if production_receipt_gap:
        review.append({"code": "production_cost_receipt_gap", "count": int(production_receipt_gap),
                       "message": "Для части производственных проводок нет соответствующей проверенной квитанции регистра."})
    if stale_output_transfers:
        review.append({"code": "production_output_source_stale", "count": len(stale_output_transfers),
                       "message": "База себестоимости выпуска изменилась или недоступна; проверьте наряд перед закрытием.",
                       "transfers": stale_output_transfers})
    if payroll_postings:
        review.append({"code": "payroll_accrual_provisional", "count": int(payroll_postings),
                       "message": "Валовое начисление зарплаты импортировано из проверенного источника; нормативный расчёт ещё не сертифицирован."})
    if payroll_receipt_gap:
        review.append({"code": "payroll_accrual_receipt_gap", "count": int(payroll_receipt_gap),
                       "message": "Для части импортированных начислений зарплаты нет связанной квитанции источника."})
    if payroll_statutory_postings:
        review.append({"code": "payroll_statutory_provisional", "count": int(payroll_statutory_postings),
                       "message": "Удержания и взносы импортированы из проверенного источника; нормативная сертификация ещё не выполнена."})
    if payroll_statutory_receipt_gap:
        review.append({"code": "payroll_statutory_receipt_gap", "count": int(payroll_statutory_receipt_gap),
                       "message": "Для части импортированных удержаний и взносов нет связанной квитанции источника."})
    if repairs:
        review.append({"code": "repair_cost_provisional", "count": int(repairs),
                       "message": "Ремонтные результаты не сертифицированы как финальная себестоимость."})
    if late_cost_postings:
        review.append({"code": "inventory_late_cost_provisional", "count": int(late_cost_postings),
                       "message": "Дополнительные расходы по запасам требуют проверки финальной себестоимости."})
    if int(late_cost_postings) > int(late_cost_receipts):
        review.append({"code": "inventory_late_cost_receipt_gap",
                       "count": int(late_cost_postings) - int(late_cost_receipts),
                       "message": "Для части поздних расходов по запасам нет связанной квитанции расчёта."})
    if trade_unresolved:
        review.append({"code": "foreign_trade_evidence", "count": int(trade_unresolved),
                       "message": "Документы ВЭД имеют незавершённые реквизиты или требуют проверки подтверждающих документов."})

    return {
        "organization_id": org_id,
        "month": month,
        "period": {"closed": bool(period.closed) if period else False,
                   "generation": period.generation if period else 0},
        "policy": {
            "id": policy.id if policy else None,
            "effective_from": policy.effective_from.isoformat() if policy else None,
            "status": "verified" if policy and policy.normative_verified else ("unverified" if policy else "missing"),
            "normative_verified": bool(policy.normative_verified) if policy else False,
            "technical_preview_available": policy is not None,
            "confirmation_available": bool(policy and policy.normative_verified),
        },
        "status": "review_only",
        "close_blocked_by_queues": bool(blockers),
        "close_blocked_by_policy": policy is None or not policy.normative_verified,
        "blockers": blockers,
        "review_items": review,
        "documents": {"pending_inbox": int(pending_inbox), "pending_source_controls": int(pending_sources)},
        "vat": {"input_lines": len(input_lines), "input_registered": len(input_registered),
                "input_unregistered": len(input_lines) - len(input_registered),
                "input_unresolved": int(input_unresolved),
                "output_lines": len(output_lines), "output_registered": len(output_registered),
                "output_unregistered": len(output_lines) - len(output_registered),
                "output_unresolved": int(output_unresolved),
                "statutory_certified": False},
        "fixed_assets": {"assets_due_by_date": len(assets),
                          "depreciation_receipts": len(depreciation_assets),
                          "assets_without_month_receipt": len(asset_without_receipt),
                          "statutory_certified": False},
        "production": {
            "postings": int(production_postings),
            "material_issues": int(production_material_postings),
            "material_issue_receipts": int(production_material_receipts),
            "labor_imports": int(production_labor_postings),
            "labor_receipts": int(production_labor_receipts),
            "overhead_allocations": int(production_overhead_postings),
            "overhead_receipts": int(production_overhead_receipts),
            "output_transfers": int(production_output_postings),
            "output_transfer_receipts": int(production_output_receipts),
            "stale_output_transfers": stale_output_transfers,
            "receipt_gap": int(production_receipt_gap),
            "final_cost_certified": False,
        },
        "payroll": {
            "gross_accruals": int(payroll_postings),
            "receipts": int(payroll_receipts),
            "receipt_gap": int(payroll_receipt_gap),
            "statutory_imports": int(payroll_statutory_postings),
            "statutory_receipts": int(payroll_statutory_receipts),
            "statutory_receipt_gap": int(payroll_statutory_receipt_gap),
            "statutory_payroll_certified": False,
            "deductions_and_contributions_available": bool(payroll_statutory_postings)
            and not payroll_statutory_receipt_gap,
        },
        "repairs": {"posted": int(repairs), "final_cost_certified": False},
        "inventory": {"late_cost_postings": int(late_cost_postings),
                      "late_cost_receipts": int(late_cost_receipts),
                      "final_cost_certified": False},
        "foreign_trade": {"entries": len(trade_entries), "unresolved": int(trade_unresolved),
                          "statutory_certified": False},
        "statutory_certified": False,
    }
