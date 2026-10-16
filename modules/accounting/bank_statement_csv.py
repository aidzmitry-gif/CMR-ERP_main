"""Explicit normalized CSV adapter; never infer a bank layout or debit direction."""
import csv
import hashlib
import io
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.services.bank_statement import BankStatementLine
from modules.accounting import bank_statement, service
from modules.accounting.bank_import import _digest

COLUMNS = ("external_id", "direction", "operation_date", "amount", "currency",
           "counterparty_name", "counterparty_identifier", "purpose")
MAX_ROWS = 1000


class CsvInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    provider: str = Field(min_length=1, max_length=100)
    account_code: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=1_000_000)
    evidence: str = Field(min_length=1, max_length=1000)


class CsvConfirmInput(CsvInput):
    preview_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


def preview(org_id: int, data: CsvInput):
    """Validate every record, preserving invalid row numbers without storing data."""
    reference = "sha256:" + hashlib.sha256(data.content.encode("utf-8")).hexdigest()
    errors, lines = [], []
    seen = set()
    totals = {"receipt": Decimal("0.00"), "payment": Decimal("0.00")}
    if not data.evidence.strip():
        raise service.AccountingError("Statement account ownership requires explicit evidence")
    reader = csv.reader(io.StringIO(data.content.removeprefix("\ufeff"), newline=""), strict=True)
    try:
        if tuple(next(reader, [])) != COLUMNS:
            raise service.AccountingError("CSV columns must match the template exactly")
        for index, values in enumerate(reader, start=1):
            if index > MAX_ROWS:
                raise service.AccountingError(f"CSV exceeds {MAX_ROWS} operations")
            if len(values) != len(COLUMNS):
                errors.append({"record": index, "message": "Wrong number of CSV fields"})
                continue
            row = dict(zip(COLUMNS, values, strict=True))
            for key in ("counterparty_name", "counterparty_identifier"):
                row[key] = row[key] or None
            try:
                line = BankStatementLine(**row, provider=data.provider, account_code=data.account_code,
                                         source_kind="file", source_reference=reference)
                bank_statement.source_values(line)
                if line.source_identity in seen:
                    raise service.AccountingError("Repeated operation identity inside CSV")
                seen.add(line.source_identity)
                lines.append(line)
                totals[line.direction] += Decimal(line.amount)
            except ValidationError as exc:
                errors.append({"record": index, "message": "; ".join(
                    f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors(include_input=False))})
            except service.AccountingError as exc:
                errors.append({"record": index, "message": str(exc)})
    except csv.Error as exc:
        raise service.AccountingError(f"Invalid CSV near line {reader.line_num}: {exc}") from exc
    if not lines and not errors:
        raise service.AccountingError("CSV contains no operations")
    digest = _digest({"organization_id": org_id, "provider": data.provider,
                      "account_code": data.account_code, "source_reference": reference,
                      "evidence": data.evidence, "format": "normalized-csv-v1"})
    return {"organization_id": org_id, "preview_digest": digest, "source_reference": reference,
            "valid": not errors, "errors": errors, "valid_count": len(lines),
            "totals": {k: str(v) for k, v in totals.items()},
            "lines": [line.model_dump() for line in lines]}


async def confirm(session, org_id: int, data: CsvConfirmInput, actor: str):
    checked = preview(org_id, data)
    if checked["preview_digest"] != data.preview_digest:
        raise service.AccountingError("CSV or import settings changed; preview again")
    if not checked["valid"]:
        raise service.AccountingError("Fix all CSV errors before importing")
    source_ids = []
    # The caller's transaction is atomic: no successful subset survives a conflict.
    for raw in checked["lines"]:
        row = await bank_statement.ingest(session, org_id, BankStatementLine(**raw),
                                           evidence=data.evidence, actor=actor)
        source_ids.append(row.id)
    return {"organization_id": org_id, "source_transaction_ids": source_ids,
            "count": len(source_ids), "source_reference": checked["source_reference"]}
