"""Read immutable output revisions without applying present-day costs to history."""
import json
from datetime import date
from decimal import Decimal

from sqlalchemy import Text, cast, select

from modules.accounting.closing_commands import actual_posting
from modules.accounting.models import Entry, ProductionOutputCostRevision
from modules.accounting.schemas import PostingInput
from modules.accounting.service import AccountingError, digest


async def verify_revision(session, organization_id, revision, evidence):
    if revision.organization_id != organization_id:
        raise AccountingError("Output revision belongs to another organization")
    matrix = evidence.get("matrix")
    if not isinstance(matrix, list):
        raise AccountingError("Output revision lacks its verified correction matrix")
    if revision.entry_id is None:
        if matrix or revision.posting is not None:
            raise AccountingError("Empty output revision contains an unexpected posting")
        return
    entry = await session.get(Entry, revision.entry_id)
    expected = PostingInput.model_validate(revision.posting)
    if (entry is None or entry.organization_id != organization_id
            or entry.operation != "production_output_cost_correction"
            or entry.correction_of != revision.original_entry_id
            or entry.source != f"production:output-cost-revision:{organization_id}:{revision.original_entry_id}:{revision.sequence}"
            or entry.actor != revision.actor or entry.digest != digest(expected)
            or revision.registration_token <= entry.id
            or (await actual_posting(session, entry)).model_dump() != expected.model_dump()):
        raise AccountingError("Output revision differs from its immutable ledger package")
    def canonical(rows):
        return sorted((row["account"], json.dumps(row["dimensions"], sort_keys=True), row["side"],
                       Decimal(str(row["amount"]))) for row in rows)
    if canonical(matrix) != canonical([line.model_dump() for line in expected.lines]):
        raise AccountingError("Output revision differs from its authenticated matrix")


async def revisions_through(session, organization_id, original_entry_id, through: date, before_entry_id=None):
    query = select(ProductionOutputCostRevision, cast(ProductionOutputCostRevision.preview, Text).label("preview_json")).where(
        ProductionOutputCostRevision.organization_id == organization_id,
        ProductionOutputCostRevision.original_entry_id == original_entry_id,
    ).order_by(ProductionOutputCostRevision.sequence)
    if before_entry_id is not None:
        query = query.where(ProductionOutputCostRevision.registration_token < before_entry_id)
    result = []
    for revision, raw in (await session.execute(query)).all():
        if date.fromisoformat(revision.command["posting_date"]) > through:
            continue
        if (revision.sequence != len(result) + 1
                or revision.previous_id != (result[-1][0].id if result else None)
                or result and revision.registration_token <= result[-1][0].registration_token):
            raise AccountingError("Output revision chain is not contiguous in the requested history")
        evidence = json.loads(raw, parse_float=Decimal)["ledger_evidence"]
        await verify_revision(session, organization_id, revision, evidence)
        result.append((revision, evidence))
    return result


async def verify_value_entry(session, organization_id, entry_id):
    found = (await session.execute(select(ProductionOutputCostRevision,
        cast(ProductionOutputCostRevision.preview, Text).label("preview_json")).where(
            ProductionOutputCostRevision.organization_id == organization_id,
            ProductionOutputCostRevision.entry_id == entry_id))).one_or_none()
    if found is None:
        raise AccountingError("Output value adjustment lacks its verified revision")
    revision, raw = found
    await verify_revision(session, organization_id, revision, json.loads(raw, parse_float=Decimal)["ledger_evidence"])
