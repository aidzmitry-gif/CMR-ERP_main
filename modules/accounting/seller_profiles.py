"""Confirmed seller requisites; immutable versions, never global seller defaults."""
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import func, select

from core.domain.reference import Currency
from modules.accounting.models import Organization, SellerProfile


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def require_currency(session, currency):
    # Same base-currency rule as accounting posting validation.
    if currency != "BYN" and await session.scalar(select(Currency.code).where(
        Currency.code == currency, Currency.is_active.is_(True),
    )) is None:
        raise HTTPException(409, "Unknown or inactive seller currency")


def result(row):
    if fingerprint(row.snapshot) != row.digest:
        raise HTTPException(409, "Seller profile integrity requires reconciliation")
    return {"organization_id": row.organization_id, "profile_id": row.id,
            "revision": row.revision, "effective_from": row.effective_from.isoformat(),
            "digest": row.digest, "seller": dict(row.snapshot),
            "evidence": row.evidence, "actor": row.actor}


async def create(session, org_id, data, actor):
    # Caller has chief authority and holds the organization lock.
    request_digest = fingerprint(data.model_dump(mode="json"))
    existing = await session.scalar(select(SellerProfile).where(
        SellerProfile.organization_id == org_id, SellerProfile.source_key == data.source_key))
    if existing:
        if existing.request_digest != request_digest:
            raise HTTPException(409, "Seller profile key already has another request")
        return result(existing)
    if not data.confirmed:
        raise HTTPException(422, "Confirm the seller's document requisites")
    await require_currency(session, data.currency)
    latest = await session.scalar(select(func.max(SellerProfile.revision)).where(
        SellerProfile.organization_id == org_id)) or 0
    if data.expected_revision != latest:
        raise HTTPException(409, "Seller profile changed; reload its current revision")
    org = await session.get(Organization, org_id, populate_existing=True)
    if org is None:
        raise HTTPException(404, "Organization not found")
    seller = {key: getattr(data, key) for key in (
        "currency", "address", "account", "bank", "bik", "director", "phone", "email")}
    seller.update(name=org.name, unp=org.unp, logo_data_url="", stamp_data_url=None,
                  signature_data_url=None)
    row = SellerProfile(organization_id=org_id, revision=latest + 1,
        effective_from=data.effective_from, currency=data.currency, source_key=data.source_key,
        request_digest=request_digest, digest=fingerprint(seller), snapshot=seller,
        evidence=data.evidence, actor=actor)
    session.add(row)
    await session.flush()
    return result(row)


async def current(session, org_id, on, currency):
    await require_currency(session, currency)
    row = await session.scalar(select(SellerProfile).where(
        SellerProfile.organization_id == org_id, SellerProfile.effective_from <= on,
        SellerProfile.currency == currency,
    ).order_by(SellerProfile.effective_from.desc(), SellerProfile.revision.desc()).limit(1))
    if row is None:
        raise HTTPException(409, "Confirmed seller requisites are missing for this organization, date and currency")
    return result(row)
