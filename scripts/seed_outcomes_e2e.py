"""Synthetic-only prerequisites for existing owned CRM outcome E2E deals."""
import asyncio
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.engine import URL

from config.access import USERS
from core.domain.models import Counterparty, Sku
from core.services.db import Database
from modules.accounting.models import AccessGrant, Organization
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.client_document_register import DealClientBinding, preview_snapshot
from modules.sales.models import CrmClient, Deal, DealItem, LossReason
from modules.wms.models import StockMovement, WarehouseDirectory


async def main():
    root = Path(__file__).resolve().parents[1]
    path = root / "e2e.db"
    if os.environ.get("AIOS_E2E_SEED") != "1" or not path.is_file() or path.is_symlink():
        raise RuntimeError("Only an existing dedicated e2e.db may be seeded")
    auth_state = root / "frontend/e2e/.auth/state.json"
    if not auth_state.is_file() or auth_state.is_symlink() or auth_state.stat().st_size > 16384:
        raise RuntimeError("Expected the local synthetic setup session")
    state = json.loads(auth_state.read_text(encoding="utf-8"))
    approver = next((cookie.get("value") for cookie in state.get("cookies", [])
                     if cookie.get("name") == "aios_actor"), None)
    if not any(user.get("username") == approver and user.get("role") == "director" for user in USERS):
        raise RuntimeError("Synthetic setup must use the existing dev director fixture")
    command = json.load(sys.stdin)
    actor, deal_id = command.get("actor"), command.get("deal_id")
    if actor != "e2e_owner" or type(deal_id) is not int or deal_id <= 0:
        raise ValueError("Invalid synthetic actor or deal")
    db = Database(SimpleNamespace(database_url=URL.create(
        "sqlite+aiosqlite", database=str(path)).render_as_string(hide_password=False)))
    db.init_engine()
    try:
        async with db.session_factory() as session:
            deal = await session.get(Deal, deal_id)
            if not deal or not deal.number.startswith(("OUTCOME-stock-", "OUTCOME-on_order-")) or deal.owner_id != 2901:
                raise RuntimeError("Refusing to modify a non-outcome synthetic deal")
            client = await session.get(CrmClient, deal.crm_client_id) if deal.crm_client_id else None
            if not client or client.owner_id != 2901 or not client.name.startswith("Outcome ") or deal.counterparty_id or client.counterparty_id:
                raise RuntimeError("Refusing to modify a non-synthetic CRM relationship")
            items = (await session.scalars(select(DealItem).where(DealItem.deal_id == deal.id))).all()
            if len(items) != 1 or items[0].qty != Decimal(2):
                raise RuntimeError("Expected exactly one synthetic deal line")
            sku = await session.get(Sku, items[0].sku_id)
            expected = "QA-STOCK" if deal.number.startswith("OUTCOME-stock-") else "QA-ORDER"
            if not sku or sku.code != expected:
                raise RuntimeError("Unexpected synthetic product")
            token = uuid4().hex
            org = Organization(name="E2E outcome seller", unp=str(100000000 + int(token[:8], 16) % 400000000))
            buyer = Counterparty(name=client.name, legal_name=client.name,
                unp=str(500000000 + int(token[8:16], 16) % 400000000),
                requisites={"legal_address": "Synthetic E2E buyer address"})
            session.add_all([org, buyer])
            await session.flush()
            deal.counterparty_id = buyer.id
            client.counterparty_id = buyer.id
            session.add_all([AccessGrant(organization_id=org.id, subject=actor, role="chief"),
                AccessGrant(organization_id=org.id, subject=approver, role="chief"),
                DealOwnership(deal_id=deal.id, organization_id=org.id, snapshot={}, evidence="Synthetic E2E ownership", actor=actor)])
            await session.flush()
            session.add(DealClientBinding(deal_id=deal.id, organization_id=org.id, counterparty_id=buyer.id,
                snapshot=await preview_snapshot(session, org.id, deal, buyer.id), evidence="Synthetic E2E buyer", actor=actor))
            reason = "e2e-" + token[:24]
            session.add(LossReason(code=reason, title="Synthetic E2E loss reason", active=True))
            if expected == "QA-STOCK":
                session.add(WarehouseDirectory(organization_id=org.id, name="E2E-W", title="Synthetic warehouse", created_by=actor, wms_enabled=False, prohibit_negative_stock=True))
                session.add(StockMovement(organization_id=org.id, sku_code=sku.code, warehouse="E2E-W", kind="in", qty=Decimal(10), reason="receipt"))
            await session.commit()
            print(json.dumps({"organization": org.id, "item": items[0].id, "buyer": buyer.id, "loss_reason": reason}))
    finally:
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
