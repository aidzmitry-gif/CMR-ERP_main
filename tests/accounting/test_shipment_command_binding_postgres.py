"""Every saved page must retain the accountant's confirmed command fields."""

# ruff: noqa: F811
from copy import deepcopy
from datetime import date, timedelta

import pytest
from sqlalchemy.exc import DBAPIError

from modules.accounting import models, service, shipment_commands, shipment_preview
from modules.accounting.schemas import PostingInput
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.accounting.test_shipment_receipt_postgres import prepare_accounting
from tests.integration.test_invoice_physical_shipments_postgres import physical_pg  # noqa: F401


@pytest.mark.parametrize(
    "field",
    ["document_date", "posting_date", "explanation", "opening", "policy_id", "correction_of"],
)
async def test_consistent_page_hash_cannot_replace_confirmed_command(
    physical_pg, monkeypatch, field
):
    factory, org, act, data = await prepare_accounting(physical_pg)
    async with factory() as session:
        old_policy = models.Policy(
            organization_id=org,
            effective_from=date(2025, 1, 1),
            reference="Superseded synthetic policy",
            inventory_method="specific",
            allocation_basis="direct_cost",
            depreciation_method="straight_line",
            normative_reference="Synthetic",
            normative_verified=False,
            approved_by="allocator",
        )
        session.add(old_policy)
        await session.commit()
        plan = deepcopy(await shipment_preview.prepare(session, org, act, data))
        value = {
            "document_date": (data.document_date - timedelta(days=1)).isoformat(),
            "posting_date": (data.posting_date + timedelta(days=1)).isoformat(),
            "explanation": "Different accountant evidence",
            "opening": True,
            "policy_id": old_policy.id,
            "correction_of": 1,
        }[field]
        if field == "posting_date" and value[:7] != data.posting_date.isoformat()[:7]:
            pytest.skip("Requires a second open day within the same month")
        for page in plan["postings"]:
            page["posting"][field] = value
            page["digest"] = service.digest(PostingInput(**page["posting"]))

        async def faulty_plan(*args, **kwargs):
            return plan

        monkeypatch.setattr(shipment_preview, "prepare", faulty_plan)
        if field in {"opening", "policy_id", "correction_of"}:
            original_validate = service.validate_posting

            async def validate_original_header(session, org_id, body, **kwargs):
                # Exercise SQL independently: validate the legitimate header,
                # then let the faulty writer insert the changed header.
                original = body.model_copy(
                    update={"opening": False, "policy_id": data.policy_id, "correction_of": None}
                )
                return await original_validate(session, org_id, original, **kwargs)

            monkeypatch.setattr(service, "validate_posting", validate_original_header)
        with pytest.raises(DBAPIError, match="Shipment|shipment"):
            await shipment_commands.confirm(
                session, org, act, data, plan["basis_digest"], "allocator"
            )
            await session.commit()
        await session.rollback()
