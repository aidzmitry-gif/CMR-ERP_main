"""Stock-only opening documents; never finalize the whole cutover or physical stock."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import select

from core.domain.models import Sku
from modules.accounting import service
from modules.accounting.models import Entry, Line, OpeningImportReceipt, Policy
from modules.accounting.schemas import Code, Input, LineInput, Money, PostingInput, Quantity
from modules.wms.models import WarehouseDirectory

OPERATION = "stock_opening"
PREFIX = "stock-opening:"
PART_SIZE = 500


class StockRow(Input):
    sku: str = Field(min_length=1, max_length=200)
    warehouse: str = Field(min_length=1, max_length=200)
    lot: str = Field(min_length=1, max_length=200)
    quantity: Quantity
    amount_byn: Money

    @model_validator(mode="after")
    def required(self):
        if any(not value.strip() for value in (self.sku, self.warehouse, self.lot)):
            raise ValueError("Укажите код товара, склад и партию / слой остатка")
        if self.amount_byn <= 0:
            raise ValueError("Общая себестоимость строки должна быть больше нуля")
        self.amount_byn = self.amount_byn.quantize(Decimal("0.01"))
        self.quantity = self.quantity.quantize(Decimal("0.000001"))
        return self


class StockInput(Input):
    request_key: UUID
    opening_date: date
    policy_id: int = Field(gt=0)
    inventory_account: Code
    counter_account: Code
    evidence: str = Field(min_length=5, max_length=300)
    rows: list[StockRow] = Field(min_length=1, max_length=5000)

    @model_validator(mode="after")
    def distinct(self):
        keys = [(r.sku, r.warehouse, r.lot) for r in self.rows]
        if len(keys) != len(set(keys)):
            raise ValueError("Повторяется товар, склад и партия: объедините строки или уточните слой")
        return self


class StockConfirm(Input):
    document: StockInput
    preview_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    acknowledge_addition: bool


async def context(session, org_id, on):
    """Fail before filling a large document when opening is already closed."""
    await service.lock_organization(session, org_id)
    if on.day != 1:
        raise service.AccountingError("Дата начальных остатков должна быть первым числом месяца")
    if await session.scalar(select(OpeningImportReceipt.id).where(
        OpeningImportReceipt.organization_id == org_id).limit(1)):
        raise service.AccountingError("Начальные остатки зафиксированы итоговым переносом")
    if await session.scalar(select(Entry.id).where(
        Entry.organization_id == org_id, Entry.opening.is_(False)).limit(1)):
        raise service.AccountingError("Уже есть обычные проводки. Ввод начальных остатков заблокирован")
    if await session.scalar(select(Entry.id).where(
        Entry.organization_id == org_id, Entry.opening.is_(True), Entry.posting_date != on).limit(1)):
        raise service.AccountingError("Дата отличается от уже введённых начальных остатков")
    accounts = await service.accounts_on(session, org_id, on)
    policy = await session.scalar(select(Policy).where(
        Policy.organization_id == org_id, Policy.effective_from <= on
    ).order_by(Policy.effective_from.desc()).limit(1))
    existing = (await session.scalars(select(Entry.id).where(
        Entry.organization_id == org_id, Entry.opening.is_(True)))).all()
    return {"organization_id": org_id, "opening_date": on.isoformat(),
            "policy_id": policy.id if policy else None,
            "inventory_accounts": [{"code": a.code, "title": a.title} for a in accounts.values()
                                   if a.category == "asset" and a.quantity_tracking and not a.cash
                                   and a.code.split(".")[0] in {"10", "41"}
                                   and set(a.required_dimensions) <= {"sku", "sku_id", "sku_unit", "warehouse", "warehouse_id", "lot"}],
            "counter_accounts": [{"code": a.code, "title": a.title} for a in accounts.values()
                                 if a.category in {"asset", "liability", "equity"}
                                 and not a.quantity_tracking and not a.cash and not a.required_dimensions],
            "warehouses": [{"name": w.name, "title": w.title} for w in (await session.scalars(
                select(WarehouseDirectory).where(WarehouseDirectory.organization_id == org_id,
                                                 WarehouseDirectory.is_active.is_(True))
                .order_by(WarehouseDirectory.name))).all()],
            "existing_opening_entries": len(existing), "physical_stock_updated": False}


def _source(data):
    return f"{PREFIX}{data.request_key}:"


def _posting_from_entry(entry, lines):
    fields = PostingInput.model_fields.keys() - {"lines"}
    return PostingInput(**{k: getattr(entry, k) for k in fields}, lines=[
        LineInput(account=line.account_code, **{k: getattr(line, k) for k in LineInput.model_fields
                                               if k != "account"}) for line in lines])


async def _replay(session, org_id, data, expected=None):
    entries = (await session.scalars(select(Entry).where(
        Entry.organization_id == org_id, Entry.source.startswith(_source(data))
    ).order_by(Entry.source))).all()
    if not entries:
        return None
    parts = (len(data.rows) + PART_SIZE - 1) // PART_SIZE
    if len(entries) != parts:
        raise service.AccountingError("Неполный пакет начальных остатков: нужна сверка")
    result_rows, preview_digest = [], None
    for index, entry in enumerate(entries):
        try:
            meta = json.loads(entry.explanation)
        except (ValueError, TypeError) as exc:
            raise service.AccountingError("Повреждены сведения пакета остатков") from exc
        if (entry.source != f"{_source(data)}{index:03}" or entry.operation != OPERATION
                or entry.source_version != 1 or not entry.opening
                or meta.get("input") != service.digest(data) or meta.get("parts") != parts
                or meta.get("part") != index or meta.get("rows") != len(data.rows)
                or (expected is not None and meta.get("preview") != expected)):
            raise service.AccountingError("Ключ пакета повторно использован с другим содержимым")
        if preview_digest is not None and preview_digest != meta.get("preview"):
            raise service.AccountingError("Части пакета не соответствуют одному подтверждению")
        preview_digest = meta.get("preview")
        lines = (await session.scalars(select(Line).where(Line.entry_id == entry.id).order_by(Line.id))).all()
        if service.digest(_posting_from_entry(entry, lines)) != entry.digest:
            raise service.AccountingError("Проводки пакета изменены: нужна сверка")
        for line in lines:
            if line.side == "debit":
                result_rows.append({"sku": line.dimensions["sku"], "warehouse": line.dimensions["warehouse"],
                                    "lot": line.dimensions["lot"], "quantity": format(line.quantity, "f"),
                                    "amount_byn": format(line.amount, ".2f"),
                                    "unit": line.dimensions["sku_unit"]})
    if len(result_rows) != len(data.rows):
        raise service.AccountingError("Количество строк пакета не совпадает")
    return _result(org_id, data, preview_digest, result_rows, [e.id for e in entries])


def _result(org_id, data, checksum, rows, entry_ids=None):
    return {"organization_id": org_id, "request_key": str(data.request_key),
            "opening_date": data.opening_date.isoformat(), "preview_digest": checksum,
            "rows": rows, "row_count": len(rows),
            "total_byn": format(sum((Decimal(r["amount_byn"]) for r in rows), Decimal(0)), ".2f"),
            "confirmed": entry_ids is not None, "entry_ids": entry_ids or [],
            "physical_stock_updated": False, "cutover_finalized": False}


async def _prepare(session, org_id, data):
    org = await service.lock_organization(session, org_id)
    info = await context(session, org_id, data.opening_date)
    if data.inventory_account not in {a["code"] for a in info["inventory_accounts"]}:
        raise service.AccountingError("Выберите количественный счёт собственных запасов 10 / 41")
    if data.counter_account not in {a["code"] for a in info["counter_accounts"]}:
        raise service.AccountingError("Выберите действующий балансовый корреспондирующий счёт без количества")
    if info["policy_id"] != data.policy_id:
        raise service.AccountingError("Учетная политика изменилась или не утверждена")
    skus = {s.code: s for s in (await session.scalars(select(Sku).where(
        Sku.code.in_({r.sku for r in data.rows}), Sku.is_active.is_(True)
    ).with_for_update(read=True).execution_options(populate_existing=True))).all()}
    warehouses = {w.name: w for w in (await session.scalars(select(WarehouseDirectory).where(
        WarehouseDirectory.organization_id == org_id, WarehouseDirectory.is_active.is_(True),
        WarehouseDirectory.name.in_({r.warehouse for r in data.rows})
    ).with_for_update(read=True).execution_options(populate_existing=True))).all()}
    normalized, stock_lines = [], []
    for number, row in enumerate(data.rows, 1):
        sku, warehouse = skus.get(row.sku), warehouses.get(row.warehouse)
        if sku is None or warehouse is None:
            raise service.AccountingError(f"Строка {number}: код товара или склад организации не найден / неактивен")
        dims = {"sku": sku.code, "sku_id": str(sku.id), "sku_unit": sku.unit,
                "warehouse": warehouse.name, "warehouse_id": str(warehouse.id), "lot": row.lot}
        stock_lines.append(LineInput(account=data.inventory_account, side="debit", amount=row.amount_byn,
                                     quantity=row.quantity, dimensions=dims))
        normalized.append({**row.model_dump(mode="json"), "unit": sku.unit,
                           "sku_title": sku.title, "warehouse_title": warehouse.title,
                           "sku_id": sku.id, "warehouse_id": warehouse.id})
    accounts = await service.accounts_on(session, org_id, data.opening_date)
    policy = await session.get(Policy, data.policy_id, populate_existing=True)
    checksum = service._snapshot_digest({"input": data.model_dump(mode="json"), "rows": normalized,
                                         "generation": org.generation, "context": info,
                                         "accounts": [{col.name: getattr(accounts[code], col.name)
                                                       for col in accounts[code].__table__.columns
                                                       if col.name != "valid_from"}
                                                      for code in (data.inventory_account, data.counter_account)],
                                         "policy": {"id": policy.id, "method": policy.inventory_method,
                                                    "approved_by": policy.approved_by,
                                                    "reference": policy.reference}})
    parts = (len(stock_lines) + PART_SIZE - 1) // PART_SIZE
    commands = []
    for part in range(parts):
        lines = []
        for debit in stock_lines[part * PART_SIZE:(part + 1) * PART_SIZE]:
            lines.extend([debit, LineInput(account=data.counter_account, side="credit", amount=debit.amount)])
        command = PostingInput(source=f"{_source(data)}{part:03}", source_version=1, operation=OPERATION,
                               document_date=data.opening_date, operation_date=data.opening_date,
                               posting_date=data.opening_date, policy_id=data.policy_id,
                               rule_version="stock-opening-v1", opening=True,
                               explanation=json.dumps({"input": service.digest(data), "preview": checksum,
                                                       "part": part, "parts": parts, "rows": len(data.rows),
                                                       "evidence": data.evidence}, ensure_ascii=False), lines=lines)
        await service.validate_posting(session, org_id, command, stock_opening=True)
        commands.append(command)
    return _result(org_id, data, checksum, normalized), commands


async def preview(session, org_id, data):
    await service.lock_organization(session, org_id)
    replay = await _replay(session, org_id, data)
    return replay if replay is not None else (await _prepare(session, org_id, data))[0]


async def confirm(session, org_id, data, actor, event_bus=None):
    if not data.acknowledge_addition:
        raise service.AccountingError("Подтвердите, что документ добавляет остатки, а не заменяет ранее введённые")
    await service.lock_organization(session, org_id)
    replay = await _replay(session, org_id, data.document, data.preview_digest)
    if replay is not None:
        return replay
    result, commands = await _prepare(session, org_id, data.document)
    if result["preview_digest"] != data.preview_digest:
        raise service.AccountingError("Данные изменились после проверки. Проверьте документ заново")
    async with session.begin_nested():
        ids = [(await service.post(session, org_id, command, actor, event_bus, stock_opening=True)).id
               for command in commands]
        result["confirmed"], result["entry_ids"] = True, ids
    return result
