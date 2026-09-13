"""Real WMS act plus unallocated PostgreSQL accounting schema."""

# ruff: noqa: F811
import hashlib
import json
from copy import deepcopy
from datetime import date

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from modules.accounting import models, service, shipment_commands, shipment_preview
from modules.accounting.schemas import PostingInput
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.integration.test_invoice_physical_shipments_postgres import physical_pg  # noqa: F401
from tests.test_invoice_physical_shipments import endpoint, request


async def prepare_accounting(physical_pg, *, full=False, stock_cost="10.00", normative_verified=False):
    api, factory, org, facts = physical_pg
    physical_lines = [{"line_no": 1, "warehouse": "W", "qty": "1.00"}]
    if full:
        physical_lines.append({"line_no": 2, "warehouse": "W", "qty": "2.00"})
    body = await request(api, org, facts, physical_lines)
    response = await api.post(endpoint(org), json=body)
    assert response.status_code == 201, response.text
    act = response.json()
    async with factory() as session:
        policy = models.Policy(
            organization_id=org,
            effective_from=date(2026, 1, 1),
            reference="Synthetic",
            inventory_method="specific",
            allocation_basis="direct_cost",
            depreciation_method="straight_line",
            normative_reference="Synthetic",
            normative_verified=normative_verified,
            approved_by="allocator",
        )
        session.add(policy)
        for code, category in [
            ("41.2", "asset"),
            ("60", "liability"),
            ("62", "asset"),
            ("90.1", "income"),
            ("90.2", "income"),
            ("68.2", "liability"),
            ("90.4", "expense"),
        ]:
            session.add(
                models.Account(
                    organization_id=org,
                    code=code,
                    title=code,
                    category=category,
                    valid_from=date(2026, 1, 1),
                    required_dimensions=[],
                    currency_tracking=False,
                    quantity_tracking=code == "41.2",
                    cash=False,
                    normative_ref="Synthetic",
                )
            )
        await session.flush()
        policy_id = policy.id
        if stock_cost is not None:
            await service.post(
                session,
                org,
                PostingInput(
                    source="synthetic-stock",
                    source_version=1,
                    operation="manual",
                    document_date=date.today(),
                    operation_date=date.today(),
                    posting_date=date.today(),
                    policy_id=policy_id,
                    rule_version="synthetic",
                    explanation="Synthetic stock",
                    lines=[
                        {
                            "account": "41.2",
                            "side": "debit",
                            "amount": stock_cost,
                            "quantity": "3",
                            "dimensions": {"warehouse": "W", "sku": "A", "lot": "L"},
                        },
                        {"account": "60", "side": "credit", "amount": stock_cost},
                    ],
                ),
                "allocator",
            )
        await session.commit()
    data = shipment_preview.ShipmentPlanInput(
        expected_act_digest=act["digest"],
        policy_id=policy_id,
        document_date=date.today(),
        posting_date=date.today(),
        explanation="Synthetic shipment",
        recognition="sale_on_shipment",
        recognition_basis="Synthetic decision",
        unit_basis="Same units",
        cost_allocation="cumulative_floor_last",
        vat_rounding="commercial_line_half_up",
        allocations=[
            {
                "line_source": line["source"],
                "account": "41.2",
                "lot": "L",
                "quantity": line["qty"],
                "expense_account": "90.4",
            }
            for line in act["snapshot"]["lines"]
        ],
        commercial_lines=[
            {
                "line_no": line_no,
                "net_amount": "20.00",
                "vat_rate": "20",
                "vat_basis": "Synthetic",
                "buyer_account": "62",
                "revenue_account": "90.1",
                "vat_revenue_account": "90.2",
                "vat_payable_account": "68.2",
                "buyer_dimensions": {
                    "counterparty": "Buyer",
                    "contract": "C",
                    "settlement_document": f"sales:document:{act['snapshot']['document_id']}",
                },
            }
            for line_no in sorted({line["line_no"] for line in act["snapshot"]["lines"]})
        ],
    )
    return factory, org, act, data


@pytest.mark.parametrize("stock_cost", ["10.00", "0.01"])
async def test_sql_shared_lot_and_zero_cent_distribution(physical_pg, stock_cost):
    factory, org, act, data = await prepare_accounting(
        physical_pg, full=True, stock_cost=stock_cost
    )
    async with factory() as session:
        plan = await shipment_preview.prepare(session, org, act, data)
        assert len(plan["mapping"]) == 2
        saved = await shipment_commands.confirm(
            session, org, act, data, plan["basis_digest"], "allocator"
        )
        await session.commit()
        assert saved.snapshot["costs"][0]["issue_cost_byn"] == stock_cost


async def test_late_inventory_change_in_same_transaction_invalidates_receipt(physical_pg):
    factory, org, act, data = await prepare_accounting(physical_pg)
    async with factory() as session:
        plan = await shipment_preview.prepare(session, org, act, data)
        await shipment_commands.confirm(session, org, act, data, plan["basis_digest"], "allocator")
        await service.post(
            session,
            org,
            PostingInput(
                source="late-same-price-stock",
                source_version=1,
                operation="manual",
                document_date=data.document_date,
                operation_date=data.document_date,
                posting_date=data.posting_date,
                policy_id=data.policy_id,
                rule_version="synthetic",
                explanation="Late same-root acquisition",
                lines=[
                    {
                        "account": "41.2",
                        "side": "debit",
                        "amount": "10.00",
                        "quantity": "3",
                        "dimensions": {"warehouse": "W", "sku": "A", "lot": "L"},
                    },
                    {"account": "60", "side": "credit", "amount": "10.00"},
                ],
            ),
            "allocator",
        )
        with pytest.raises(DBAPIError, match="Shipment inventory cost differs"):
            await session.commit()
        await session.rollback()
        assert await session.scalar(select(func.count()).select_from(models.Entry)) == 1
        assert (
            await session.scalar(select(func.count()).select_from(models.ShipmentAccountingReceipt))
            == 0
        )
        assert (
            await session.scalar(
                select(models.SourceControl.entry_id).where(
                    models.SourceControl.source == plan["source"]
                )
            )
            is None
        )


async def test_real_act_package_and_replay_with_sql_envelope_guards(physical_pg):
    factory, org, act, data = await prepare_accounting(physical_pg)
    async with factory() as session:
        plan = await shipment_preview.prepare(session, org, act, data)
        saved = await shipment_commands.confirm(
            session, org, act, data, plan["basis_digest"], "allocator"
        )
        saved_id = saved.id
        await session.commit()
    async with factory() as session:
        saved = await shipment_commands.confirm(
            session, org, act, data, plan["basis_digest"], "allocator"
        )
        assert saved.id == saved_id
    async with factory() as session:
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(
                text(
                    "UPDATE accounting.shipment_accounting_receipt SET actor='forged' WHERE id=:id"
                ),
                {"id": saved_id},
            )
        await session.rollback()

    async with factory() as session:
        with pytest.raises(DBAPIError, match="Shipment receipt ledger lines are finalized"):
            await session.execute(
                text(
                    "INSERT INTO accounting.line (entry_id,account_id,account_code,account_title,category,cash,side,amount,dimensions,currency) "
                    "SELECT entry_id,account_id,account_code,account_title,category,cash,side,amount,dimensions,currency "
                    "FROM accounting.line WHERE entry_id=:entry LIMIT 1"
                ),
                {"entry": saved.anchor_entry_id},
            )
        await session.rollback()
    async with factory() as session:
        late = deepcopy(plan["postings"][0]["posting"])
        late["source"] += ":part:2"
        with pytest.raises(DBAPIError, match="Shipment receipt ledger pages are finalized"):
            await service.post(session, org, PostingInput(**late), "allocator", inventory_sale=True)
        await session.rollback()


@pytest.mark.parametrize("tamper", ["quantity", "commercial_omission", "cost", "cent_distribution"])
async def test_self_consistent_forged_manifest_rejected_by_sql(physical_pg, monkeypatch, tamper):
    factory, org, act, data = await prepare_accounting(
        physical_pg,
        full=tamper == "cent_distribution",
        stock_cost="0.01" if tamper == "cent_distribution" else "10.00",
    )
    async with factory() as session:
        plan = deepcopy(await shipment_preview.prepare(session, org, act, data))
        if tamper == "quantity":
            plan["mapping"][0]["quantity"] = "0.50"
        elif tamper == "cent_distribution":
            plan["mapping"][0]["cost_byn"], plan["mapping"][1]["cost_byn"] = (
                plan["mapping"][1]["cost_byn"],
                plan["mapping"][0]["cost_byn"],
            )
        elif tamper == "cost":
            plan["mapping"][0]["cost_byn"] = "4.00"
            plan["costs"][0]["issue_cost_byn"] = "4.00"
            for page in plan["postings"]:
                for line in page["posting"]["lines"]:
                    if line["account"] in {"41.2", "90.4"}:
                        line["amount"] = "4.00"
        else:
            for page in plan["postings"]:
                page["posting"]["lines"] = [
                    line for line in page["posting"]["lines"] if line["account"] in {"41.2", "90.4"}
                ]
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

        async def untrusted_application_plan(*args, **kwargs):
            return plan

        # Keep real DB triggers enabled. Simulate a faulty application supplying
        # matching hashes: SQL must independently reject the incorrect package.
        monkeypatch.setattr(shipment_preview, "prepare", untrusted_application_plan)
        with pytest.raises(DBAPIError, match="Shipment|shipment"):
            await shipment_commands.confirm(
                session, org, act, data, plan["basis_digest"], "allocator"
            )
            await session.commit()
        await session.rollback()
