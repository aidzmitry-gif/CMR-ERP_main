"""Synthetic joint-head financial proof; no pytest, live URL, or ORM DDL.

Uses the G03 dedicated role/admin target and actual Alembic upgrade. An optional
G04_SERVE=1 keeps the last synthetic case available to the primary's browser;
its database is still removed when the server exits normally.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.integration.crm_rel_001_migration_proof import (  # noqa: E402
    ADMIN_DATABASE,
    HEAD,
    connect,
    selected_url,
    upgrade,
)

DAY = "2026-09-12"
MONTH = "2026-09"
ACTOR = "kharkovich_d"


def estimate(purpose):
    # Frozen G01 oracle / tests.accounting.test_assembly_estimate.example.
    return {
        "product": "G04 synthetic assembly", "quantity": "10", "purpose": purpose,
        "reference": "G04 synthetic order", "specification": "Synthetic BOM",
        "as_of": DAY,
        "components": [
            {"name": "Cell", "per_unit": "4", "loss_percent": "5",
             "unit_cost_byn": "2.5", "price_basis": "Synthetic quote"},
            {"name": "Case", "per_unit": "1", "unit_cost_byn": "3",
             "price_basis": "Synthetic quote"},
        ],
        "batch_costs": {"labor_byn": "20", "contributions_byn": "7",
                        "subcontract_byn": "0", "overhead_byn": "10", "packaging_byn": "5"},
        "sale_unit_net_byn": "30",
    }


async def checked(api, method, path, body=None, status=200):
    response = await api.request(method, path, **({"json": body} if body is not None else {}))
    assert response.status_code == status, (method, path, response.status_code, response.text[:1200])
    return response.json()


def refused_populated_downgrade(url):
    """Actual Alembic refusal on this marked disposable target, with exact readback."""
    admin_url = selected_url()
    assert url.set(database=ADMIN_DATABASE) == admin_url, "Downgrade target differs from gated cluster"
    assert url.database.startswith("crm_rel_001_g04_"), "Downgrade requires the generated disposable database"
    functions = (
        "accounting.validate_shipment_output_layer(integer,integer,integer,text,date,integer)",
        "accounting.validate_shipment_costs(integer)",
        "accounting.validate_shipment_receipt(integer)",
    )

    def readback():
        with connect(url) as connection:
            marker = connection.execute(
                "SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=%s",
                (url.database,),
            ).fetchone()
            assert marker == ("crm-rel-001-g04:" + url.database,), "Downgrade database marker changed"
            state = {"head": connection.execute("SELECT version_num FROM alembic_version ORDER BY version_num").fetchall()}
            for table, order in (("shipment_accounting_receipt", "id"),
                                 ("production_output_transfer_receipt", "entry_id"),
                                 ("entry", "id"), ("line", "id")):
                state[table] = connection.execute(
                    f"SELECT row_to_json(r)::text FROM accounting.{table} r ORDER BY {order}"
                ).fetchall()
            state["functions"] = [connection.execute(
                "SELECT pg_get_functiondef(%s::regprocedure)", (name,)
            ).fetchone()[0] for name in functions]
            return state

    before = readback()
    assert before["head"] == [(HEAD,)] and before["shipment_accounting_receipt"]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "crm_rel_001_joint_01"],
        cwd=ROOT,
        env={**os.environ, "AIOS_ENVIRONMENT": "dev",
             "AIOS_DATABASE_URL": url.render_as_string(hide_password=False), "PYTHONDONTWRITEBYTECODE": "1"},
        text=True, capture_output=True, timeout=300,
    )
    detail = result.stdout + result.stderr
    if url.password:
        detail = detail.replace(url.password, "<redacted>")
    assert result.returncode != 0, "Populated43 downgrade unexpectedly succeeded"
    assert "Cannot downgrade finished-goods shipment history" in detail, detail[-1500:]
    assert readback() == before, "Refused downgrade changed head, receipts, ledger or function definitions"
    return {"status": "refused_without_mutation", "head": HEAD,
            "exact_readback": "head/receipts/entries/lines/three_functions"}


async def sql_output_guards(factory, org, policy_id, entry_id):
    """Direct SQL adversaries, each isolated by rollback; never disable a guard."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    async with factory() as session:
        line = (await session.execute(text("SELECT id FROM accounting.line WHERE entry_id=:e AND side='debit'"), {"e": entry_id})).scalar_one()
        credit = (await session.execute(text("SELECT id FROM accounting.line WHERE entry_id=:e AND side='credit' ORDER BY id LIMIT 1"), {"e": entry_id})).scalar_one()
        boundary = await session.scalar(text("SELECT nextval(pg_get_serial_sequence('accounting.entry','id'))"))
        query = text("SELECT accounting.validate_shipment_output_layer(:org,:entry,:line,:account,:day,:boundary)")
        params = {"org": org, "entry": entry_id, "line": line, "account": "43", "day": date.fromisoformat(DAY), "boundary": boundary}
        await session.execute(query, params)  # Authentic complete output is mandatory.
        rejected = []

        async def reject(label, values, before=None):
            transaction = await session.begin_nested()
            try:
                if before is not None:
                    await before()
                try:
                    await session.execute(query, {**params, **values})
                except DBAPIError as error:
                    assert getattr(error.orig, "sqlstate", None) == "P0001", (label, str(error)[:500])
                    if label == "stale_wip_source":
                        assert error.orig.diag.message_primary == "Shipment output WIP source basis is stale", str(error)[:500]
                    rejected.append(label)
                else:
                    raise AssertionError(f"Direct SQL accepted {label}")
            finally:
                await transaction.rollback()

        await reject("wrong_org", {"org": org + 999999})
        await reject("arbitrary_43_account", {"account": "43.999"})
        await reject("wrong_quantity_line", {"line": credit})
        await reject("unreceipted_debit", {"entry": boundary})

        async def wrong_policy():
            # A later independently valid policy cannot rewrite the output's policy provenance.
            await session.execute(text("""INSERT INTO accounting.policy
                (organization_id,effective_from,reference,inventory_method,allocation_basis,depreciation_method,
                 normative_reference,normative_verified,approved_by,production_costing)
                SELECT organization_id,:day,'Synthetic wrong output policy',inventory_method,allocation_basis,
                 depreciation_method,normative_reference,normative_verified,approved_by,production_costing
                FROM accounting.policy WHERE id=:policy"""), {"day": date.fromisoformat(DAY), "policy": policy_id})
        await reject("wrong_effective_output_policy", {}, wrong_policy)

        async def original_state():
            return {
                "receipt": (await session.execute(text("SELECT row_to_json(r)::text FROM accounting.production_output_transfer_receipt r WHERE r.organization_id=:org ORDER BY r.entry_id"), {"org": org})).scalars().all(),
                "entries": (await session.execute(text("SELECT row_to_json(e)::text FROM accounting.entry e WHERE e.organization_id=:org ORDER BY e.id"), {"org": org})).scalars().all(),
                "lines": (await session.execute(text("SELECT row_to_json(l)::text FROM accounting.line l JOIN accounting.entry e ON e.id=l.entry_id WHERE e.organization_id=:org ORDER BY l.id"), {"org": org})).scalars().all(),
            }

        before_stale = await original_state()
        clone_entries = []

        async def stale_source():
            wip = await session.scalar(text("SELECT e.id FROM accounting.entry e JOIN accounting.line l ON l.entry_id=e.id WHERE e.organization_id=:org AND l.account_code='20' AND l.side='debit' ORDER BY e.id LIMIT 1"), {"org": org})
            fresh = await session.scalar(text("""INSERT INTO accounting.entry
                (organization_id,source,source_version,operation,document_date,operation_date,posting_date,
                 policy_id,rule_version,explanation,opening,actor,digest)
                SELECT organization_id,'g12:synthetic-stale-wip',1,'manual',document_date,operation_date,posting_date,
                 policy_id,rule_version,'Synthetic direct SQL stale source',opening,actor,digest
                FROM accounting.entry WHERE id=:wip RETURNING id"""), {"wip": wip})
            clone_entries.append(fresh)
            await session.execute(text("""INSERT INTO accounting.line
                (entry_id,account_id,account_code,account_title,side,amount,currency,dimensions,quantity,category,cash,
                 original_amount,rate,rate_scale,rate_date,rate_source,cash_activity)
                SELECT :fresh,account_id,account_code,account_title,side,amount,currency,dimensions,quantity,category,cash,
                 original_amount,rate,rate_scale,rate_date,rate_source,cash_activity
                FROM accounting.line WHERE entry_id=:wip"""), {"fresh": fresh, "wip": wip})
            params["boundary"] = await session.scalar(text("SELECT nextval(pg_get_serial_sequence('accounting.entry','id'))"))
        await reject("stale_wip_source", {}, stale_source)
        assert len(clone_entries) == 1
        assert await session.scalar(text("SELECT count(*) FROM accounting.entry WHERE id=:clone"), {"clone": clone_entries[0]}) == 0
        assert await session.scalar(text("SELECT count(*) FROM accounting.line WHERE entry_id=:clone"), {"clone": clone_entries[0]}) == 0
        assert await original_state() == before_stale, "Stale-source rollback changed original receipt or ledger"
        await session.rollback()
        return rejected


async def sql_shipment_guards(factory, org, act, command, plan):
    """Insert forged whole-act receipts directly; all temporary postings roll back."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from modules.accounting import service, shipment_preview
    from modules.accounting.models import Organization
    from modules.accounting.schemas import PostingInput

    rejected = []
    for case in ("wrong_shipment_policy", "wrong_shipment_org", "arbitrary_43_mapping",
                 "wrong_analytics", "wrong_quantity", "missing_coverage"):
        async with factory() as session:
            inputs = deepcopy(command)
            snapshot = {"act": deepcopy(act), "mapping": deepcopy(plan["mapping"]),
                        "costs": deepcopy(plan["costs"]), "commercial": deepcopy(plan["commercial"]), "pages": []}
            target_org = org
            if case == "wrong_shipment_policy":
                inputs["policy_id"] += 999999
            elif case == "wrong_shipment_org":
                foreign_readback = text("""SELECT 'output_receipt',r.entry_id,row_to_json(r)::text
                    FROM accounting.production_output_transfer_receipt r WHERE r.organization_id=:org
                    UNION ALL SELECT 'shipment_receipt',r.id,row_to_json(r)::text
                    FROM accounting.shipment_accounting_receipt r WHERE r.organization_id=:org
                    UNION ALL SELECT 'entry',e.id,row_to_json(e)::text
                    FROM accounting.entry e WHERE e.organization_id=:org
                    UNION ALL SELECT 'line',l.id,row_to_json(l)::text
                    FROM accounting.line l JOIN accounting.entry e ON e.id=l.entry_id WHERE e.organization_id=:org
                    ORDER BY 1,2""")
                before_foreign = (await session.execute(foreign_readback, {"org": org})).all()
                other = Organization(name="G12 synthetic foreign receipt", unp="999000002")
                session.add(other)
                await session.flush()
                target_org = other.id
            elif case == "arbitrary_43_mapping":
                snapshot["mapping"][0]["account"] = "43.999"
                inputs["allocations"][0]["account"] = "43.999"
            elif case == "wrong_analytics":
                snapshot["costs"][0]["inventory_dimensions"]["warehouse"] = "FORGED"
            elif case == "wrong_quantity":
                snapshot["mapping"][0]["quantity"] = "11.000000"
                inputs["allocations"][0]["quantity"] = "11.000000"
            elif case == "missing_coverage":
                snapshot["mapping"] = []
                inputs["allocations"] = []
            basis = {"act_digest": act["digest"], "inputs": inputs, "mapping": snapshot["mapping"],
                     "costs": snapshot["costs"], "commercial": snapshot["commercial"]}
            checksum = hashlib.sha256(shipment_preview.canonical(basis).encode()).hexdigest()
            for page in plan["postings"]:
                posting = PostingInput.model_validate({**page["posting"], "rule_version": "shipment-sale-v1:" + checksum})
                entry = await service.post(session, org, posting, ACTOR, inventory_sale=True)
                snapshot["pages"].append({"entry_id": entry.id, "digest": service.digest(posting),
                                          "posting": posting.model_dump(mode="json")})
            try:
                await session.execute(text("""INSERT INTO accounting.shipment_accounting_receipt
                    (organization_id,source,act_digest,command,basis_digest,snapshot,anchor_entry_id,actor)
                    VALUES (:org,:source,:act,CAST(:command AS json),:basis,CAST(:snapshot AS json),:entry,:actor)"""),
                    {"org": target_org, "source": plan["source"], "act": act["digest"],
                     "command": json.dumps(inputs), "basis": checksum, "snapshot": json.dumps(snapshot),
                     "entry": snapshot["pages"][0]["entry_id"], "actor": ACTOR})
            except DBAPIError as error:
                assert getattr(error.orig, "sqlstate", None) == "P0001", (case, str(error)[:500])
                if case == "wrong_shipment_org":
                    assert error.orig.diag.message_primary == "Financial entry must belong to the same organization and root transaction", str(error)[:500]
                rejected.append(case)
            else:
                raise AssertionError(f"Direct SQL accepted {case}")
            finally:
                await session.rollback()
            if case == "wrong_shipment_org":
                temporary_entries = [page["entry_id"] for page in snapshot["pages"]]
                assert await session.scalar(text("SELECT count(*) FROM accounting.organization WHERE id=:org"), {"org": target_org}) == 0
                assert await session.scalar(text("SELECT count(*) FROM accounting.entry WHERE id=ANY(:ids)"), {"ids": temporary_entries}) == 0
                assert await session.scalar(text("SELECT count(*) FROM accounting.line WHERE entry_id=ANY(:ids)"), {"ids": temporary_entries}) == 0
                assert await session.scalar(text("SELECT count(*) FROM accounting.shipment_accounting_receipt WHERE organization_id=:org OR anchor_entry_id=ANY(:ids)"), {"org": target_org, "ids": temporary_entries}) == 0
                assert (await session.execute(foreign_readback, {"org": org})).all() == before_foreign, "Foreign receipt rollback changed original receipts or ledger"
    return rejected


async def scenario(url, purpose, *, legacy=False):
    # Settings are selected before create_app; transport does not run lifespan.
    os.environ["AIOS_ENVIRONMENT"] = "dev"
    os.environ["AIOS_DATABASE_URL"] = url.render_as_string(hide_password=False)
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import func, select, text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from core.domain.models import Counterparty, Sku
    from core.runtime.app import create_app
    from core.runtime.deps import get_session
    from core.services.auth import CurrentUser
    from modules.accounting import service
    from modules.accounting.gateway import AccountingService
    from modules.accounting.models import AccessGrant, Account, Entry, Organization, Policy
    from modules.accounting.schemas import PostingInput
    from modules.production.accounting_ownership import (
        OwnershipCommand,
        assign_order,
        order_snapshot,
    )
    from modules.production.models import ProductionOrder
    from modules.production.output_documents import OutputDocument
    from modules.sales.accounting_ownership import DealOwnership
    from modules.sales.client_document_register import DealClientBinding, preview_snapshot
    from modules.sales.models import Deal, DealItem
    from modules.sales.reservation_source import SalesReservationSource
    from modules.wms.models import Location, Receipt, ReceiptLine, StockMovement
    from modules.wms.reservation_events import apply

    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app()
    app.state.core.services.db.session_factory = factory

    async def sessions():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    try:
        async with factory() as session:
            assert await session.scalar(text("SELECT version_num FROM alembic_version")) == ("crm_rel_001_joint_01" if legacy else HEAD)
            org = Organization(name=f"G04 synthetic {purpose}", unp="999000001")
            buyer = Counterparty(name="G04 synthetic buyer", unp="999000002", requisites={"address": "Synthetic"})
            sku = Sku(code="G04-OUTPUT", title="G04 synthetic goods", unit="шт")
            order = ProductionOrder(number="G04-ORDER", product="G04 synthetic goods", qty=10)
            place = Location(warehouse="W", code="G04-RECEIVING")
            session.add_all([org, buyer, sku, order, place])
            await session.flush()
            session.add(AccessGrant(organization_id=org.id, subject=ACTOR, role="chief"))
            goods_account = "41.2" if legacy else "43"
            categories = {"20": "asset", "25": "expense", goods_account: "asset", "60": "liability",
                          "62": "asset", "90.1": "income", "90.2": "income",
                          "68.2": "liability", "90.4": "expense"}
            for code, category in categories.items():
                session.add(Account(organization_id=org.id, code=code, title="Synthetic " + code,
                    category=category, valid_from=date(2026, 1, 1),
                    required_dimensions={"20": ["department", "order"], "25": ["department"],
                                         goods_account: ["warehouse", "sku", "lot"]}.get(code, []),
                    currency_tracking=False, quantity_tracking=code == goods_account, cash=False,
                    normative_ref="Synthetic proof only"))
            # Explicit synthetic policy; no remapping of real 1C or OSV accounts.
            policy = Policy(organization_id=org.id, effective_from=date(2026, 1, 1),
                reference="G04 synthetic policy", inventory_method="specific", allocation_basis="direct_cost",
                depreciation_method="straight_line", normative_reference="Synthetic proof only",
                normative_verified=True, approved_by=ACTOR,  # This disposable fixture alone may exercise close guards.
                production_costing={"overhead_accounts": ["25"], "wip_account": "20",
                    "finished_goods_account": goods_account, "pool_dimensions": ["department"],
                    "order_dimension": "order", "rounding": "largest_remainder_cent",
                    "reference": "Synthetic G04 chosen account"})
            session.add(policy)
            await session.flush()
            digest = order_snapshot(order)[1]
            await assign_order(session, AccountingService(), org.id, CurrentUser(ACTOR, ["director"]),
                OwnershipCommand(order_id=order.id, expected_digest=digest, evidence="Synthetic G04 ownership"))
            await session.commit()
            org_id, policy_id, order_id, place_id = org.id, policy.id, order.id, place.id

        headers = {"X-User": ACTOR, "X-User-Roles": "director", "X-Expected-Principal": ACTOR}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers) as api:
            estimate_path = f"/accounting/organizations/{org_id}/assembly-estimate"
            result = await checked(api, "POST", estimate_path, estimate(purpose))
            expected = {"total_cost_byn": "177.00", "unit_cost_byn": "17.700000",
                        "revenue_net_byn": "300.00", "gross_profit_byn": "123.00", "margin_percent": "41.00"}
            assert all(result[k] == v for k, v in expected.items()) and result["posted"] is False
            missing = estimate(purpose)
            missing["components"][0]["unit_cost_byn"] = None
            unknown = await checked(api, "POST", estimate_path, missing)
            assert unknown["status"] == "incomplete"
            assert all(unknown[k] is None for k in ("total_cost_byn", "unit_cost_byn", "gross_profit_byn", "margin_percent"))
            assert (await api.post(estimate_path.replace(str(org_id), "999999"), json=estimate(purpose))).status_code in {403, 404}
            async with factory() as session:
                assert await session.scalar(select(func.count()).select_from(Entry)) == 0
                assert await session.scalar(select(func.count()).select_from(StockMovement)) == 0

            production_path = f"/production/organizations/{org_id}"
            output_command = {"request_id": str(uuid4()), "order_id": order_id,
                "expected_order_digest": digest, "operation_date": DAY, "sku_code": sku.code,
                "quantity": "10.00", "warehouse": "W", "location_id": place_id,
                "lot": "G04-LOT", "evidence": "Synthetic G04 physical output"}
            document = await checked(api, "POST", production_path + "/output-documents", output_command)
            assert await checked(api, "POST", production_path + "/output-documents", output_command) == document
            output_path = production_path + "/output-documents/" + output_command["request_id"]
            confirmation = {"expected_digest": document["digest"]}
            await checked(api, "POST", output_path + "/confirm", confirmation)
            await checked(api, "POST", output_path + "/confirm", confirmation)
            bus, services = app.state.core.event_bus, app.state.core.services
            assert await bus.relay_pending(factory, services, event_types=("production.output.confirmed",)) == 1
            assert await bus.relay_pending(factory, services, event_types=("production.output.confirmed",)) == 0
            async with factory() as session:
                receipt = await session.scalar(select(Receipt))
                line = await session.scalar(select(ReceiptLine))
                assert line.expected_qty == Decimal("10") and receipt.organization_id == org_id
                receipt_id, line_id = receipt.id, line.id
                output_id = await session.scalar(select(OutputDocument.id))
                assert await session.scalar(select(func.count()).select_from(StockMovement)) == 0
            receipt_path = f"/wms/receipts/{receipt_id}"
            detail = await checked(api, "GET", receipt_path)
            await checked(api, "POST", receipt_path + "/qc", {"expected_revision": detail["qc_revision"],
                "decisions": [{"line_id": line_id, "accepted_qty": "10.00", "rejected_qty": "0.00", "reject_reason": ""}]})
            await checked(api, "POST", receipt_path + "/accept")

            completion_path = production_path + f"/orders/{order_id}/completion"
            completion_preview = await checked(api, "GET", completion_path + "-preview")
            completion_command = {"expected_digest": completion_preview["digest"],
                                  "operation_date": DAY, "evidence": "Synthetic G04 complete accepted output"}
            completed = await checked(api, "POST", completion_path, completion_command)
            assert await checked(api, "POST", completion_path, completion_command) == completed
            async with factory() as session:
                completed_order = await session.get(ProductionOrder, order_id)
                assert completed_order.stage == "done"
                assert completed_order.made_qty == 10 and completed_order.progress == 100
                assert await session.scalar(text("SELECT count(*) FROM production.order_completion")) == 1
                assert await session.scalar(select(func.count()).select_from(StockMovement)) == 1

            async with factory() as session:
                wip = PostingInput(source="g04:synthetic-reviewed-wip", source_version=1, operation="manual",
                    document_date=DAY, operation_date=DAY, posting_date=DAY, policy_id=policy_id,
                    rule_version="g04-synthetic-v1", explanation="Synthetic known WIP, not live accounting acceptance",
                    lines=[{"account": "20", "side": "debit", "amount": "177.00",
                            "dimensions": {"department": "SHOP", "order": "G04-ORDER"}},
                           {"account": "60", "side": "credit", "amount": "177.00"}])
                await service.post(session, org_id, wip, ACTOR)
                await session.commit()
            transfer_path = f"/accounting/organizations/{org_id}/periods/{MONTH}/production-output-transfer"
            transfer = {"policy_id": policy_id, "order_id": order_id, "analytical_order": "G04-ORDER",
                        "department": "SHOP", "warehouse": "W", "posting_date": DAY, "output_document_ids": [output_id]}
            preview = await checked(api, "POST", transfer_path + "-preview", transfer)
            assert preview["candidate_transfer_byn"] == "177.00" and preview["final_cost_certified"] is False
            transfer_command = {**transfer, "basis_digest": preview["basis_digest"], "digest": preview["digest"]}
            posted = await checked(api, "POST", transfer_path + "-confirm", transfer_command, status=201)
            replayed = await checked(api, "POST", transfer_path + "-confirm", transfer_command, status=201)
            assert replayed["entry_id"] == posted["entry_id"]
            sql_rejections = [] if legacy else await sql_output_guards(factory, org_id, policy_id, posted["entry_id"])

            # Reuse the exact issuance/buyer binding contract of test_invoice_issuance.seed,
            # with stock supplied by the actual production receipt rather than a fake movement.
            async with factory() as session:
                deal = Deal(number="G04-DEAL", title="Synthetic G04 sale", counterparty="Ignored display text", amount=999)
                session.add(deal)
                await session.flush()
                item = DealItem(deal_id=deal.id, sku_id=sku.id, qty=Decimal("10"))
                session.add_all([item, DealOwnership(deal_id=deal.id, organization_id=org_id,
                    snapshot={}, evidence="Synthetic G04 deal ownership", actor=ACTOR)])
                await session.flush()
                session.add(DealClientBinding(deal_id=deal.id, organization_id=org_id, counterparty_id=buyer.id,
                    snapshot=await preview_snapshot(session, org_id, deal, buyer.id), evidence="Synthetic exact buyer", actor=ACTOR))
                await session.commit()
                deal_id, item_id = deal.id, item.id
            await checked(api, "POST", f"/accounting/organizations/{org_id}/seller-profiles", {
                "source_key": "g04-seller", "expected_revision": 0, "effective_from": "2026-01-01", "currency": "BYN",
                "address": "Synthetic", "account": "SYNTHETIC", "bank": "SYNTHETIC", "bik": "SYNTHETIC",
                "director": "Synthetic", "evidence": "Synthetic G04 seller profile", "confirmed": True}, status=201)
            invoice_base = {"organization_id": org_id, "currency": "BYN", "document_date": DAY,
                "valid_until": "2026-09-30", "pricing": [{"item_id": item_id, "unit_price_net": "30.00", "vat_rate": "20.00"}],
                "pricing_evidence": "Explicit synthetic G04 net price and VAT"}
            invoice_preview = await checked(api, "POST", f"/sales/deals/{deal_id}/invoice-preview", invoice_base)
            issue = {**invoice_base, "kind": "invoice", "request_key": "g04-issue",
                "expected_document_version": invoice_preview["document_version"],
                "expected_basis_digest": invoice_preview["basis_digest"],
                "allocations": [{"line_no": r["line_no"], "warehouse": "W", "qty": r["qty"]} for r in invoice_preview["lines"]],
                "evidence": "Synthetic complete physical journal", "journal_complete": True}
            issued = await checked(api, "POST", f"/sales/deals/{deal_id}/documents", issue, status=201)
            invoice_id = issued["document"]["id"]
            async with factory() as session:
                facts = await SalesReservationSource().invoice_reservation(session, invoice_id)
                await apply(session, invoice_id, [(sku.code, "W", Decimal("10"))], organization_id=org_id, release=False)
                await session.commit()
            shipment_path = f"/wms/organizations/{org_id}/invoices/{invoice_id}/physical-shipments"
            identity = {"expected_version": facts["version"], "expected_content_sha256": facts["content_sha256"]}
            basis = await checked(api, "POST", shipment_path + "/preview", identity)
            physical = {**identity, "source_key": str(uuid4()), "operation_date": DAY,
                "expected_reservation_digest": basis["reservation_digest"], "expected_remaining_digest": basis["remaining_digest"],
                "expected_physical_digest": basis["physical_digest"], "evidence": "Synthetic G04 authorized physical release",
                "lines": [{"line_no": 1, "warehouse": "W", "qty": "10.00"}]}
            act = await checked(api, "POST", shipment_path, physical, status=201)
            assert await checked(api, "POST", shipment_path, physical, status=201) == act
            accounting_path = f"/accounting/organizations/{org_id}/shipments/{physical['source_key']}"
            shipment = {"expected_act_digest": act["digest"], "policy_id": policy_id, "document_date": DAY, "posting_date": DAY,
                "explanation": "Synthetic G04 shipment", "recognition": "sale_on_shipment", "recognition_basis": "Synthetic decision",
                "unit_basis": "Same units", "cost_allocation": "cumulative_floor_last", "vat_rounding": "commercial_line_half_up",
                "allocations": [{"line_source": r["source"], "account": goods_account, "lot": "G04-LOT", "quantity": r["qty"],
                                 "expense_account": "90.4"} for r in act["snapshot"]["lines"]],
                "commercial_lines": [{"line_no": 1, "net_amount": "300.00", "vat_rate": "20", "vat_basis": "Synthetic VAT",
                    "buyer_account": "62", "revenue_account": "90.1", "vat_revenue_account": "90.2", "vat_payable_account": "68.2",
                    "buyer_dimensions": {"counterparty": buyer.name, "contract": "G04 synthetic", "settlement_document": f"sales:document:{invoice_id}"}}]}
            planned = await checked(api, "POST", accounting_path + "/preview", shipment)
            if not legacy:
                sql_rejections += await sql_shipment_guards(factory, org_id, act, shipment, planned)
            shipment_command = {**shipment, "expected_basis_digest": planned["basis_digest"]}
            saved = await checked(api, "POST", accounting_path + "/confirm", shipment_command, status=201)
            downgrade_refusal = None if legacy else await asyncio.to_thread(refused_populated_downgrade, url)
            if legacy:
                # Real historical receipt, generated by frozen joint head before the new migration.
                async with factory() as session:
                    before_legacy = (await session.execute(text("SELECT row_to_json(r)::text FROM accounting.shipment_accounting_receipt r"))).scalars().all()
                await asyncio.to_thread(upgrade, url, HEAD)
            repeated = await checked(api, "POST", accounting_path + "/confirm", shipment_command, status=201)
            assert repeated == saved
            if legacy:
                async with factory() as session:
                    assert (await session.execute(text("SELECT row_to_json(r)::text FROM accounting.shipment_accounting_receipt r"))).scalars().all() == before_legacy
            # Production output still has its own unresolved primary control;
            # the output-transfer source does not resolve that different source.
            # Observe refusal honestly; this proves neither close nor closed replay.
            from modules.accounting.schemas import CloseInput
            async with factory() as session:
                period = await service.period_for(session, org_id, MONTH)
                pending = (await session.execute(text("""SELECT source,version,month,entry_id
                    FROM accounting.source_control WHERE organization_id=:org AND month<=:month AND entry_id IS NULL
                    ORDER BY source,version,id"""), {"org": org_id, "month": MONTH})).mappings().all()
                assert any(dict(row) == {"source": f"production:output:{output_id}", "version": 1,
                                         "month": MONTH, "entry_id": None} for row in pending)
                close_readback = text("""SELECT 'period',p.id,row_to_json(p)::text
                    FROM accounting.period p WHERE p.organization_id=:org
                    UNION ALL SELECT 'control',c.id,row_to_json(c)::text
                    FROM accounting.source_control c WHERE c.organization_id=:org
                    UNION ALL SELECT 'output_receipt',r.entry_id,row_to_json(r)::text
                    FROM accounting.production_output_transfer_receipt r WHERE r.organization_id=:org
                    UNION ALL SELECT 'shipment_receipt',r.id,row_to_json(r)::text
                    FROM accounting.shipment_accounting_receipt r WHERE r.organization_id=:org
                    UNION ALL SELECT 'entry',e.id,row_to_json(e)::text
                    FROM accounting.entry e WHERE e.organization_id=:org
                    UNION ALL SELECT 'line',l.id,row_to_json(l)::text
                    FROM accounting.line l JOIN accounting.entry e ON e.id=l.entry_id WHERE e.organization_id=:org
                    ORDER BY 1,2""")
                before_close = (await session.execute(close_readback, {"org": org_id})).all()
                assert period.closed is False
                refusal_message = "Unposted primary documents prevent closing"
                try:
                    await service.close_period(session, org_id, MONTH, CloseInput(
                        expected_generation=period.generation,
                        evidence={step: "Synthetic disposable G12 replay control only" for step in service.CLOSE_STEPS}), ACTOR)
                except service.AccountingError as error:
                    assert str(error) == refusal_message, str(error)
                else:
                    raise AssertionError("Unresolved production primary control unexpectedly allowed close")
                finally:
                    await session.rollback()
                assert (await session.execute(close_readback, {"org": org_id})).all() == before_close, "Refused close changed period, controls, receipts or ledger"
                assert await session.scalar(text("SELECT closed FROM accounting.period WHERE organization_id=:org AND month=:month"), {"org": org_id, "month": MONTH}) is False
                close_refusal = {"status": "refused_without_mutation", "message": refusal_message,
                                 "pending_controls": [dict(row) for row in pending], "pending_count": len(pending)}
            assert await checked(api, "POST", accounting_path + "/confirm", shipment_command, status=201) == saved
            report_path = f"/accounting/organizations/{org_id}/reports/shipment-profit?start=2026-09-01&end=2026-09-30"
            report = await checked(api, "GET", report_path)
            assert report["basis"] == "at_posting" and len(report["rows"]) == 1
            assert report["page_subtotal"] == {"revenue_net_byn": "300.00", "cogs_byn": "177.00",
                                              "gross_profit_byn": "123.00", "margin_percent": "41.00"}
            assert report["rows"][0]["vat_byn"] == "60.00"
            assert all(report[k] is False for k in ("includes_later_adjustments", "includes_returns", "includes_unposted_shipments"))
            assert await checked(api, "GET", report_path) == report  # API readback/reload oracle.
            assert (await api.get(report_path.replace(str(org_id) + "/reports", "999999/reports"))).status_code in {403, 404}
            async with factory() as session:
                assert await session.scalar(text("SELECT sum(CASE WHEN kind='in' THEN qty ELSE -qty END) FROM wms.stock_movement")) == 0
                assert await session.scalar(select(func.count()).select_from(StockMovement)) == 2
                assert await session.scalar(text("SELECT sum(CASE WHEN side='debit' THEN amount ELSE -amount END) FROM accounting.line")) == 0
                assert await session.scalar(text("SELECT sum(CASE WHEN side='debit' THEN quantity ELSE -quantity END) FROM accounting.line WHERE account_code=:account"), {"account": goods_account}) == 0
                assert await session.scalar(text("SELECT count(*) FROM accounting.shipment_accounting_receipt")) == 1
            receipt = {"status": "passed", "purpose": purpose, "head": HEAD, "oracle": expected,
                "report": report["page_subtotal"], "basis": "at_posting", "stock_remaining": "0", "replay": "passed",
                "unknown_cost": "passed", "org_scope": "passed", "browser": "pending_primary",
                "organization_id": org_id, "order_id": order_id, "invoice_id": invoice_id,
                "goods_account": goods_account, "sql_rejections": sql_rejections, "legacy_upgrade_replay": legacy,
                "populated_downgrade": downgrade_refusal,
                "close_refusal": close_refusal, "open_period_replay": "passed",
                "synthetic_closed_period_replay": "not_proven", "real_period_close": "not_proven"}
            print(json.dumps(receipt), flush=True)
            return app, engine, receipt
    except BaseException:
        await engine.dispose()
        raise


async def main():
    assert os.environ.get("CRM_REL_001_G04_ACCEPTANCE") == "1", "Explicit G04 opt-in required"
    url = selected_url()  # Reuse unchanged strict G03 dedicated role/admin/loopback gate.
    from psycopg import sql
    with connect(url) as admin:
        databases = {r[0] for r in admin.execute("SELECT datname FROM pg_database WHERE NOT datistemplate")}
        assert databases <= {"postgres", ADMIN_DATABASE}, "Refusing a non-fresh disposable cluster"
        cases = []
        for purpose, legacy in (("customer_order", False), ("stock", False), ("legacy_41", True)):
            database = "crm_rel_001_g04_" + uuid4().hex
            marker = "crm-rel-001-g04:" + database
            target = url.set(database=database)
            engine = None
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
            admin.execute(sql.SQL("COMMENT ON DATABASE {} IS {}").format(sql.Identifier(database), sql.Literal(marker)))
            try:
                await asyncio.to_thread(upgrade, target, "crm_rel_001_joint_01" if legacy else HEAD)
                app, engine, receipt = await scenario(target, "customer_order" if legacy else purpose, legacy=legacy)
                cases.append(receipt)
                if purpose == "stock" and os.environ.get("CRM_REL_001_G04_SERVE") == "1":
                    import uvicorn
                    # Primary selects network/forwarding; only the isolated synthetic app is served.
                    port = int(os.environ.get("CRM_REL_001_G04_HTTP_PORT", "8080"))
                    assert 1024 <= port <= 65535, "Invalid isolated HTTP port"
                    print(json.dumps({**receipt, "status": "browser_fixture_ready", "port": port}), flush=True)
                    await uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port, lifespan="off", log_level="warning")).serve()
            finally:
                if engine is not None:
                    await engine.dispose()
                stored = admin.execute("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=%s", (database,)).fetchone()
                assert stored == (marker,), "Cleanup database marker changed"
                assert admin.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=%s", (database,)).fetchone()[0] == 0, "Cleanup connections remain"
                admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))
                print(json.dumps({"status": "cleanup_passed", "purpose": purpose}), flush=True)
        print(json.dumps({"status": "passed", "head": HEAD, "cases": cases, "production_changes": 0}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
