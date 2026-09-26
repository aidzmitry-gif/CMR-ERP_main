"""Organization-scoped projections of immutable production order ownership."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy import String, cast, or_, select

from modules.accounting import service
from modules.production.accounting_ownership import ProductionOrderOwnership

MAX_ORDER_ID = 2_147_483_647
MAX_RESULTS = 50
ORDER_DIMENSION_KEYS = frozenset({
    "order", "order_source", "order_id", "order_number", "order_product",
    "order_quantity", "order_created_at", "order_digest", "order_stage_at_ownership",
})


def has_reference(dimensions: dict[str, str]) -> bool:
    return any(key == "order" or key.startswith("order_") for key in dimensions)


def _parse_order_id(raw_id: str | None) -> int:
    if (not isinstance(raw_id, str) or not raw_id.isascii() or not raw_id.isdecimal()
            or raw_id.startswith("0") or len(raw_id) > 10):
        raise service.AccountingError("Select a registered production order from this organization")
    order_id = int(raw_id)
    if order_id > MAX_ORDER_ID:
        raise service.AccountingError("Select a registered production order from this organization")
    return order_id


def dimensions_from_ownership(row: ProductionOrderOwnership) -> dict[str, str]:
    snapshot = row.snapshot
    if not isinstance(snapshot, dict):
        raise service.AccountingError("Production order ownership snapshot is incomplete")
    snapshot_id = snapshot.get("order_id")
    number = snapshot.get("number")
    product = snapshot.get("product")
    quantity = snapshot.get("quantity")
    created_at = snapshot.get("created_at")
    stage = snapshot.get("stage")
    digest = row.digest
    if (type(snapshot_id) is not int or snapshot_id <= 0 or snapshot_id > MAX_ORDER_ID
            or snapshot_id != row.order_id
            or not isinstance(number, str) or not number.strip() or len(number) > 200
            or not isinstance(product, str) or not product.strip() or len(product) > 200
            or type(quantity) is not int or quantity <= 0 or quantity > MAX_ORDER_ID
            or not isinstance(created_at, str) or "T" not in created_at or len(created_at) > 200
            or not isinstance(stage, str) or not stage.strip() or len(stage) > 200
            or not isinstance(digest, str) or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)):
        raise service.AccountingError("Production order ownership snapshot is incomplete")
    try:
        datetime.fromisoformat(created_at)
    except ValueError as exc:
        raise service.AccountingError("Production order ownership snapshot is incomplete") from exc
    actual_digest = hashlib.sha256(json.dumps(
        snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()
    if actual_digest != digest:
        raise service.AccountingError("Production order ownership snapshot digest is invalid")
    return {
        "order": number,
        "order_source": "production",
        "order_id": str(snapshot_id),
        "order_number": number,
        "order_product": product,
        "order_quantity": str(quantity),
        "order_created_at": created_at,
        "order_digest": digest,
        "order_stage_at_ownership": stage,
    }


async def options(session, organization_id: int, term: str) -> list[dict[str, str]]:
    query = select(ProductionOrderOwnership).where(
        ProductionOrderOwnership.organization_id == organization_id,
    )
    search = term.strip()
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.where(or_(
            cast(ProductionOrderOwnership.order_id, String).ilike(pattern, escape="\\"),
            ProductionOrderOwnership.snapshot["number"].as_string().ilike(pattern, escape="\\"),
            ProductionOrderOwnership.snapshot["product"].as_string().ilike(pattern, escape="\\"),
        ))
    rows = (await session.scalars(query.order_by(
        ProductionOrderOwnership.order_id.desc(),
    ).limit(MAX_RESULTS))).all()
    return [dimensions_from_ownership(row) for row in rows]


async def verify_reference(session, organization_id: int, dimensions: dict[str, str]) -> None:
    if not has_reference(dimensions):
        return
    order_id = _parse_order_id(dimensions.get("order_id"))
    row = await session.scalar(select(ProductionOrderOwnership).where(
        ProductionOrderOwnership.order_id == order_id,
        ProductionOrderOwnership.organization_id == organization_id,
    ))
    if row is None or row.organization_id != organization_id:
        raise service.AccountingError("Production order was not found in this organization's ownership registry")
    expected = dimensions_from_ownership(row)
    actual_keys = {key for key in dimensions if key == "order" or key.startswith("order_")}
    if actual_keys != ORDER_DIMENSION_KEYS or any(
        dimensions.get(key) != value for key, value in expected.items()
    ):
        raise service.AccountingError("Production order snapshot changed; select it again")
