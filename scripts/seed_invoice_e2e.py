"""Seed only the dedicated local e2e.db for the real browser invoice flow."""
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

from core.domain.models import Counterparty, Sku
from core.services.db import Database
from modules.accounting.models import AccessGrant, Organization
from modules.sales.access import DealAccess
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.accounting_ownership import snapshot as ownership_snapshot
from modules.sales.client_document_register import DealClientBinding, preview_snapshot
from modules.sales.models import CrmClient, Deal, DealDocument, DealItem, LossReason
from modules.wms.models import StockMovement, WarehouseDirectory


async def main():
    root = Path(__file__).resolve().parents[1]
    path = root / "e2e.db"
    if os.environ.get("AIOS_E2E_SEED") != "1" or not path.is_file() or path.is_symlink():
        raise RuntimeError("Only an existing dedicated e2e.db may be seeded")
    command = json.load(sys.stdin)
    actor, deal_id = command["actor"], command["deal_id"]
    if not isinstance(actor, str) or not actor or len(actor) > 200:
        raise ValueError("Invalid test actor")
    if type(deal_id) is not int or deal_id <= 0:
        raise ValueError("Invalid test deal")
    item_id = command.get("item_id")
    reserve_mode = command.get("reserve_mode")
    physical_shipment = command.get("physical_shipment", False)
    foreign_book_reader = command.get("foreign_book_reader", False)
    if item_id is not None and (type(item_id) is not int or item_id <= 0):
        raise ValueError("Invalid selected UI item")
    if (reserve_mode not in {None, "stock", "on_order"}
            or (item_id is None) != (reserve_mode is None)
            or type(physical_shipment) is not bool
            or type(foreign_book_reader) is not bool
            or (physical_shipment and reserve_mode != "stock")):
        raise ValueError("Invoice fixture mode does not match its selected UI item")
    db = Database(SimpleNamespace(database_url=URL.create(
        "sqlite+aiosqlite", database=str(path)
    ).render_as_string(hide_password=False)))
    db.init_engine()
    try:
        async with db.session_factory() as session:
            deal = await session.get(Deal, deal_id)
            if not deal or not deal.number.startswith("E2E-"):
                raise RuntimeError("Refusing to modify a non-E2E deal")
            client = await session.get(CrmClient, deal.crm_client_id) if deal.crm_client_id is not None else None
            buyer = await session.get(Counterparty, deal.counterparty_id) if deal.counterparty_id is not None else None
            legal_address = (buyer.requisites or {}).get("legal_address") if buyer else None
            if (client is None or buyer is None or not buyer.is_active or buyer.merged_into_id is not None
                    or not isinstance(legal_address, str) or not legal_address.strip()
                    or client.counterparty_id != buyer.id or client.owner_id != deal.owner_id
                    or deal.counterparty != client.name):
                raise RuntimeError("E2E deal must preserve one active MDM-linked CRM client and owner")
            existing_owner = await session.get(DealOwnership, deal.id)
            existing_binding = await session.get(DealClientBinding, deal.id)
            existing_documents = (await session.scalars(select(DealDocument).where(
                DealDocument.deal_id == deal.id,
            ))).all()
            if existing_owner is not None or existing_binding is not None or existing_documents:
                raise RuntimeError("Refusing to replace existing deal ownership, client binding, or documents")

            item = None
            sku = None
            if item_id is not None:
                items = (await session.scalars(select(DealItem).where(
                    DealItem.deal_id == deal.id,
                ).order_by(DealItem.id))).all()
                if len(items) != 1 or items[0].id != item_id:
                    raise RuntimeError("Invoice seed requires exactly the selected existing UI deal item")
                item = items[0]
                sku = await session.get(Sku, item.sku_id)
                if sku is None or not sku.code.strip():
                    raise RuntimeError("Selected UI deal item has no MDM SKU")

            token = uuid4().hex
            org = Organization(name="E2E invoice seller", unp=str(100000000 + int(token[:8], 16) % 400000000))
            session.add(org)
            await session.flush()

            # This is package membership inside the synthetic book, not an app-role promotion.
            session.add(AccessGrant(organization_id=org.id, subject=actor, role="chief"))
            if actor != "kharkovich_d":
                session.add(AccessGrant(organization_id=org.id, subject="kharkovich_d", role="chief"))
            if foreign_book_reader:
                session.add(AccessGrant(organization_id=org.id, subject="e2e_foreign", role="reader"))
            session.add(DealOwnership(
                deal_id=deal.id, organization_id=org.id,
                snapshot=await ownership_snapshot(session, deal.id, DealAccess("all")),
                evidence="Synthetic E2E ownership of the selected CRM deal", actor=actor,
            ))
            await session.flush()
            session.add(DealClientBinding(
                deal_id=deal.id, organization_id=org.id, counterparty_id=buyer.id,
                snapshot=await preview_snapshot(session, org.id, deal, buyer.id),
                evidence="Synthetic E2E binding of the selected CRM client and MDM counterparty", actor=actor,
            ))
            warehouse = None
            if reserve_mode == "stock":
                warehouse = "E2E-W"
                session.add(StockMovement(
                    organization_id=org.id, sku_code=sku.code, warehouse=warehouse,
                    kind="in", qty=Decimal("10"), reason="receipt",
                ))
                session.add(WarehouseDirectory(
                    organization_id=org.id, name=warehouse, title="Synthetic E2E invoice warehouse",
                    wms_enabled=physical_shipment, prohibit_negative_stock=True,
                    is_active=True, created_by=actor,
                ))
            reason = "e2e-" + token[:24]
            session.add(LossReason(code=reason, title="Synthetic E2E loss reason", active=True))
            await session.commit()
            print(json.dumps({
                "organization": org.id, "deal": deal.id, "client": client.id,
                "item": item.id if item else None, "sku": sku.code if sku else None,
                "warehouse": warehouse, "buyer": buyer.id, "buyer_name": buyer.name,
                "buyer_unp": buyer.unp, "loss_reason": reason,
            }))
    finally:
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
