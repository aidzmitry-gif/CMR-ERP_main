"""Database guards for private inbound VAT evidence history (real PostgreSQL)."""
# ruff: noqa: F811
import json
import runpy
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from modules.accounting.models import Organization
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_procurement_receipt_drafts import source_options
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401

pytestmark = pytest.mark.integration


async def run_migration(session):
    def run(connection):
        migration = runpy.run_path("migrations/versions/0191_accounting_inbound_vat_evidence.py")
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()

    await (await session.connection()).run_sync(run)


def insert_values(org_id, receipt_id, receipt_version, *, kind="supplier_eschf_xml", supersedes_id=None):
    request_key = str(uuid4())
    extension = ".xml" if kind == "supplier_eschf_xml" else ".pdf"
    content_type = "application/xml" if kind == "supplier_eschf_xml" else "application/pdf"
    metadata = {
        "organization_id": org_id,
        "receipt_id": receipt_id,
        "receipt_version": receipt_version,
        "kind": kind,
        "tax_period": "2026-09",
        "reference": "Synthetic direct guard test source",
        "filename": "source" + extension,
        "content_type": content_type,
        "size_bytes": 5,
        "sha256": "a" * 64,
        "storage_filename": request_key.replace("-", "") + extension,
        "evidence": "Synthetic evidence entered for database guard testing",
        "request_key": request_key,
        "supersedes_id": supersedes_id,
    }
    return {
        **metadata,
        "request_digest": "b" * 64,
        "digest": "c" * 64,
        "snapshot": json.dumps(metadata),
        "actor": "pg-evidence-test",
    }


async def insert_file(session, values):
    return await session.scalar(text("""
        INSERT INTO accounting.inbound_vat_evidence_file
        (organization_id, receipt_id, receipt_version, kind, tax_period, reference, filename,
         content_type, size_bytes, sha256, storage_filename, evidence, request_key, supersedes_id,
         request_digest, digest, snapshot, actor)
        VALUES (:organization_id, :receipt_id, :receipt_version, :kind, :tax_period, :reference,
                :filename, :content_type, :size_bytes, :sha256, :storage_filename, :evidence,
                :request_key, :supersedes_id, :request_digest, :digest, CAST(:snapshot AS jsonb), :actor)
        RETURNING id
    """), values)


async def test_pg_inbound_vat_evidence_guards_org_revision_supersedes_and_immutability(
        issuance_pg, pg_book):
    api, factory = issuance_pg
    api.headers["X-User"] = "tester"
    api.headers["X-User-Roles"] = "director"
    async with factory() as session:
        await run_migration(session)
        await session.execute(text(
            "SELECT setval(pg_get_serial_sequence('accounting.account', 'id'), "
            "(SELECT max(id) FROM accounting.account))"
        ))
        await session.execute(text(
            "SELECT setval(pg_get_serial_sequence('accounting.organization', 'id'), "
            "(SELECT max(id) FROM accounting.organization))"
        ))
        path, options = await source_options(api, session, pg_book)
        await session.commit()

    preview = await api.post(path + "/preview", json=options)
    assert preview.status_code == 200, preview.text
    confirmed = await api.post(path + "/confirm", json={**options, "digest": preview.json()["digest"]})
    assert confirmed.status_code == 201, confirmed.text
    correction_response = await api.post(path + "/correction-drafts", json={
        "key": str(uuid4()), "expected_version": 1,
        "expected_entry_id": confirmed.json()["entry_id"],
    })
    assert correction_response.status_code == 201, correction_response.text
    correction = correction_response.json()
    current_document = correction["revisions"][0]["document"]
    current_document["explanation"] = "Synthetic second correction revision for DB guard tests"
    edited = await api.put(
        f"/procurement/organizations/{pg_book[0]}/receipt-documents/{correction['id']}",
        json={"key": str(uuid4()), "expected_version": 1, "document": current_document},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"] == 2

    async with factory() as session:
        other = Organization(name="Other evidence guard company", unp="198765432")
        session.add(other)
        await session.flush()
        other_id = other.id

        valid = insert_values(pg_book[0], correction["id"], 2)
        first_id = await insert_file(session, valid)
        child = insert_values(pg_book[0], correction["id"], 2, supersedes_id=first_id)
        child_id = await insert_file(session, child)
        await session.commit()

        with pytest.raises(DBAPIError, match="parallel chain"):
            async with session.begin_nested():
                await insert_file(session, insert_values(pg_book[0], correction["id"], 2))

        with pytest.raises(DBAPIError, match="exact current correction draft"):
            async with session.begin_nested():
                await insert_file(session, insert_values(other_id, correction["id"], 2))

        with pytest.raises(DBAPIError, match="exact current correction draft"):
            async with session.begin_nested():
                await insert_file(session, insert_values(pg_book[0], correction["id"], 1))

        with pytest.raises(DBAPIError, match="latest file in the same chain"):
            async with session.begin_nested():
                await insert_file(session, insert_values(
                    pg_book[0], correction["id"], 2,
                    kind="supporting_document_pdf", supersedes_id=first_id,
                ))

        with pytest.raises(DBAPIError, match="latest file in the same chain"):
            async with session.begin_nested():
                await insert_file(session, insert_values(
                    pg_book[0], correction["id"], 2, supersedes_id=first_id,
                ))

        assert await session.scalar(text(
            "SELECT count(*) FROM accounting.inbound_vat_evidence_file WHERE id IN (:first, :child)"
        ), {"first": first_id, "child": child_id}) == 2

        for statement in (
            "UPDATE accounting.inbound_vat_evidence_file SET evidence='changed' WHERE id=:id",
            "DELETE FROM accounting.inbound_vat_evidence_file WHERE id=:id",
            "TRUNCATE accounting.inbound_vat_evidence_file",
        ):
            with pytest.raises(DBAPIError, match="immutable"):
                async with session.begin_nested():
                    await session.execute(text(statement), {"id": first_id})
