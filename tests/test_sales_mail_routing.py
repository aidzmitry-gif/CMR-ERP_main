"""Synthetic incoming transport, permissions and frozen replies; never send mail."""

import base64
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect, select
from sqlalchemy.orm import undefer
from starlette.requests import Request

from core.domain.models import AuditLog, User
from modules.sales import mail_inbound, mail_queue, mail_routes, mail_routing
from modules.sales.mail_inbound import InboundPayload, accept_message
from modules.sales.mail_models import IncomingEmail, OutgoingEmail
from modules.sales.mail_queue import digest, now
from modules.sales.models import Deal
from ops.sales_mail.relay import receipt_id
from tests.test_sales_email_queue import prepared

ENDPOINT = "/integrations/sales-mail/v1"
DIRECTOR = {"X-User": "director", "X-User-Roles": "director"}


def raw_message(*, sender="control@example.test", references=(), message_id="<incoming@example.test>",
                attachments=(), html=False, reply_to=None):
    msg = EmailMessage(policy=policy.SMTP)
    msg["From"] = sender
    msg["To"] = "order@microchips.by"
    msg["Subject"] = "Synthetic reply"
    if message_id:
        msg["Message-ID"] = message_id
    if references:
        msg["References"] = " ".join(references)
        msg["In-Reply-To"] = references[-1]
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content("Synthetic plain text only")
    if html:
        msg.add_alternative('<script>alert(1)</script><img src="https://invalid.test/track">', subtype="html")
    for filename, content, content_type in attachments:
        maintype, subtype = content_type.split("/")
        msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)
    return msg.as_bytes()


def payload_for(raw, *, uid=1, uidvalidity=7):
    return {
        "mailbox": "order@microchips.by", "uidvalidity": uidvalidity, "uid": uid,
        "raw_sha256": digest(raw), "raw_base64": base64.b64encode(raw).decode("ascii"),
    }


@pytest.fixture(autouse=True)
def no_smtp(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("G04 must not submit SMTP")
    monkeypatch.setattr(mail_queue, "submit", forbidden)


@pytest.fixture
def token_headers(tmp_path, monkeypatch):
    token = "synthetic-inbound-token-only"
    path = tmp_path / "sales-mail-token"
    path.write_text(token, encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setenv("AIOS_SALES_MAIL_INBOUND_TOKEN_FILE", str(path))
    return {"X-Sales-Mail-Token": token, "X-User-Roles": "guest"}


async def ingest(api, token_headers, raw=None, **identity):
    return await api.post(ENDPOINT, json=payload_for(raw or raw_message(), **identity), headers=token_headers)


async def accepted_outgoing(session, **kwargs):
    email = await prepared(session, **kwargs)
    email.status = "accepted"
    email.accepted_at = now()
    await session.commit()
    return email


async def test_machine_auth_is_independent_and_required(api, session, token_headers, monkeypatch):
    body = payload_for(raw_message())
    for headers in ({}, {"X-Sales-Mail-Token": "wrong"}, {"X-User-Roles": "admin"}):
        assert (await api.post(ENDPOINT, json=body, headers=headers)).status_code == 401
    response = await api.post(ENDPOINT, json=body, headers=token_headers)
    assert response.status_code == 201
    assert response.json() == {"receipt_id": receipt_id(body["mailbox"], 7, 1), "raw_sha256": body["raw_sha256"]}
    assert len((await session.scalars(select(IncomingEmail))).all()) == 1
    monkeypatch.delenv("AIOS_SALES_MAIL_INBOUND_TOKEN_FILE")
    assert (await api.post(ENDPOINT, json=body, headers=token_headers)).status_code == 503


async def test_machine_oidc_without_user_token_reaches_dedicated_auth(api, token_headers, monkeypatch):
    from config.settings import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    assert (await ingest(api, token_headers)).status_code == 201


@pytest.mark.parametrize("content", ["", "a\nb", "x" * 4097])
async def test_invalid_token_files_fail_closed(api, token_headers, monkeypatch, tmp_path, content):
    path = tmp_path / "bad-token"
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setenv("AIOS_SALES_MAIL_INBOUND_TOKEN_FILE", str(path))
    assert (await ingest(api, token_headers)).status_code == 503


@pytest.mark.parametrize("change", [
    {"mailbox": "admin@enersys.by"}, {"uid": 0}, {"uid": -1}, {"uid": True},
    {"uid": "1"}, {"uid": 4294967296}, {"uidvalidity": 0}, {"uidvalidity": 1.5},
    {"raw_sha256": "0" * 64}, {"raw_sha256": "A" * 64}, {"raw_base64": "!"},
    {"raw_base64": "Zh=="}, {"raw_base64": "Zm9v\n"}, {"extra": "forbidden"},
])
async def test_invalid_payload_never_creates_receipt(api, session, token_headers, change):
    body = {**payload_for(raw_message()), **change}
    result = await api.post(ENDPOINT, json=body, headers=token_headers)
    assert result.status_code == 422, result.text
    assert "raw_base64" not in result.text
    assert await session.scalar(select(IncomingEmail)) is None


async def test_malformed_json_and_encoding_are_rejected(api, token_headers):
    for data in (b"{", b"[]", b"null", b'"scalar"', b"\xff", b'{"uid":1,"uid":2}'):
        response = await api.post(ENDPOINT, content=data, headers={**token_headers, "Content-Type": "application/json"})
        assert response.status_code == 422
    assert (await api.post(ENDPOINT, content=b"{}", headers=token_headers)).status_code == 415
    assert (await api.post(ENDPOINT, json={}, headers={**token_headers, "Content-Encoding": "gzip"})).status_code == 415


@pytest.mark.parametrize("declared", [True, False])
async def test_body_limit_precedes_json_allocation(monkeypatch, declared):
    monkeypatch.setattr(mail_inbound, "MAX_REQUEST_BYTES", 20)
    def forbidden(*args, **kwargs):
        raise AssertionError("oversized body reached JSON parser")
    monkeypatch.setattr(mail_inbound.json, "loads", forbidden)
    chunks = iter([b"x" * 11, b"y" * 11])
    async def receive():
        chunk = next(chunks)
        return {"type": "http.request", "body": chunk, "more_body": True}
    headers = [(b"content-type", b"application/json")]
    if declared:
        headers.append((b"content-length", b"21"))
    request = Request({"type": "http", "headers": headers}, receive=receive)
    with pytest.raises(HTTPException) as caught:
        await mail_inbound.read_payload(request)
    assert caught.value.status_code == 413


async def test_raw_limit_checked_after_decode(api, token_headers, monkeypatch):
    monkeypatch.setattr(mail_inbound, "MAX_BYTES", 10)
    assert (await ingest(api, token_headers)).status_code == 413


async def test_duplicate_receipt_is_immutable_and_hash_conflict_409(api, session, token_headers):
    raw = raw_message()
    first = await ingest(api, token_headers, raw)
    second = await ingest(api, token_headers, raw)
    conflict = await ingest(api, token_headers, raw_message(sender="other@example.test"))
    assert [first.status_code, second.status_code, conflict.status_code] == [201, 200, 409]
    assert first.json() == second.json()
    row = await session.scalar(select(IncomingEmail).options(undefer(IncomingEmail.raw)))
    assert row.raw == raw and row.raw_sha256 == digest(raw)
    audits = (await session.scalars(select(AuditLog).where(AuditLog.action == "sales.email.incoming_received"))).all()
    assert len(audits) == 1


async def test_unique_collision_savepoint_returns_winner(session, monkeypatch):
    raw = raw_message()
    payload = InboundPayload.model_validate(payload_for(raw))
    winner, _ = await accept_message(session, payload, raw)
    await session.commit()
    winner_id = winner.id
    session.expunge_all()
    original_scalar = session.scalar
    calls = 0
    async def racing_scalar(*args, **kwargs):
        nonlocal calls
        calls += 1
        return None if calls == 1 else await original_scalar(*args, **kwargs)
    monkeypatch.setattr(session, "scalar", racing_scalar)
    # The existing database unique constraint rejects the losing insert.
    recovered, created = await accept_message(session, payload, raw)
    assert not created and recovered.id == winner_id
    assert await session.scalar(select(IncomingEmail.id)) == winner_id


@pytest.mark.parametrize("case,reason", [
    ("unknown", "unknown_chain"), ("forged", "sender_mismatch"),
    ("conflicting", "conflicting_references"), ("multiple_from", "ambiguous_sender"),
    ("duplicate_from", "ambiguous_sender"), ("invalid_reference", "invalid_references"),
    ("prepared", "unconfirmed_chain"), ("malformed", "malformed_mime"),
])
async def test_untrusted_chain_goes_only_to_inbox(api, session, token_headers, case, reason):
    outgoing = await accepted_outgoing(session)
    refs = [outgoing.message_id]
    sender = "control@example.test"
    if case == "unknown":
        refs = ["<unknown@example.test>"]
    if case == "forged":
        sender = "forged@example.test"
    if case == "conflicting":
        other = await accepted_outgoing(session, key="other-request", number="OTHER")
        refs.append(other.message_id)
    if case == "multiple_from":
        sender = "control@example.test, attacker@example.test"
    if case == "prepared":
        outgoing.accepted_at = None
        outgoing.status = "prepared"
        await session.commit()
    raw = raw_message(sender=sender, references=refs)
    if case == "duplicate_from":
        raw = b"From: attacker@example.test\r\n" + raw
    if case == "invalid_reference":
        raw = raw.replace(b"References: ", b"References: garbage ")
    if case == "malformed":
        raw = b"not a MIME header block"
    result = await ingest(api, token_headers, raw)
    assert result.status_code == 201
    row = await session.get(IncomingEmail, result.json()["receipt_id"])
    assert row.deal_id is None and row.routing_reason == reason
    assert (await api.get(f"/sales/deals/{outgoing.deal_id}/incoming-emails")).json()["items"] == []


async def test_matching_chain_respects_two_managers_on_every_view(api, session, token_headers):
    outgoing = await accepted_outgoing(session)
    deal = await session.get(Deal, outgoing.deal_id)
    deal.owner_id, deal.owner = 101, "Alice"
    for name, employee_id in (("alice", 101), ("bob", 202)):
        session.add(User(username=name, full_name=name, role="sales", status="active", department="Продажи",
                         employee_id=employee_id, deal_visibility="own"))
    await session.commit()
    raw = raw_message(sender="Control <CONTROL@example.test>", references=[outgoing.message_id],
                      attachments=[("safe.txt", b"safe content", "text/plain")], html=True)
    received = await ingest(api, token_headers, raw)
    rid = received.json()["receipt_id"]
    prefix = f"/sales/deals/{deal.id}/incoming-emails"
    for user, expected in (("alice", 200), ("bob", 404)):
        headers = {"X-User": user, "X-User-Roles": "sales"}
        for path in (prefix, f"{prefix}/{rid}", f"{prefix}/{rid}/attachments/0"):
            assert (await api.get(path, headers=headers)).status_code == expected
        assert (await api.get("/sales/mail/inbox", headers=headers)).status_code == 403
    detail = (await api.get(f"{prefix}/{rid}")).json()
    assert detail["owner_id"] == 101 and detail["routing_status"] == "matched"
    assert "<script>" not in detail["body_text"] and "raw" not in detail
    assert (await api.get(f"/sales/mail/inbox/{rid}")).status_code == 404
    download = await api.get(f"{prefix}/{rid}/attachments/0")
    assert download.content == b"safe content"
    assert download.headers["content-disposition"].startswith("attachment;")
    assert download.headers["x-content-type-options"] == "nosniff"


async def test_inbox_assignment_is_head_only_scoped_and_audited(api, session, token_headers):
    outgoing = await accepted_outgoing(session)
    received = await ingest(api, token_headers)
    rid = received.json()["receipt_id"]
    endpoint = f"/sales/mail/inbox/{rid}/assign"
    manager = {"X-User-Roles": "sales", "X-User": "manager"}
    assert (await api.post(endpoint, json={"deal_id": outgoing.deal_id}, headers=manager)).status_code == 403
    session.add(User(username="head", full_name="Head", role="sales_head", status="active",
                     employee_id=301, deal_visibility="own"))
    await session.commit()
    head = {"X-User-Roles": "sales_head", "X-User": "head"}
    assert (await api.get("/sales/mail/inbox", headers=head)).status_code == 200
    assert (await api.post(endpoint, json={"deal_id": outgoing.deal_id}, headers=head)).status_code == 404
    first = await api.post(endpoint, json={"deal_id": outgoing.deal_id}, headers=DIRECTOR)
    again = await api.post(endpoint, json={"deal_id": outgoing.deal_id}, headers=DIRECTOR)
    assert first.status_code == again.status_code == 200
    assert first.json()["routing_status"] == "assigned"
    assert (await api.get(f"/sales/mail/inbox/{rid}", headers=DIRECTOR)).status_code == 404
    other = await accepted_outgoing(session, number="OTHER", key="other-request")
    assert (await api.post(endpoint, json={"deal_id": other.deal_id}, headers=DIRECTOR)).status_code == 409
    audits = (await session.scalars(select(AuditLog).where(AuditLog.action == "sales.email.incoming_assigned"))).all()
    assert len(audits) == 1 and audits[0].detail["previous_deal_id"] is None


@pytest.mark.parametrize("filename,content,content_type", [
    ("../unsafe.txt", b"safe", "text/plain"), ("run.exe", b"MZ", "application/octet-stream"),
    ("active.html", b"<script>alert(1)</script>", "text/html"), ("fake.pdf", b"%PDF-bad", "application/pdf"),
])
async def test_unsafe_attachments_are_preserved_but_not_downloaded(api, token_headers, filename, content, content_type):
    result = await ingest(api, token_headers, raw_message(attachments=[(filename, content, content_type)]))
    rid = result.json()["receipt_id"]
    detail = (await api.get(f"/sales/mail/inbox/{rid}")).json()
    meta = detail["attachments"][0]
    assert not meta["downloadable"] and meta["blocked_reason"]
    assert "/" not in meta["filename"] and "\\" not in meta["filename"]
    assert (await api.get(f"/sales/mail/inbox/{rid}/attachments/0")).status_code == 422


async def test_html_only_mail_has_inert_readable_text(api, token_headers):
    message = EmailMessage()
    message["From"] = "control@example.test"
    message["To"] = "order@microchips.by"
    message.set_content(
        '<p>Нужен счёт &amp; договор</p><script>steal()</script>'
        '<style>hidden-style</style><img src="https://invalid.test/tracker"><div>Количество: 6</div>',
        subtype="html",
    )
    response = await ingest(api, token_headers, message.as_bytes())
    rid = response.json()["receipt_id"]
    detail = (await api.get(f"/sales/mail/inbox/{rid}")).json()
    assert "Нужен счёт & договор" in detail["body_text"]
    assert "Количество: 6" in detail["body_text"]
    assert not any(value in detail["body_text"] for value in ("steal", "hidden-style", "tracker", "<img"))


@pytest.mark.parametrize("parser_failure", [False, True], ids=["native-parser", "parser-assertion"])
async def test_malformed_html_is_durable_for_review(api, token_headers, monkeypatch, parser_failure):
    if parser_failure:
        def reject_html(self, content):
            raise AssertionError("synthetic parser failure")
        monkeypatch.setattr(mail_routing._PlainHTML, "feed", reject_html)
    message = EmailMessage()
    message["From"] = "control@example.test"
    message["To"] = "order@microchips.by"
    message.set_content("<![bogus]><p>text</p>", subtype="html")
    response = await ingest(api, token_headers, message.as_bytes())
    assert response.status_code == 201
    rid = response.json()["receipt_id"]
    detail = (await api.get(f"/sales/mail/inbox/{rid}")).json()
    assert detail["routing_status"] == "unresolved"
    # Newer Python parsers tolerate this declaration. Both outcomes must retain
    # the original for review; a parser failure must never produce HTTP 500.
    if parser_failure:
        assert detail["routing_reason"] == "malformed_mime"
    else:
        assert detail["routing_reason"] in {"malformed_mime", "unknown_chain"}
    assert detail["raw_sha256"] == digest(message.as_bytes())


async def test_forwarded_message_is_one_blocked_attachment(api, token_headers):
    inner = EmailMessage()
    inner.set_content("Inner body")
    inner.add_attachment(b"safe content", maintype="text", subtype="plain", filename="safe.txt")
    outer = EmailMessage()
    outer["From"] = "control@example.test"
    outer["To"] = "order@microchips.by"
    outer.set_content("See forwarded original")
    outer.add_attachment(inner, filename="forwarded.eml")
    response = await ingest(api, token_headers, outer.as_bytes())
    rid = response.json()["receipt_id"]
    detail = (await api.get(f"/sales/mail/inbox/{rid}")).json()
    assert len(detail["attachments"]) == 1
    meta = detail["attachments"][0]
    assert meta["filename"] == "forwarded.eml"
    assert meta["size"] is None and meta["sha256"] is None
    assert meta["downloadable"] is False
    assert (await api.get(f"/sales/mail/inbox/{rid}/attachments/0")).status_code == 422


async def test_corrupted_raw_download_fails_without_disclosure(api, session, token_headers):
    result = await ingest(api, token_headers, raw_message(attachments=[("a.txt", b"safe", "text/plain")]))
    rid = result.json()["receipt_id"]
    row = await session.scalar(select(IncomingEmail).where(IncomingEmail.id == rid).options(undefer(IncomingEmail.raw)))
    row.raw = b"changed outside application"
    await session.commit()  # SQLite has no PostgreSQL snapshot triggers.
    assert (await api.get(f"/sales/mail/inbox/{rid}/attachments/0")).status_code == 409


async def test_list_is_bounded_and_does_not_load_raw_or_text(api, session, token_headers):
    for uid in (1, 2, 3):
        await ingest(api, token_headers, uid=uid)
    session.expunge_all()
    row = await session.scalar(select(IncomingEmail))
    assert {"raw", "body_text", "headers"} <= inspect(row).unloaded
    page = (await api.get("/sales/mail/inbox?limit=2&offset=0")).json()
    assert len(page["items"]) == 2 and page["next_offset"] == 2
    assert "body_text" not in page["items"][0] and "headers" not in page["items"][0]
    last = (await api.get("/sales/mail/inbox?limit=2&offset=2")).json()
    assert len(last["items"]) == 1 and last["next_offset"] is None
    for query in ("limit=0", "limit=101", "offset=-1", "offset=1000001"):
        assert (await api.get(f"/sales/mail/inbox?{query}")).status_code == 422


async def test_reply_snapshot_recipient_and_idempotency(api, session, token_headers, monkeypatch):
    monkeypatch.setattr(mail_routes, "sender_or_503", lambda core: "crm@example.test")
    original = await accepted_outgoing(session)
    raw = raw_message(references=[original.message_id], reply_to="attacker@example.test")
    rid = (await ingest(api, token_headers, raw)).json()["receipt_id"]
    endpoint = f"/sales/deals/{original.deal_id}/emails/prepare"
    payload = {"request_key": "reply-request", "to": ["control@example.test"],
               "subject": "Synthetic reply", "body": "Explicit reply", "reply_to_receipt_id": rid}
    wrong = await api.post(endpoint, json={**payload, "to": ["attacker@example.test"]}, headers=DIRECTOR)
    assert wrong.status_code == 422
    first = await api.post(endpoint, json=payload, headers=DIRECTOR)
    assert first.status_code == 201, first.text
    email_id = first.json()["id"]
    email = await session.scalar(select(OutgoingEmail).where(OutgoingEmail.id == email_id).options(undefer(OutgoingEmail.mime)))
    frozen = email.mime
    parsed = BytesParser(policy=policy.default).parsebytes(frozen)
    assert str(parsed["In-Reply-To"]) == "<incoming@example.test>"
    assert original.message_id in str(parsed["References"])
    assert "<incoming@example.test>" in str(parsed["References"])
    assert parsed["To"] == "control@example.test" and parsed["Reply-To"] is None
    profile = await session.scalar(select(User).where(User.username == "director"))
    profile.full_name = "Changed profile"
    await session.commit()
    again = await api.post(endpoint, json=payload, headers=DIRECTOR)
    assert again.json()["id"] == email_id
    assert email.mime == frozen and email.reply_to_receipt_id == rid
    conflict = await api.post(endpoint, json={**payload, "reply_to_receipt_id": None}, headers=DIRECTOR)
    assert conflict.status_code == 409
    other = await accepted_outgoing(session, number="OTHER", key="other-request")
    foreign = await api.post(f"/sales/deals/{other.deal_id}/emails/prepare", json={**payload, "request_key": "foreign-reply"}, headers=DIRECTOR)
    assert foreign.status_code == 404


async def test_action_flags_hide_creator_identity_and_foreign_buttons(api, session, monkeypatch):
    monkeypatch.setenv("AIOS_SALES_EMAIL_ENABLED", "1")
    monkeypatch.setattr(mail_routes, "sender_or_503", lambda core: "crm@example.test")
    email = await prepared(session)
    prefix = f"/sales/deals/{email.deal_id}/emails"
    own = (await api.get(prefix, headers=DIRECTOR)).json()[0]
    foreign = (await api.get(f"{prefix}/{email.id}", headers={"X-User": "other"})).json()
    assert own["can_confirm"] and not own["can_retry"]
    assert not foreign["can_confirm"] and not foreign["can_retry"]
    assert "created_by" not in own and "confirmed_by" not in own
    email.status, email.attempt_count = "uncertain", 1
    await session.commit()
    detail = (await api.get(f"{prefix}/{email.id}", headers=DIRECTOR)).json()
    assert detail["can_retry"] and not detail["can_confirm"]
    monkeypatch.setenv("AIOS_SALES_EMAIL_ENABLED", "0")
    assert not (await api.get(f"{prefix}/{email.id}", headers=DIRECTOR)).json()["can_retry"]


@pytest.mark.parametrize("raw", [
    b"From: a@example.test\r\nSubject: " + b"x" * (64 * 1024) + b"\r\n\r\ntext",
    b"From: a@example.test\r\nContent-Type: multipart/mixed; boundary=x\r\n\r\n" +
    (b"--x\r\nContent-Type: text/plain\r\n\r\npart\r\n" * 130) + b"--x--\r\n",
], ids=["large-header", "too-many-parts"])
def test_excessive_mime_is_reviewed(raw):
    _, problem = mail_routing.extract_message(raw)
    assert problem == "malformed_mime"
