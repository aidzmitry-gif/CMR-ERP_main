"""Seed only the dedicated local e2e.db for the real browser invoice flow."""
import asyncio
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.engine import URL

from core.domain.models import Counterparty, Sku
from core.services.db import Database
from modules.accounting.models import AccessGrant, Organization
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.client_document_register import DealClientBinding, preview_snapshot
from modules.sales.models import Deal, DealItem, LossReason
from modules.wms.models import StockMovement


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
    db = Database(SimpleNamespace(database_url=URL.create(
        "sqlite+aiosqlite", database=str(path)
    ).render_as_string(hide_password=False)))
    db.init_engine()
    try:
        async with db.session_factory() as session:
            deal = await session.get(Deal, deal_id)
            if not deal or not deal.number.startswith("E2E-DOC-"):
                raise RuntimeError("Refusing to modify a non-E2E deal")
            token = uuid4().hex
            org = Organization(name="E2E invoice seller", unp=str(100000000 + int(token[:8], 16) % 400000000))
            buyer = Counterparty(name="E2E invoice buyer", unp=str(500000000 + int(token[8:16], 16) % 400000000), requisites={"address": "Synthetic buyer address"})
            sku = Sku(code="E2E-INV-" + token, title="E2E invoice goods", unit="шт")
            session.add_all([org, buyer, sku])
            await session.flush()
            item = DealItem(deal_id=deal.id, sku_id=sku.id, qty=Decimal("2"))
            session.add_all([item, AccessGrant(organization_id=org.id, subject=actor, role="chief"), DealOwnership(deal_id=deal.id, organization_id=org.id, snapshot={}, evidence="Synthetic E2E ownership", actor=actor)])
            await session.flush()
            session.add(DealClientBinding(deal_id=deal.id, organization_id=org.id, counterparty_id=buyer.id, snapshot=await preview_snapshot(session, org.id, deal, buyer.id), evidence="Synthetic E2E buyer binding", actor=actor))
            session.add(StockMovement(organization_id=org.id, sku_code=sku.code, warehouse="E2E-W", kind="in", qty=Decimal("10"), reason="receipt"))
            reason = "e2e-" + token[:24]
            session.add(LossReason(code=reason, title="Synthetic E2E loss reason", active=True))
            await session.commit()
            print(json.dumps({"organization": org.id, "item": item.id, "sku": sku.code, "buyer": buyer.id, "loss_reason": reason}))
    finally:
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
