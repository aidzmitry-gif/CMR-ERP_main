"""Prepare physical/catalogue facts in the fixed, isolated browser-test database."""

import asyncio
import json
import os
import re
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.engine import URL

from core.domain.models import Counterparty, Sku, User
from core.services.db import Database
from modules.accounting.models import AccessGrant, Organization
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.client_document_register import DealClientBinding
from modules.sales.models import Deal, DealDocument, DealItem, LossReason
from modules.wms.models import StockMovement, WarehouseDirectory


def _test_database_path():
    """Resolve only the legacy workspace DB or an exact owned Linux test DB."""
    expected = Path(__file__).resolve().parents[1] / "e2e.db"
    owner = os.environ.get("E2E_DOCKER_OWNER")
    value = os.environ.get("E2E_SQLITE_PATH")
    if owner is None and value is None:
        value = str(expected)
    if owner is not None:
        if (sys.platform != "linux" or not re.fullmatch(r"[a-f0-9]{32}", owner)
                or value != f"/e2e-db/{owner}/e2e.db"):
            raise RuntimeError("Exact owner-bound Linux E2E database configuration is required")
        path = Path(value)
    else:
        if not value or Path(value).is_symlink():
            raise RuntimeError("Explicit E2E database path is invalid")
        path = Path(value).resolve()
        if path != expected:
            raise RuntimeError("Only the fixed workspace E2E database is allowed without an owner")
    if (not path.parent.is_dir() or path.parent.is_symlink()
            or path.resolve() != path.absolute() or path.is_symlink()):
        raise RuntimeError("E2E database and parent must have exact non-symlink identities")
    sidecars = [Path(str(path) + suffix) for suffix in ("-wal", "-shm", "-journal")]
    if not path.is_file() or any(item.is_symlink() for item in sidecars):
        raise RuntimeError("E2E seeder requires an existing regular database and non-symlink sidecars")
    return path


async def main():
    path = _test_database_path()
    if (
        os.environ.get("AIOS_E2E_SEED") != "1"
        or os.environ.get("AIOS_SELLER_UNP") != "190000007"
        or not path.is_file()
        or path.is_symlink()
        or path.resolve() != path.absolute()
    ):
        raise RuntimeError("Only the existing fixed synthetic e2e.db may be prepared")
    command = json.load(sys.stdin)
    actor = command["actor"]
    deal_id, org_id, buyer_id = (command[key] for key in ("deal_id", "organization_id", "buyer_id"))
    if not isinstance(actor, str) or not actor or len(actor) > 200:
        raise ValueError("Invalid existing chief actor")
    if any(type(value) is not int or value <= 0 for value in (deal_id, org_id, buyer_id)):
        raise ValueError("Exact positive synthetic identities are required")
    db = Database(
        SimpleNamespace(
            database_url=URL.create("sqlite+aiosqlite", database=str(path)).render_as_string(
                hide_password=False
            )
        )
    )
    db.init_engine()
    try:
        async with db.session_factory() as session:
            org = await session.get(Organization, org_id)
            if not org or org.unp != "190000007" or org.name != "E2E installation seller":
                raise RuntimeError("The configured synthetic organization does not match")
            grant = await session.scalar(
                select(AccessGrant).where(
                    AccessGrant.organization_id == org_id,
                    AccessGrant.subject == actor,
                )
            )
            if not grant or grant.role != "chief":
                raise RuntimeError("The API actor must already be chief of the synthetic book")
            owner = await session.scalar(select(User).where(User.username == "e2e_owner"))
            if (
                not owner
                or owner.employee_id != 2901
                or owner.role != "sales"
                or owner.status != "active"
                or owner.deal_visibility != "own"
            ):
                raise RuntimeError("The existing synthetic own-scope seller does not match")
            reader = await session.scalar(
                select(AccessGrant).where(
                    AccessGrant.organization_id == org_id,
                    AccessGrant.subject == "e2e_owner",
                )
            )
            if reader is not None and reader.role != "reader":
                raise RuntimeError("Refusing to change an existing synthetic seller grant")
            deal = await session.get(Deal, deal_id)
            if (
                not deal
                or not deal.number.startswith(("E2E-DOC-", "OWN-", "OUTCOME-"))
                or deal.owner_id != 2901
                or deal.branch_id is not None
                or deal.counterparty_id != buyer_id
            ):
                raise RuntimeError("The exact untouched synthetic own deal is required")
            buyer = await session.get(Counterparty, buyer_id)
            if (
                not buyer
                or not buyer.name.startswith("E2E invoice buyer ")
                or not buyer.is_active
                or buyer.merged_into_id is not None
                or not buyer.requisites.get("legal_address")
            ):
                raise RuntimeError("The exact API-created synthetic legal buyer is required")
            code = f"E2E-INV-{deal_id}"
            if await session.scalar(select(Sku.id).where(Sku.code == code)) is not None:
                raise RuntimeError("This deal already has physical/catalogue prerequisites")
            for model in (DealItem, DealDocument, DealOwnership, DealClientBinding):
                if (
                    await session.scalar(
                        select(model.deal_id).where(model.deal_id == deal_id).limit(1)
                    )
                    is not None
                ):
                    raise RuntimeError("Refusing to replace existing invoice preparation")
            warehouse = await session.scalar(
                select(WarehouseDirectory).where(
                    WarehouseDirectory.organization_id == org_id,
                    WarehouseDirectory.name == "E2E-W",
                )
            )
            if warehouse is not None and (
                warehouse.title != "Synthetic E2E warehouse"
                or warehouse.created_by != actor
                or warehouse.is_active is not True
                or warehouse.wms_enabled is not False
                or warehouse.prohibit_negative_stock is not True
            ):
                raise RuntimeError("The warehouse identity or guarded document mode differs")
            if reader is None:
                session.add(AccessGrant(organization_id=org_id, subject="e2e_owner", role="reader"))
            if warehouse is None:
                session.add(
                    WarehouseDirectory(
                        organization_id=org_id,
                        name="E2E-W",
                        title="Synthetic E2E warehouse",
                        is_active=True,
                        wms_enabled=False,
                        prohibit_negative_stock=True,
                        created_by=actor,
                    )
                )
            sku = Sku(
                code=code,
                title=f"E2E invoice goods {deal_id}",
                unit="шт",
                attributes={"synthetic_deal_id": deal_id, "synthetic_organization_id": org_id},
            )
            session.add(sku)
            reason = f"e2e-{deal_id}"
            session.add(LossReason(code=reason, title=f"Synthetic E2E loss {deal_id}", active=True))
            session.add(
                StockMovement(
                    organization_id=org_id,
                    sku_code=code,
                    warehouse="E2E-W",
                    kind="in",
                    qty=Decimal("10"),
                    reason="receipt",
                )
            )
            await session.commit()
            print(
                json.dumps(
                    {
                        "organization": org_id,
                        "sku": code,
                        "sku_id": sku.id,
                        "buyer": buyer_id,
                        "loss_reason": reason,
                    }
                )
            )
    finally:
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
