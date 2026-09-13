"""SQL must enforce the BYN shipment line contract independently of Python."""

# ruff: noqa: F811
import hashlib
import json
from copy import deepcopy
from datetime import date

import pytest
from sqlalchemy.exc import DBAPIError

from modules.accounting import models, service, shipment_commands, shipment_preview
from modules.accounting.schemas import PostingInput
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.accounting.test_shipment_receipt_postgres import prepare_accounting
from tests.integration.test_invoice_physical_shipments_postgres import physical_pg  # noqa: F401


@pytest.mark.parametrize("field", ["quantity", "currency", "cash_activity"])
async def test_commercial_line_cannot_carry_incompatible_metadata(physical_pg, monkeypatch, field):
    factory, org, act, data = await prepare_accounting(physical_pg)
    async with factory() as session:
        plan = deepcopy(await shipment_preview.prepare(session, org, act, data))
        for page in plan["postings"]:
            for line in page["posting"]["lines"]:
                if line["account"] != "62":
                    continue
                if field == "quantity":
                    line["quantity"] = "1.000000"
                elif field == "currency":
                    line.update(
                        currency="USD",
                        original_amount=line["amount"],
                        rate="1",
                        rate_scale=1,
                        rate_date=data.posting_date.isoformat(),
                        rate_source="Synthetic FX",
                    )
                else:
                    line["cash_activity"] = "operating"
            page["digest"] = service.digest(PostingInput(**page["posting"]))

        async def faulty_plan(*args, **kwargs):
            return plan

        original_validate = service.validate_posting

        async def validate_original_line(session, org_id, body, **kwargs):
            corrected = body.model_dump(mode="json")
            for line in corrected["lines"]:
                if line["account"] == "62":
                    line.update(
                        quantity=None,
                        currency="BYN",
                        original_amount=None,
                        rate=None,
                        rate_scale=None,
                        rate_date=None,
                        rate_source=None,
                        cash_activity=None,
                    )
            return await original_validate(session, org_id, PostingInput(**corrected), **kwargs)

        monkeypatch.setattr(shipment_preview, "prepare", faulty_plan)
        monkeypatch.setattr(service, "validate_posting", validate_original_line)
        with pytest.raises(DBAPIError, match="Shipment|shipment"):
            await shipment_commands.confirm(
                session, org, act, data, plan["basis_digest"], "allocator"
            )
            await session.commit()
        await session.rollback()


@pytest.mark.parametrize("bad", ["missing", "blank", "unknown_account"])
async def test_zero_cent_allocation_requires_its_own_valid_analytics(physical_pg, monkeypatch, bad):
    factory, org, act, data = await prepare_accounting(physical_pg, full=True, stock_cost="0.01")
    async with factory() as session:
        for code in ["90.4.0", "90.4.9"]:
            session.add(
                models.Account(
                    organization_id=org,
                    code=code,
                    title=code,
                    category="expense",
                    valid_from=date(2026, 1, 1),
                    required_dimensions=["order"] if code == "90.4.0" else [],
                    currency_tracking=False,
                    quantity_tracking=False,
                    cash=False,
                    normative_ref="Synthetic",
                )
            )
        await session.commit()
        data.allocations[0].expense_account = "90.4.0"
        data.allocations[0].expense_dimensions = {"order": "valid"}
        data.allocations[1].expense_account = "90.4.9"
        plan = deepcopy(await shipment_preview.prepare(session, org, act, data))
        assert plan["mapping"][0]["cost_byn"] == "0.00"
        if bad == "unknown_account":
            data.allocations[0].expense_account = "90.4.1"
        else:
            data.allocations[0].expense_dimensions = {} if bad == "missing" else {"order": ""}
        plan["mapping"][0].update(data.allocations[0].model_dump(mode="json"))
        basis = {
            "act_digest": act["digest"],
            "inputs": data.model_dump(mode="json"),
            "costs": plan["costs"],
            "mapping": plan["mapping"],
            "commercial": plan["commercial"],
        }
        plan["basis_digest"] = hashlib.sha256(
            json.dumps(
                basis, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")
            ).encode()
        ).hexdigest()
        for page in plan["postings"]:
            page["posting"]["rule_version"] = "shipment-sale-v1:" + plan["basis_digest"]
            page["digest"] = service.digest(PostingInput(**page["posting"]))

        async def faulty_plan(*args, **kwargs):
            return plan

        monkeypatch.setattr(shipment_preview, "prepare", faulty_plan)
        with pytest.raises(DBAPIError, match="Shipment account"):
            await shipment_commands.confirm(
                session, org, act, data, plan["basis_digest"], "allocator"
            )
            await session.commit()
        await session.rollback()
