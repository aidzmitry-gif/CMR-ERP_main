from datetime import date
from pathlib import Path

from sqlalchemy import select

from core.services.auth import CurrentUser, get_current_user
from modules.accounting import service
from modules.accounting.catalog import catalogue
from modules.accounting.models import AccessGrant, Account, CatalogAdoption, Line, Organization
from modules.accounting.schemas import CatalogAdoptionInput


def adoption_payload(**changes):
    value = {
        "request_key": "00000000-0000-0000-0000-000000000581",
        "effective_from": "2026-10-01",
        "evidence": "Synthetic chief accountant catalogue adoption evidence",
    }
    value.update(changes)
    return value


def account_payload(code, valid_from, **changes):
    value = {
        "code": code,
        "title": f"Synthetic account {code}",
        "category": "asset",
        "valid_from": valid_from,
        "normative_ref": "synthetic working-plan reference",
    }
    value.update(changes)
    return value


async def test_catalog_adoption_is_server_snapshotted_idempotent_and_links_only_new_versions(
        client, db, book, posting):
    prefix = f"/accounting/organizations/{book[0]}"
    entry = await service.post(db, book[0], posting(), "tester")
    await db.commit()
    legacy = await db.scalar(select(Account).where(
        Account.organization_id == book[0], Account.code == "41", Account.valid_from == date(2026, 1, 1),
    ))
    historic_line = await db.scalar(select(Line).where(Line.entry_id == entry.id))
    assert legacy.catalog_adoption_id is None

    forged = await client.post(prefix + "/catalog-adoptions", json=adoption_payload(
        catalog_version="forged-by-client",
    ))
    assert forged.status_code == 422

    created = await client.post(prefix + "/catalog-adoptions", json=adoption_payload())
    assert created.status_code == 201, created.text
    created = created.json()
    catalog = catalogue()
    assert created["catalog_version"] == catalog["version"]
    assert created["catalog_source"] == catalog["source"]
    assert created["catalog_review_state"] == catalog["normative_review"]
    assert created["current_normative_verified"] is catalog["current_normative_verified"]
    assert (await client.post(prefix + "/catalog-adoptions", json=adoption_payload())).json() == created
    collision = await client.post(prefix + "/catalog-adoptions", json=adoption_payload(
        evidence="Synthetic but materially different catalogue adoption evidence",
    ))
    assert collision.status_code == 409

    pre_adoption = await client.post(prefix + "/accounts", json=account_payload("42", "2026-09-15"))
    assert pre_adoption.status_code == 422  # Posted history makes retroactive configuration invalid.
    linked = await client.post(prefix + "/accounts", json=account_payload("42", "2026-10-01"))
    assert linked.status_code == 201, linked.text
    assert linked.json()["catalog_adoption_id"] == created["catalog_adoption_id"]
    assert legacy.catalog_adoption_id is None
    assert historic_line.account_id == legacy.id
    assert historic_line.account_code == "41"

    await service.post(db, book[0], posting("catalog-adoption-replay", posting_date="2026-11-01"), "tester")
    await db.commit()
    replay_after_history = await client.post(prefix + "/catalog-adoptions", json=adoption_payload())
    assert replay_after_history.status_code == 201, replay_after_history.text
    assert replay_after_history.json() == created
    historical_new = await client.post(prefix + "/catalog-adoptions", json=adoption_payload(
        request_key="00000000-0000-0000-0000-000000000584", effective_from="2026-11-01",
    ))
    assert historical_new.status_code == 422

    persisted = await db.get(CatalogAdoption, created["catalog_adoption_id"])
    assert persisted.request_digest == service.digest(CatalogAdoptionInput.model_validate(adoption_payload()))
    assert persisted.snapshot["catalog_version"] == catalog["version"]
    assert persisted.snapshot["catalog_source"] == catalog["source"]


async def test_catalog_adoption_reader_readonly_and_cross_organization_isolation(client, db, book):
    prefix = f"/accounting/organizations/{book[0]}"
    assert (await client.post(prefix + "/catalog-adoptions", json=adoption_payload())).status_code == 201
    other = Organization(name="Synthetic isolated catalogue organization", unp="888888888")
    db.add(other)
    db.add(AccessGrant(organization_id=book[0], subject="catalog-reader", role="reader"))
    await db.commit()

    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("catalog-reader", ["director"])
    assert (await client.get(prefix + "/catalog-adoptions")).status_code == 200
    assert (await client.post(prefix + "/catalog-adoptions", json=adoption_payload(
        request_key="00000000-0000-0000-0000-000000000582",
    ))).status_code == 403
    assert (await client.get(f"/accounting/organizations/{other.id}/catalog-adoptions")).status_code == 403
    assert (await client.post(f"/accounting/organizations/{other.id}/catalog-adoptions", json=adoption_payload(
        request_key="00000000-0000-0000-0000-000000000583",
    ))).status_code == 403


def test_catalog_adoption_migration_enforces_org_scoped_link_and_immutability():
    migration = Path("migrations/versions/0158_catalog_adoption.py").read_text(encoding="utf-8")
    assert 'down_revision = "0157"' in migration
    assert "uq_catalog_adoption_organization_id" in migration
    assert "FOREIGN KEY (organization_id, catalog_adoption_id)" in migration
    assert "REFERENCES accounting.catalog_adoption(organization_id, id)" in migration
    assert "BEFORE UPDATE OR DELETE OR TRUNCATE" in migration
    assert "guard_account_catalog_adoption" in migration
