"""Receipt protocol against real SQLAlchemy/ASGI/outbox/storage; PostgreSQL opt-in.

Concurrency run: set CRM_INTAKE_TEST_POSTGRES_URL to an isolated loopback PostgreSQL
database named crm_intake_test*. The test creates/drops only its random schema.
Windows SQLite tests do not prove PostgreSQL concurrency or Linux power-loss durability.
"""
from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import io
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.db.base import Base
from core.domain.models import (
    AuditLog,
    Contact,
    Counterparty,
    IntakeIdentity,
    IntakeReceipt,
    OutboxEvent,
)
from core.runtime.core import Core
from core.runtime.deps import get_session
from core.services import intake_storage
from core.services.eventbus import EventContext, OutboxEventBus
from modules.integrations import intake
from modules.integrations.routes import router as integrations_router
from modules.leads import events
from modules.leads import storage as lead_storage
from modules.leads.models import Lead, LeadAttachment
from modules.leads.module import LeadsModule

URL = "/integrations/intake/v1"
HEADERS = {"X-Intake-Token": "test-intake-only", "X-User-Roles": "director"}
TABLES = [model.__table__ for model in (
    Counterparty, Contact, IntakeIdentity, IntakeReceipt, OutboxEvent, AuditLog, Lead, LeadAttachment,
)]


def envelope(namespace="admin@enersys.by", source_id="mail:1", delivery_id="delivery:1", **extra):
    return {
        "namespace": namespace, "source_id": source_id, "delivery_id": delivery_id,
        "lead": {"email": "buyer@example.invalid", "message": "Нужна цена\nОригинальная строка."},
        **extra,
    }


def attachment(data=b"%PDF-1.4 exact test bytes\n%%EOF", file_id="1",
               filename="Запрос.pdf", content_type="application/pdf"):
    return {
        "file_id": file_id, "filename": filename, "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "data_url": f"data:{content_type};base64," + base64.b64encode(data).decode(),
    }


DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def docx_attachment(number):
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>Verified request {number}</w:t></w:r></w:p></w:body>"
        "</w:document>"
    ).encode()
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    ).encode()
    relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    ).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in (
            ("[Content_Types].xml", content_types),
            ("_rels/.rels", relationships),
            ("word/document.xml", document),
        ):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, data)
    data = buffer.getvalue()
    return attachment(
        data,
        file_id=f"docx-{number}", filename=f"request-{number}.docx", content_type=DOCX_CONTENT_TYPE,
    )


def legat_request(tender, lot, delivery_id, *, namespace="zakupki.legat.by", **extra):
    source_id = f"tender:{tender}:lot:{lot}"
    return envelope(
        namespace, source_id, delivery_id,
        lead={
            "company": "Verified Buyer Co",
            "product": f"Verified product {tender}/{lot}",
            "message": "Legat notification with verified buyer company",
        },
        template_id=2344, tender_id=tender, lot_id=lot, **extra,
    )


def direct_legat_request(tender, lot, delivery_id):
    source_id = f"tender:{tender}:lot:{lot}"
    return envelope(
        "admin@enersys.by", source_id, delivery_id,
        identity_namespace="zakupki.legat.by", template_id=2344,
        tender_id=tender, lot_id=lot,
        lead={
            "name": "Verified buyer", "company": "Verified Buyer Co",
            "phone": f"+375290000{int(lot):02d}", "email": f"buyer-{tender}-{lot}@example.invalid",
            "product": f"Verified product {tender}/{lot}",
            "message": "Direct buyer request with verified contacts",
        },
        files=[docx_attachment(1)],
    )


def app_for(session_dependency):
    bus = OutboxEventBus()
    services = SimpleNamespace(
        config=SimpleNamespace(intake_webhook_token="test-intake-only", environment="prod"),
        event_bus=bus,
    )
    core = Core(services)
    LeadsModule().register(core)
    app = FastAPI()
    app.state.core = core
    app.dependency_overrides[get_session] = session_dependency
    app.include_router(integrations_router, prefix="/integrations")
    for registered in core.routers:
        app.include_router(registered.router, prefix=registered.prefix)
    return app, services


@pytest_asyncio.fixture
async def receipt_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:").execution_options(
        schema_translate_map={"leads": None},
    )
    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: Base.metadata.create_all(conn, tables=TABLES))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def receipt_tmp():
    # Same sandbox-friendly convention as tests/conftest.py; no recursive cleanup.
    path = Path(".tmp_pytest/manual") / uuid4().hex
    path.mkdir(parents=True)
    return path


@pytest_asyncio.fixture
async def intake_env(receipt_session, monkeypatch, receipt_tmp):
    session = receipt_session
    monkeypatch.setenv("AIOS_ENVIRONMENT", "dev")
    root = receipt_tmp / "files"
    monkeypatch.setenv("AIOS_LEADS_DATA_DIR", str(root))
    monkeypatch.setattr(lead_storage, "_DATA_DIR", root)

    async def dependency():
        yield session

    app, services = app_for(dependency)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=HEADERS,
    ) as client:
        yield SimpleNamespace(
            api=client, session=session, services=services, app=app, root=root,
            relay=lambda: services.event_bus.relay_once(session, EventContext(session, services)),
        )


async def count(session, model):
    return await session.scalar(select(func.count()).select_from(model))


async def receipt(env, receipt_id):
    response = await env.api.get(f"{URL}/receipts/{receipt_id}")
    assert response.status_code == 200, response.text
    return response.json()


async def test_delivery_survives_new_session_with_exact_files(intake_env):
    env = intake_env
    file = attachment()
    request = envelope(subject="Полная тема", files=[file])
    response = await env.api.post(URL, json=request)
    assert response.status_code == 202, response.text
    initial = response.json()
    assert initial["status"] == "queued" and initial["lead_id"] is None
    assert initial["files"][0]["attachment_id"] is None
    assert await count(env.session, Lead) == 0
    outbox = (await env.session.execute(select(OutboxEvent))).scalars().all()
    assert [event.payload for event in outbox] == [{"receipt_id": initial["receipt_id"]}]
    await env.session.commit()
    env.session.expunge_all()
    factory = async_sessionmaker(env.session.bind, expire_on_commit=False)
    async with factory() as restarted:
        await env.services.event_bus.relay_once(restarted, EventContext(restarted, env.services))
    result = await receipt(env, initial["receipt_id"])
    assert result["status"] == "delivered" and result["lead_id"]
    saved_file = result["files"][0]
    assert saved_file["sha256"] == file["sha256"] and saved_file["attachment_id"]
    assert "storage_path" not in saved_file
    downloaded = await env.api.get(
        f"/leads/{result['lead_id']}/attachments/{saved_file['attachment_id']}/download"
    )
    assert downloaded.status_code == 200
    assert hashlib.sha256(downloaded.content).hexdigest() == file["sha256"]
    lead = await env.session.get(Lead, result["lead_id"])
    assert request["lead"]["message"] in lead.message and "Полная тема" in lead.message
    repeated = await env.api.post(URL, json=request)
    assert repeated.status_code == 200 and repeated.json() == result
    assert await count(env.session, LeadAttachment) == 1


async def test_legacy_doc_and_nested_png_delivery_download_once(intake_env):
    env = intake_env
    doc_data = (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(range(251))) * 200
    doc_data = doc_data[:40960]
    png_data = (b"\x89PNG\r\n\x1a\n" + b"PNG synthetic test bytes") * 200
    png_data = png_data[:3341]
    request = envelope(files=[
        attachment(doc_data, "doc", "legacy.doc", "application/msword"),
        attachment(png_data, "png", "inline.png", "image/png"),
    ])
    response = await env.api.post(URL, json=request)
    assert response.status_code == 202, response.text
    receipt_id = response.json()["receipt_id"]
    await env.relay()
    result = await receipt(env, receipt_id)
    assert result["status"] == "delivered" and result["lead_id"]
    by_name = {item["filename"]: item for item in result["files"]}
    assert {"legacy.doc", "inline.png"} == set(by_name)
    expected = {"legacy.doc": doc_data, "inline.png": png_data}
    for filename, data in expected.items():
        item = by_name[filename]
        download = await env.api.get(
            f"/leads/{result['lead_id']}/attachments/{item['attachment_id']}/download"
        )
        assert download.status_code == 200
        assert download.content == data
        assert hashlib.sha256(download.content).hexdigest() == item["sha256"]
        assert download.headers["content-type"].split(";", 1)[0] == (
            "application/msword" if filename == "legacy.doc" else "image/png"
        )
        if filename == "legacy.doc":
            assert download.headers["content-disposition"].startswith("attachment;")
            assert download.headers["x-content-type-options"] == "nosniff"
    assert await count(env.session, LeadAttachment) == 2
    repeated = await env.api.post(URL, json=request)
    assert repeated.status_code == 200 and repeated.json() == result
    assert await count(env.session, LeadAttachment) == 2

    doc_row = await env.session.scalar(select(LeadAttachment).where(LeadAttachment.filename == "legacy.doc"))
    doc_path = intake_storage.resolve_path(env.root, doc_row.storage_path)
    doc_path.write_bytes(b"corrupted")
    assert (await receipt(env, receipt_id))["status"] == "unavailable"
    doc_path.unlink()
    assert (await receipt(env, receipt_id))["status"] == "unavailable"


async def test_duplicate_queued_and_payload_conflict(intake_env):
    env = intake_env
    first = await env.api.post(URL, json=envelope())
    second = await env.api.post(URL, json=envelope())
    assert first.json()["receipt_id"] == second.json()["receipt_id"]
    assert await count(env.session, IntakeReceipt) == await count(env.session, OutboxEvent) == 1
    changed = envelope(lead={"message": "Changed"})
    conflict = await env.api.post(URL, json=changed)
    assert conflict.status_code == 409
    conflict = await env.api.post(URL, json=envelope(source_id="mail:another"))
    assert conflict.status_code == 409
    assert await count(env.session, IntakeIdentity) == 1  # No phantom identity after rollback.


async def test_identity_is_not_sender_and_site_copy_joins_exact_source(intake_env):
    env = intake_env
    requests = [
        envelope("microchips.by", "form:1:result:42", "site:42"),
        envelope("admin@enersys.by", "form:1:result:42", "mail-copy:42",
                 identity_namespace="microchips.by"),
        envelope(source_id="mail:new-request", delivery_id="mail:new-request"),
        envelope(source_id="mail:new-request", delivery_id="mail:reply",
                 lead={"email": "buyer@example.invalid", "message": "Дополнительный вопрос"}),
    ]
    responses = [await env.api.post(URL, json=request) for request in requests]
    assert all(response.status_code == 202 for response in responses)
    await env.relay()
    results = [await receipt(env, response.json()["receipt_id"]) for response in responses]
    assert all(result["status"] == "delivered" for result in results)
    assert results[0]["lead_id"] == results[1]["lead_id"]
    assert results[2]["lead_id"] == results[3]["lead_id"] != results[0]["lead_id"]
    lead = await env.session.get(Lead, results[3]["lead_id"])
    assert lead.message.count("Дополнительный вопрос") == 1


async def test_tenders_and_lots_separate_across_three_templates(intake_env):
    env = intake_env
    ids = []
    for number, (tender, lot, template) in enumerate([
        ("10", "1", 2344), ("10", "2", 2400), ("11", "1", 2517), ("10", "1", 2517),
    ]):
        response = await env.api.post(URL, json=envelope(
            "zakupki.legat.by", f"tender:{tender}:lot:{lot}", f"mail:{number}:lot:{lot}",
            template_id=template, tender_id=tender, lot_id=lot,
        ))
        assert response.status_code == 202, response.text
        ids.append(response.json()["receipt_id"])
    await env.relay()
    results = [await receipt(env, value) for value in ids]
    assert all(result["status"] == "delivered" for result in results)
    assert len({result["lead_id"] for result in results}) == 3
    assert results[0]["lead_id"] == results[3]["lead_id"]
    assert all(lead.source == "tender" for lead in (await env.session.scalars(select(Lead))).all())


@pytest.mark.parametrize("admin_first", [False, True])
async def test_legat_admin_alias_preserves_history_contacts_and_docx(intake_env, monkeypatch, admin_first):
    env = intake_env
    manual = Counterparty(name="Manual association")
    env.session.add(manual)
    await env.session.flush()
    await env.session.commit()
    pairs = [("365", "1"), ("365", "2"), ("366", "1"), ("366", "2")]
    legat = [legat_request(tender, lot, f"legat:{tender}:{lot}") for tender, lot in pairs]
    direct = [direct_legat_request(tender, lot, f"mail:{tender}:{lot}") for tender, lot in pairs]
    assert len({request["files"][0]["sha256"] for request in direct}) == 1
    first, second = (direct, legat) if admin_first else (legat, direct)

    batch_responses = []
    for batch in (first, second):
        responses = [await env.api.post(URL, json=request) for request in batch]
        assert all(response.status_code == 202 for response in responses)
        batch_responses.append(responses)
        if batch is direct:
            failed_file = batch[0]["files"][0]["filename"]
            original_verify = intake_storage.verify_file
            failed = {"done": False}

            def fail_once(root, item):
                if item["filename"] == failed_file and not failed["done"]:
                    failed["done"] = True
                    raise OSError("synthetic retry")
                return original_verify(root, item)

            monkeypatch.setattr(intake_storage, "verify_file", fail_once)
            await env.relay()
            monkeypatch.setattr(intake_storage, "verify_file", original_verify)
            retry = await env.api.post(URL, json=batch[0])
            assert retry.status_code == 202
            await env.relay()
        else:
            await env.relay()

        if batch is first:
            assert await count(env.session, IntakeReceipt) == 4
            assert await count(env.session, IntakeIdentity) == 4
            assert await count(env.session, Lead) == 4
            for lead in (await env.session.scalars(select(Lead))).all():
                lead.counterparty_id, lead.customer_kind = manual.id, "existing"
            await env.session.commit()

    for request in first + second:
        response = await env.api.post(URL, json=request)
        assert response.status_code == 200
    await env.relay()
    assert await count(env.session, IntakeReceipt) == 8
    assert await count(env.session, IntakeIdentity) == 4
    assert await count(env.session, Lead) == 4
    leads = (await env.session.scalars(select(Lead).order_by(Lead.id))).all()
    expected_by_product = {
        request["lead"]["product"]: (
            base64.b64decode(request["files"][0]["data_url"].split(",", 1)[1]),
            request["files"][0]["sha256"],
        )
        for request in direct
    }
    assert {lead.product for lead in leads} == set(expected_by_product)
    for tender, lot in pairs:
        lead = next(item for item in leads if item.product == f"Verified product {tender}/{lot}")
        assert (lead.name, lead.company, lead.phone, lead.email) == (
            "Verified buyer", "Verified Buyer Co", f"+375290000{int(lot):02d}",
            f"buyer-{tender}-{lot}@example.invalid",
        )
        legat_provenance = f"Источник: zakupki.legat.by; ID: tender:{tender}:lot:{lot}"
        admin_provenance = f"Источник: admin@enersys.by; ID: tender:{tender}:lot:{lot}"
        assert lead.message.count(legat_provenance) == 1
        assert lead.message.count(admin_provenance) == 1
        assert lead.message.count("Legat notification with verified buyer company") == 1
        assert lead.message.count("Direct buyer request with verified contacts") == 1
    attachments = (await env.session.scalars(select(LeadAttachment).order_by(LeadAttachment.id))).all()
    assert len(attachments) == 4
    assert all(item.source == "email" and item.content_type == DOCX_CONTENT_TYPE for item in attachments)
    leads_by_id = {lead.id: lead for lead in leads}
    for item in attachments:
        data = intake_storage.resolve_path(env.root, item.storage_path).read_bytes()
        expected_data, expected_hash = expected_by_product[leads_by_id[item.lead_id].product]
        assert data == expected_data
        assert hashlib.sha256(data).hexdigest() == expected_hash
        assert item.size_bytes == len(data) == len(expected_data)
    assert all(lead.counterparty_id == manual.id and lead.customer_kind == "existing" for lead in leads)
    results = [await receipt(env, response.json()["receipt_id"])
               for responses in batch_responses for response in responses]
    assert len({(item["identity_namespace"], item["source_id"]) for item in results}) == 4
    assert sum(item["namespace"] == "zakupki.legat.by" for item in results) == 4
    assert sum(item["namespace"] == "admin@enersys.by" for item in results) == 4
    expected_hash_by_source = {
        request["source_id"]: request["files"][0]["sha256"] for request in direct
    }
    for item in results:
        if item["namespace"] == "admin@enersys.by":
            assert item["files"][0]["sha256"] == expected_hash_by_source[item["source_id"]]
    assert all(lead.source == "tender" for lead in (await env.session.scalars(select(Lead))).all())


@pytest.mark.parametrize("payload", [
    legat_request("365", "1", "bad-alias", namespace="microchips.by",
                  identity_namespace="zakupki.legat.by"),
    legat_request("365", "1", "bad-alias", namespace="enersys.by",
                  identity_namespace="zakupki.legat.by"),
    envelope(
        "admin@enersys.by", "tender:365:lot:1", "missing-template",
        identity_namespace="zakupki.legat.by", tender_id="365", lot_id="1",
    ),
    envelope(
        "admin@enersys.by", "mail:365:1", "bad-source-id",
        identity_namespace="zakupki.legat.by", template_id=2344, tender_id="365", lot_id="1",
    ),
    envelope(
        "zakupki.legat.by", "tender:365:lot:1", "bad-identity",
        identity_namespace="microchips.by", template_id=2344, tender_id="365", lot_id="1",
    ),
])
async def test_legat_alias_guards_reject_forbidden_or_incomplete_requests(intake_env, payload):
    response = await intake_env.api.post(URL, json=payload)
    assert response.status_code == 422, response.text
    assert await count(intake_env.session, IntakeReceipt) == 0
    assert await count(intake_env.session, IntakeIdentity) == 0


async def test_legat_alias_rejects_tampered_docx_metadata(intake_env):
    request = direct_legat_request("365", "1", "mail:tampered")
    request["files"][0]["sha256"] = "0" * 64
    response = await intake_env.api.post(URL, json=request)
    assert response.status_code == 422, response.text
    assert await count(intake_env.session, IntakeReceipt) == 0
    assert await count(intake_env.session, IntakeIdentity) == 0


async def test_site_contact_wins_when_mail_copy_arrives_first(intake_env):
    env = intake_env
    first = await env.api.post(URL, json=envelope(
        source_id="form:1:result:42", identity_namespace="microchips.by",
        lead={"email": "notification@example.invalid", "message": "Копия"},
    ))
    second = await env.api.post(URL, json=envelope(
        "microchips.by", "form:1:result:42", "direct:42",
        lead={"email": "buyer@example.invalid", "name": "Покупатель", "message": "Форма"},
    ))
    await env.relay()
    first_result = await receipt(env, first.json()["receipt_id"])
    second_result = await receipt(env, second.json()["receipt_id"])
    assert first_result["lead_id"] == second_result["lead_id"]
    lead = await env.session.get(Lead, first_result["lead_id"])
    assert lead.email == "buyer@example.invalid" and lead.name == "Покупатель"


@pytest.mark.parametrize("choice", ["buyer", "no_match", "manual", "manual_clear", "unknown_origin"])
async def test_authoritative_contacts_rebind_only_proven_automatic_customer(intake_env, choice):
    env = intake_env
    notifier, buyer, manual = [Counterparty(name=name) for name in ("Notifier", "Buyer", "Manual")]
    env.session.add_all([notifier, buyer, manual])
    await env.session.flush()
    expected_ids = {"buyer": buyer.id, "manual": manual.id, "unknown_origin": notifier.id}
    env.session.add_all([
        Contact(full_name="Notifier", email="notifier@example.invalid", counterparty_id=notifier.id),
        Contact(full_name="Buyer", email="buyer@example.invalid", counterparty_id=buyer.id),
    ])
    await env.session.commit()
    first = await env.api.post(URL, json=envelope(
        source_id="form:1:result:43", identity_namespace="microchips.by",
        lead={"email": "notifier@example.invalid", "message": "Копия"},
    ))
    await env.relay()
    result = await receipt(env, first.json()["receipt_id"])
    lead = await env.session.get(Lead, result["lead_id"])
    assert lead.counterparty_id == notifier.id and lead.customer_kind == "existing"
    if choice == "manual":
        lead.counterparty_id = manual.id
    elif choice == "manual_clear":
        lead.counterparty_id, lead.customer_kind = None, ""
    elif choice == "unknown_origin":
        emitted = (await env.session.scalars(select(OutboxEvent).where(
            OutboxEvent.event_type == "leads.lead.received",
        ))).one()
        emitted.payload = {k: v for k, v in emitted.payload.items() if k != "customer_binding"}
    await env.session.commit()
    direct = await env.api.post(URL, json=envelope(
        "microchips.by", "form:1:result:43", "direct:43",
        lead={
            "email": "unknown@example.invalid" if choice == "no_match" else "buyer@example.invalid",
            "message": "Прямая заявка",
        },
    ))
    await env.relay()
    assert (await receipt(env, direct.json()["receipt_id"]))["status"] == "delivered"
    await env.session.refresh(lead)
    assert lead.counterparty_id == expected_ids.get(choice)
    assert lead.customer_kind == ("" if choice in {"no_match", "manual_clear"} else "existing")


@pytest.mark.parametrize("failure", ["disk", "processing"])
async def test_failed_receipt_does_not_block_relay_and_retries(intake_env, monkeypatch, failure):
    env = intake_env
    bad_request = envelope(files=[attachment()])
    bad_id = (await env.api.post(URL, json=bad_request)).json()["receipt_id"]
    good_id = (await env.api.post(URL, json=envelope(source_id="good", delivery_id="good"))).json()["receipt_id"]
    original = intake_storage.verify_file
    if failure == "disk":
        def fail(root, item):
            raise OSError("simulated disk unavailable")
        monkeypatch.setattr(intake_storage, "verify_file", fail)
    else:
        from modules.leads import leads
        original_score = leads.apply_initial_score

        async def fail(lead, session):
            if "delivery:1" in lead.message:
                raise RuntimeError("simulated after lead insertion")
            return await original_score(lead, session)
        monkeypatch.setattr(leads, "apply_initial_score", fail)
    await env.relay()
    failed = await receipt(env, bad_id)
    assert failed["status"] == "failed" and failed["lead_id"] is None
    assert (await receipt(env, good_id))["status"] == "delivered"
    assert await count(env.session, Lead) == 1 and await count(env.session, LeadAttachment) == 0
    if failure == "disk":
        monkeypatch.setattr(intake_storage, "verify_file", original)
    else:
        monkeypatch.setattr(leads, "apply_initial_score", original_score)
    retried = await env.api.post(URL, json=bad_request)
    assert retried.status_code == 202 and retried.json()["receipt_id"] == bad_id
    await env.relay()
    assert (await receipt(env, bad_id))["status"] == "delivered"
    assert await count(env.session, Lead) == 2 and await count(env.session, LeadAttachment) == 1


async def test_commit_failure_returns_no_ack_and_retry_is_safe(intake_env, monkeypatch):
    env = intake_env
    original = env.session.commit

    async def fail():
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(env.session, "commit", fail)
    response = await env.api.post(URL, json=envelope(files=[attachment()]))
    assert response.status_code == 503
    assert await count(env.session, IntakeReceipt) == await count(env.session, OutboxEvent) == 0
    monkeypatch.setattr(env.session, "commit", original)
    response = await env.api.post(URL, json=envelope(files=[attachment()]))
    assert response.status_code == 202
    await env.relay()
    assert (await receipt(env, response.json()["receipt_id"]))["status"] == "delivered"


async def test_lost_commit_response_reconciles_same_receipt(intake_env, monkeypatch):
    env = intake_env
    original = env.session.commit

    async def committed_then_lost():
        await original()
        raise RuntimeError("connection lost after commit")

    monkeypatch.setattr(env.session, "commit", committed_then_lost)
    response = await env.api.post(URL, json=envelope())
    assert response.status_code == 503
    monkeypatch.setattr(env.session, "commit", original)
    recovered = await env.api.post(URL, json=envelope())
    assert recovered.status_code == 202 and await count(env.session, IntakeReceipt) == 1
    assert await count(env.session, OutboxEvent) == 1
    await env.relay()
    assert (await receipt(env, recovered.json()["receipt_id"]))["status"] == "delivered"


async def test_relay_commit_failure_rolls_back_lead_and_receipt(intake_env, monkeypatch):
    env = intake_env
    receipt_id = (await env.api.post(URL, json=envelope(files=[attachment()]))).json()["receipt_id"]
    original = env.session.commit

    async def fail():
        raise RuntimeError("relay commit failed")

    monkeypatch.setattr(env.session, "commit", fail)
    with pytest.raises(RuntimeError):
        await env.relay()
    await env.session.rollback()
    monkeypatch.setattr(env.session, "commit", original)
    assert (await receipt(env, receipt_id))["status"] == "queued"
    assert await count(env.session, Lead) == await count(env.session, LeadAttachment) == 0
    await env.relay()
    assert (await receipt(env, receipt_id))["status"] == "delivered"


async def test_corrupted_delivered_file_is_never_confirmed(intake_env):
    env = intake_env
    receipt_id = (await env.api.post(URL, json=envelope(files=[attachment()]))).json()["receipt_id"]
    await env.relay()
    row = await env.session.get(IntakeReceipt, receipt_id)
    intake_storage.resolve_path(env.root, row.files[0]["storage_path"]).write_bytes(b"corrupt")
    result = await receipt(env, receipt_id)
    assert result["status"] == "unavailable" and result["lead_id"] is None
    repeated = await env.api.post(URL, json=envelope(files=[attachment()]))
    assert repeated.json()["status"] == "unavailable"


@pytest.mark.parametrize("missing", ["lead", "attachment", "ownership", "metadata", "subscriber"])
async def test_delivery_check_requires_existing_owned_rows_and_registered_subscriber(intake_env, missing):
    env = intake_env
    request = envelope(files=[] if missing == "lead" else [attachment()])
    receipt_id = (await env.api.post(URL, json=request)).json()["receipt_id"]
    await env.relay()
    before = await receipt(env, receipt_id)
    assert before["status"] == "delivered"
    assert any(event.event_type == "intake.receipt.check" for event in env.app.state.core.events)
    if missing == "lead":
        await env.session.delete(await env.session.get(Lead, before["lead_id"]))
    elif missing == "subscriber":
        env.app.state.core.event_bus = OutboxEventBus()
    else:
        row = await env.session.get(LeadAttachment, before["files"][0]["attachment_id"])
        if missing == "attachment":
            await env.session.delete(row)  # Leave the physical file intact.
        elif missing == "ownership":
            other = Lead(source="site", message="Other lead")
            env.session.add(other)
            await env.session.flush()
            row.lead_id = other.id
        else:
            row.filename = "Different.pdf"
    await env.session.commit()
    counts = {model: await count(env.session, model) for model in (Lead, LeadAttachment, OutboxEvent)}
    checked = await receipt(env, receipt_id)
    assert checked["status"] == "unavailable" and checked["lead_id"] is None
    retried = await env.api.post(URL, json=request)
    assert retried.status_code == 200 and retried.json()["status"] == "unavailable"
    assert {model: await count(env.session, model) for model in counts} == counts


async def test_auth_precedes_body_and_receipt_read(intake_env, monkeypatch):
    env = intake_env

    async def unread_body():
        raise AssertionError("Unauthorized body was read")
        yield b""  # pragma: no cover

    response = await env.api.post(URL, content=unread_body(), headers={"X-Intake-Token": "bad"})
    assert response.status_code == 403
    assert (await env.api.get(f"{URL}/receipts/unknown", headers={"X-Intake-Token": "bad"})).status_code == 403
    monkeypatch.setattr(env.app.state.core.config, "intake_webhook_token", "")
    assert (await env.api.post(URL, json=envelope())).status_code == 403


@pytest.mark.parametrize("change", [
    {"namespace": "omts.by"}, {"identity_namespace": "zakupki.legat.by"},
    {"source_id": ""}, {"delivery_id": "contains space"}, {"unexpected": "ignored?"},
    {"lead": {"message": "x", "product": "x" * 129}}, {"lead": {"message": "\x00"}},
    {"lead": {"message": "я" * (128 * 1024 + 1)}}, {"template_id": 5198},
    {"namespace": "zakupki.legat.by"}, {"files": [attachment()] * 2},
    {"files": [{**attachment(), "sha256": "0" * 64}]},
    {"files": [{**attachment(), "size_bytes": 1}]},
    {"files": [{**attachment(), "filename": "../escape.pdf"}]},
    {"files": [{**attachment(), "data_url": "data:text/html;base64,PGgxPjwv aDE+"}]},
    {"files": [attachment(file_id=str(i)) for i in range(9)]},
])
async def test_invalid_input_is_rejected_without_state(intake_env, change):
    env = intake_env
    response = await env.api.post(URL, json={**envelope(), **change})
    assert response.status_code == 422, response.text
    assert await count(env.session, IntakeReceipt) == await count(env.session, OutboxEvent) == 0
    assert not env.root.exists()


@pytest.mark.parametrize("raw", [b"{", b"[]", b'{"namespace":1,"namespace":2}', b'{"lead":NaN}'])
async def test_malformed_json(intake_env, raw):
    response = await intake_env.api.post(URL, content=raw, headers={"Content-Type": "application/json"})
    assert response.status_code in {400, 422}


async def test_chunk_limit_and_aggregate_file_limit(intake_env, monkeypatch):
    env = intake_env
    monkeypatch.setattr(intake, "MAX_BODY_BYTES", 30)

    async def chunks():
        yield b"{" + b" " * 15
        yield b" " * 15 + b"}"

    response = await env.api.post(URL, content=chunks(), headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    response = await env.api.post(URL, content=b"{}", headers={
        "Content-Type": "application/json", "Content-Length": "31",
    })
    assert response.status_code == 413
    monkeypatch.setattr(intake, "MAX_BODY_BYTES", 32000)
    monkeypatch.setattr(intake, "MAX_TOTAL_FILE_BYTES", 1)
    assert (await env.api.post(URL, json=envelope(files=[attachment()]))).status_code == 422
    assert await count(env.session, IntakeReceipt) == 0


async def test_stage_fsync_failure_has_no_receipt(intake_env, monkeypatch):
    def fail(*args):
        raise OSError("fsync failed")

    monkeypatch.setattr(intake_storage.os, "fsync", fail)
    response = await intake_env.api.post(URL, json=envelope(files=[attachment()]))
    assert response.status_code == 503
    assert await count(intake_env.session, IntakeReceipt) == 0


@pytest.mark.integration
async def test_postgres_concurrent_delivery_and_rollback(monkeypatch, receipt_tmp):
    raw_url = os.environ.get("CRM_INTAKE_TEST_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set an isolated loopback CRM_INTAKE_TEST_POSTGRES_URL for real concurrency")
    url = make_url(raw_url)
    assert url.get_backend_name() == "postgresql"
    assert url.host in {"127.0.0.1", "localhost", "::1"}
    assert (url.database or "").startswith("crm_intake_test")
    schema = "intake_test_" + uuid4().hex
    monkeypatch.setenv("AIOS_LEADS_DATA_DIR", str(receipt_tmp / "pg_files"))
    engine = create_async_engine(url)
    schemas = {table.schema for table in Base.metadata.tables.values()}
    engine = engine.execution_options(schema_translate_map={name: schema for name in schemas})
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.run_sync(lambda conn: Base.metadata.create_all(conn, tables=TABLES))
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def dependency():
            async with factory() as session:
                yield session

        app, services = app_for(dependency)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers=HEADERS,
        ) as client:
            request = envelope(files=[attachment()])
            responses = await asyncio.gather(*(client.post(URL, json=copy.deepcopy(request)) for _ in range(8)))
            assert all(response.status_code == 202 for response in responses)
            ids = {response.json()["receipt_id"] for response in responses}
            assert len(ids) == 1
            async with factory() as session:
                assert await count(session, IntakeReceipt) == await count(session, OutboxEvent) == 1
                await events.on_intake_lead({"receipt_id": next(iter(ids))}, EventContext(session, services))
                await session.rollback()  # Real PG savepoint release must not commit the delivery.
            async with factory() as session:
                assert await count(session, Lead) == 0

            async def duplicate_delivery():
                async with factory() as session:
                    await events.on_intake_lead(
                        {"receipt_id": next(iter(ids))}, EventContext(session, services),
                    )
                    await session.commit()

            # Bypass the outbox's own lock to exercise the receipt identity lock
            # against two truly concurrent subscriber deliveries on PostgreSQL.
            await asyncio.gather(duplicate_delivery(), duplicate_delivery())

            async def relay():
                async with factory() as session:
                    return await services.event_bus.relay_once(session, EventContext(session, services))

            await asyncio.gather(relay(), relay())
            async with factory() as session:
                assert await count(session, Lead) == await count(session, LeadAttachment) == 1
            result = (await client.get(f"{URL}/receipts/{next(iter(ids))}")).json()
            assert result["status"] == "delivered"

            # An ordinary editor locks only Lead, not IntakeIdentity. Force its
            # commit between the consumer's attempted read and binding decision.
            async with factory() as session:
                notifier, buyer, manual = [Counterparty(name=n) for n in ("Notifier", "Buyer", "Manual")]
                session.add_all([notifier, buyer, manual])
                await session.flush()
                session.add_all([
                    Contact(full_name="Notifier", email="notifier@example.invalid", counterparty_id=notifier.id),
                    Contact(full_name="Buyer", email="buyer@example.invalid", counterparty_id=buyer.id),
                ])
                await session.commit()
                manual_id = manual.id
            source_key = "mottor:1191119:manual-race"
            first = envelope(
                identity_namespace="enersys.by", source_id=source_key, delivery_id="mail:race",
                lead={"email": "notifier@example.invalid", "message": "copy"},
            )
            first_receipt = (await client.post(URL, json=first)).json()["receipt_id"]
            await relay()
            lead_id = (await client.get(f"{URL}/receipts/{first_receipt}")).json()["lead_id"]
            direct = envelope("enersys.by", source_key, "direct:race")
            direct_receipt = (await client.post(URL, json=direct)).json()["receipt_id"]
            reached_binding, release_binding = asyncio.Event(), asyncio.Event()
            original_manages = events._intake_manages_customer

            async def pause_binding(session, lead):
                reached_binding.set()
                await release_binding.wait()
                return await original_manages(session, lead)

            monkeypatch.setattr(events, "_intake_manages_customer", pause_binding)

            async def deliver_direct():
                async with factory() as session:
                    await events.on_intake_lead({"receipt_id": direct_receipt}, EventContext(session, services))
                    await session.commit()

            async with factory() as editor:
                edited = await editor.get(Lead, lead_id, with_for_update=True)
                edited.counterparty_id = manual_id
                await editor.flush()
                delivery_task = asyncio.create_task(deliver_direct())
                try:
                    async with factory() as observer:
                        for _ in range(150):
                            locks = await observer.scalar(text(
                                "SELECT count(*) FROM pg_stat_activity "
                                "WHERE datname=current_database() AND wait_event_type='Lock'"
                            ))
                            if locks or reached_binding.is_set():
                                break
                            await asyncio.sleep(0.01)
                        else:
                            pytest.fail("No deterministic reader/editor interleaving observed")
                    await editor.commit()
                    release_binding.set()
                    await asyncio.wait_for(delivery_task, 5)
                finally:
                    release_binding.set()
                    if not delivery_task.done():
                        delivery_task.cancel()
                        await asyncio.gather(delivery_task, return_exceptions=True)
            async with factory() as session:
                final_lead = await session.get(Lead, lead_id)
                assert final_lead.email == "buyer@example.invalid"
                assert final_lead.counterparty_id == manual_id

            # Two independent source adapters may deliver the same four
            # tender identities concurrently. PostgreSQL identity locks must
            # serialize each pair without duplicate leads or attachments.
            before = {}
            async with factory() as session:
                for model in (IntakeReceipt, IntakeIdentity, Lead, LeadAttachment):
                    before[model] = await count(session, model)
            pairs = [("pg365", "1"), ("pg365", "2"), ("pg366", "1"), ("pg366", "2")]
            legat_batch = [
                legat_request(tender, lot, f"pg-legat:{tender}:{lot}")
                for tender, lot in pairs
            ]
            admin_batch = [
                direct_legat_request(tender, lot, f"pg-admin:{tender}:{lot}")
                for tender, lot in pairs
            ]
            batch_responses = await asyncio.gather(*(
                client.post(URL, json=copy.deepcopy(request))
                for request in legat_batch + admin_batch
            ))
            assert all(response.status_code == 202 for response in batch_responses)
            receipt_ids = [response.json()["receipt_id"] for response in batch_responses]
            assert len(set(receipt_ids)) == 8

            async def deliver_receipt(receipt_id):
                async with factory() as session:
                    await events.on_intake_lead(
                        {"receipt_id": receipt_id}, EventContext(session, services),
                    )
                    await session.commit()

            await asyncio.gather(*(deliver_receipt(receipt_id) for receipt_id in receipt_ids))
            # The direct deliveries leave their intake outbox notifications queued;
            # ordinary relay must consume those delivered-receipt noops safely.
            await asyncio.gather(relay(), relay())
            async with factory() as session:
                assert await count(session, IntakeReceipt) == before[IntakeReceipt] + 8
                assert await count(session, IntakeIdentity) == before[IntakeIdentity] + 4
                assert await count(session, Lead) == before[Lead] + 4
                products = {request["lead"]["product"] for request in admin_batch}
                new_leads = (await session.scalars(select(Lead).where(Lead.product.in_(products)))).all()
                assert len(new_leads) == 4
                attachments = (await session.scalars(
                    select(LeadAttachment).where(
                        LeadAttachment.lead_id.in_([lead.id for lead in new_leads]),
                    ).order_by(LeadAttachment.id)
                )).all()
                assert await count(session, LeadAttachment) == before[LeadAttachment] + 4
                assert len(attachments) == 4
                assert all(item.source == "email" for item in attachments)
            statuses = await asyncio.gather(*(client.get(f"{URL}/receipts/{receipt_id}")
                                              for receipt_id in receipt_ids))
            assert all(response.json()["status"] == "delivered" for response in statuses)
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
