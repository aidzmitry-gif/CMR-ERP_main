"""Synthetic organization-bound logo inputs; no remote images or production data."""
import base64
from datetime import date
from io import BytesIO

import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import func, select

from modules.accounting import seller_profiles
from modules.accounting.models import AccessGrant, Organization, SellerProfile
from modules.accounting.schemas import SellerProfileInput
from tests.accounting.test_seller_profiles import payload


def media(fmt="PNG", size=(2, 2), *, animated=False, padded=None):
    output = BytesIO()
    image = Image.new("RGB", size, "white")
    options = {"save_all": True, "append_images": [Image.new("RGB", size, "black")]} if animated else {}
    image.save(output, format=fmt, **options)
    content = output.getvalue()
    if padded is not None:
        assert len(content) <= padded
        content += b"\0" * (padded - len(content))
    mime = "image/png" if fmt == "PNG" else "image/jpeg"
    return "data:" + mime + ";base64," + base64.b64encode(content).decode()


async def test_logo_old_request_digest_replays_without_new_fields(client, db, book):
    endpoint = f"/accounting/organizations/{book[0]}/seller-profiles"
    request = payload()
    response = await client.post(endpoint, json=request)
    assert response.status_code == 201, response.text
    original = response.json()
    row = await db.get(SellerProfile, original["profile_id"])
    old_fields = SellerProfileInput(**request).model_dump(mode="json", exclude={"logo_data_url"})
    assert row.request_digest == seller_profiles.fingerprint(old_fields)
    assert (await client.post(endpoint, json=request)).json() == original
    assert (await client.post(endpoint, json={**request, "logo_data_url": ""})).json() == original
    assert await db.scalar(select(func.count()).select_from(SellerProfile)) == 1


async def test_logo_version_dates_and_changed_key_conflict(client, db, book):
    endpoint = f"/accounting/organizations/{book[0]}/seller-profiles"
    png, jpeg = media(), media("JPEG")
    first = await client.post(endpoint, json=payload(logo_data_url=png))
    assert first.status_code == 201, first.text
    assert first.json()["seller"]["logo_data_url"] == png
    assert (await client.post(endpoint, json=payload(logo_data_url=png))).json() == first.json()
    assert (await client.post(endpoint, json=payload(logo_data_url=jpeg))).status_code == 409
    second = await client.post(endpoint, json=payload(
        source_key="seller-2", expected_revision=1, effective_from="2026-10-01", logo_data_url=jpeg))
    assert second.status_code == 201, second.text
    assert (await client.get(endpoint[:-1] + "?on=2026-09-01&currency=BYN")).json() == first.json()
    assert (await client.get(endpoint[:-1] + "?on=2026-10-01&currency=BYN")).json() == second.json()


async def test_logo_has_no_other_organization_fallback(client, db, book):
    response = await client.post(f"/accounting/organizations/{book[0]}/seller-profiles",
                                 json=payload(logo_data_url=media()))
    assert response.status_code == 201, response.text
    other = Organization(name="Synthetic unrelated logo owner", unp="100000002")
    db.add(other)
    await db.commit()
    other_id = other.id
    with pytest.raises(HTTPException) as denied:
        await seller_profiles.current(db, other_id, date(2026, 9, 1), "BYN")
    assert denied.value.status_code == 409
    response = await client.get(f"/accounting/organizations/{other_id}/seller-profile?on=2026-09-01&currency=BYN")
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("role", ["reader", "accountant"])
async def test_logo_keeps_chief_authority(client, db, book, role):
    grant = await db.scalar(select(AccessGrant).where(
        AccessGrant.organization_id == book[0], AccessGrant.subject == "tester"))
    grant.role = role  # Reduce the existing synthetic authority; no grant is added.
    await db.commit()
    response = await client.post(f"/accounting/organizations/{book[0]}/seller-profiles",
                                 json=payload(logo_data_url=media()))
    assert response.status_code == 403, response.text
    assert await db.scalar(select(func.count()).select_from(SellerProfile)) == 0


@pytest.mark.parametrize("case", [
    "url", "svg", "html", "base64", "mime", "truncated", "encoded_over", "decoded_over",
    "png_side", "png_pixels", "jpeg_side", "animated",
])
async def test_logo_input_rejection(client, db, book, case):
    values = {
        "url": "https://example.invalid/logo.png",
        "svg": "data:image/svg+xml;base64,PHN2Zy8+",
        "html": "data:text/html;base64,PGgxPm5vPC9oMT4=",
        "base64": "data:image/png;base64,not-base64!",
        "mime": media().replace("image/png", "image/jpeg"),
        "truncated": "data:image/png;base64,iVBORw0KGgo=",
        "encoded_over": "data:image/png;base64," + "A" * 43_696,
        "decoded_over": media(padded=32_769),
        "png_side": media(size=(2049, 1)),
        "png_pixels": media(size=(1025, 1025)),
        "jpeg_side": media("JPEG", size=(2049, 1)),
        "animated": media(animated=True),
    }
    response = await client.post(f"/accounting/organizations/{book[0]}/seller-profiles",
                                 json=payload(logo_data_url=values[case]))
    assert response.status_code == 422, response.text
    assert await db.scalar(select(func.count()).select_from(SellerProfile)) == 0


@pytest.mark.parametrize("fmt", ["PNG", "JPEG"])
async def test_logo_byte_edge_accepts(client, db, book, fmt):
    logo = media(fmt, padded=32_768)
    response = await client.post(f"/accounting/organizations/{book[0]}/seller-profiles",
                                 json=payload(logo_data_url=logo))
    assert response.status_code == 201, response.text
    assert response.json()["seller"]["logo_data_url"] == logo


async def test_logo_pixel_edge_accepts(client, db, book):
    response = await client.post(f"/accounting/organizations/{book[0]}/seller-profiles",
                                 json=payload(logo_data_url=media(size=(2048, 512))))
    assert response.status_code == 201, response.text
