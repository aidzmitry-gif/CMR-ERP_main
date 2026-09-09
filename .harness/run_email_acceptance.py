"""Synthetic integration snapshot; never imports credentials or writes dependency checkout."""
# ruff: noqa: E402 -- dependency snapshot must be selected before CRM imports

import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
dependency = Path(sys.argv[1]).resolve()
output = (
    ROOT / "reports/email-send-001" / ("acceptance-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
)
output.mkdir(parents=True)
snapshot = output / "dependency"
snapshot.mkdir()
(snapshot / ".gitignore").write_text("*\n")
manifest = {}
for name in (
    "models.py",
    "access.py",
    "routes.py",
    "documents.py",
    "events.py",
    "reserve.py",
    "schemas.py",
):
    data = (dependency / "modules/sales" / name).read_bytes()
    manifest[name] = hashlib.sha256(data).hexdigest()
    if name == "models.py":
        data += b"\nfrom modules.sales.mail_models import OutgoingEmail, EmailAttempt\n"
    (snapshot / name).write_bytes(data)
(snapshot / "test_document_versions.py").write_bytes(
    (dependency / "tests/test_document_versions.py").read_bytes()
)
(output / "dependency-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
import modules.sales

modules.sales.__path__.insert(0, str(snapshot))
sys.path.insert(0, str(snapshot))
os.environ.update(
    {
        "AIOS_ENVIRONMENT": "dev",
        "AIOS_AUTH_MODE": "dev",
        "AIOS_SALES_EMAIL_ENABLED": "1",
        "AIOS_DATABASE_URL": "sqlite+aiosqlite:///" + (output / "synthetic.db").as_posix(),
        "AIOS_SMTP_HOST": "127.0.0.1",
        "AIOS_SMTP_FROM": "crm@example.test",
        "AIOS_SMTP_TLS": "false",
        "AIOS_SMTP_USER": "",
        "AIOS_SMTP_PASSWORD": "",
        "AIOS_SMTP_PORT": "2525",
    }
)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from email import policy
from email.parser import BytesParser
from io import BytesIO
from socketserver import StreamRequestHandler, ThreadingTCPServer
from threading import Thread

import uvicorn
from httpx import ASGITransport, AsyncClient
from pypdf import PdfReader
from test_document_versions import make_contract, make_invoice

from core.runtime.app import create_app
from modules.sales.models import Deal, PriceQuote

state = {"mode": "accepted", "received": 0, "attempts": 0, "envelopes": []}


class SMTPHandler(StreamRequestHandler):
    def reply(self, line):
        self.wfile.write(line + b"\r\n")
        self.wfile.flush()

    def handle(self):
        self.reply(b"220 local synthetic SMTP")
        envelope = []
        while line := self.rfile.readline():
            command = line.split(b" ", 1)[0].strip().upper()
            if command == b"EHLO":
                self.reply(b"250-localhost")
                self.reply(b"250 SIZE 20971520")
            elif command == b"RCPT":
                envelope.append(line.decode().strip())
                self.reply(b"250 ok")
            elif command == b"DATA":
                self.reply(b"354 send")
                content = bytearray()
                while (line := self.rfile.readline()) not in (b".\r\n", b""):
                    content.extend(line[1:] if line.startswith(b"..") else line)
                state["attempts"] += 1
                mode = state["mode"]
                if mode in {"accepted", "uncertain"}:
                    state["received"] += 1
                    state["envelopes"].append(envelope)
                    (output / f"received-{state['received']}.eml").write_bytes(content)
                if mode == "uncertain":
                    return
                self.reply(
                    {
                        "accepted": b"250 accepted",
                        "failed": b"550 rejected",
                        "retry_wait": b"451 temporary",
                    }[mode]
                )
            elif command == b"QUIT":
                self.reply(b"221 bye")
                return
            else:
                self.reply(b"250 ok")


async def main():
    smtp = ThreadingTCPServer(("127.0.0.1", 0), SMTPHandler)
    smtp.daemon_threads = True
    thread = Thread(target=smtp.serve_forever, daemon=True)
    thread.start()
    os.environ["AIOS_SMTP_PORT"] = str(smtp.server_address[1])
    app = create_app()
    db = app.state.core.services.db
    await db.connect()
    async with db.session_factory() as session:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-User-Roles": "director"},
        ) as api:
            deal, invoice, sku, cp, item = await make_invoice(api, session)
            contract, template = await make_contract(api, session, deal)
            response = await api.post(
                f"/sales/documents/{contract['id']}/decide", json={"approved": True}
            )
            assert response.status_code == 200, response.text
            base = f"/sales/deals/{deal['id']}/emails"
            body = {
                "request_key": "acceptance-fixed-v1",
                "document_ids": [invoice["id"], contract["id"]],
                "to": ["control@example.test"],
                "cc": ["copy@example.test"],
                "subject": "Контроль: счёт и договор",
                "body": "Только синтетические документы.",
            }
            response = await api.post(base + "/prepare", json=body)
            assert response.status_code == 201, response.text
            email = response.json()
            assert email["status"] == "prepared" and state["received"] == 0
            pdfs = []
            for index, name in enumerate(("invoice-v1.pdf", "contract-v1.pdf")):
                result = await api.get(f"{base}/{email['id']}/attachments/{index}")
                assert result.status_code == 200, result.text
                content = result.content
                extracted = "\n".join(
                    page.extract_text() for page in PdfReader(BytesIO(content)).pages
                )
                assert ("240.00" if index == 0 else "200.00") in extracted, extracted
                assert "Battery original" in extracted and "Buyer original" in extracted
                assert hashlib.sha256(content).hexdigest() == email["attachments"][index]["sha256"]
                (output / name).write_bytes(content)
                pdfs.append(content)
            sku.title = "Changed product after prepared email"
            template.body = "<p>Changed contract template</p>"
            cp.requisites = {"address": "Changed buyer address"}
            session.add(PriceQuote(sku_code=sku.code, counterparty=cp.name, price=Decimal("150")))
            row = await session.get(Deal, deal["id"])
            row.title = "Контроль отправки CRM"
            await session.commit()
            revised = await api.post(
                f"/sales/documents/{invoice['id']}/revision",
                json={"reason": "Synthetic new price", "request_key": "email-new-version"},
            )
            assert revised.status_code == 201, revised.text
            revision = revised.json()
            issued = await api.post(f"/sales/documents/{revision['id']}/issue")
            assert issued.status_code == 200 and issued.json()["amount"] == 360, issued.text
            for index, original in enumerate(pdfs):
                assert (
                    await api.get(f"{base}/{email['id']}/attachments/{index}")
                ).content == original
            assert (await api.post(base + "/prepare", json=body)).json()["id"] == email["id"]
            evidence = {
                "synthetic_only": True,
                "dependency_snapshot": manifest,
                "deal_id": deal["id"],
                "email_id": email["id"],
                "invoice_v1_amount": 240,
                "invoice_v2_amount": 360,
                "contract_amount": 200,
                "pdfs_unchanged_after_source_mutation_and_new_version": True,
                "prepared_without_smtp": True,
                "idempotent_prepare": True,
                "output": str(output),
            }
            (output / "evidence.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    await db.disconnect()

    @app.get("/qa/state")
    async def qa_state():
        return {**state, "output": str(output), "deal_id": deal["id"], "email_id": email["id"]}

    @app.post("/qa/mode/{mode}")
    async def qa_mode(mode: str):
        assert mode in {"accepted", "uncertain", "failed", "retry_wait"}
        state["mode"] = mode
        return state

    @app.get("/qa/verify")
    async def qa_verify():
        content = (output / "received-1.eml").read_bytes()
        parsed = BytesParser(policy=policy.default).parsebytes(content)
        received_pdfs = [part.get_payload(decode=True) for part in parsed.iter_attachments()]
        assert received_pdfs == pdfs
        assert (
            str(parsed["To"]) == "control@example.test" and str(parsed["Cc"]) == "copy@example.test"
        )
        assert str(parsed["Message-ID"]) == email["message_id"]
        evidence.update(
            smtp_received=state["received"],
            smtp_attempts=state["attempts"],
            received_mime_attachments_exact=True,
            received_to_cc_correct=True,
        )
        (output / "evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return evidence

    print("ACCEPTANCE_READY " + str(output), flush=True)
    try:
        await uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=18816, log_level="warning")
        ).serve()
    finally:
        smtp.shutdown()
        smtp.server_close()
        thread.join(timeout=2)


asyncio.run(main())
