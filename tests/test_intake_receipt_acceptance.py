"""Local producer-to-receipt acceptance using synthetic inputs only.

Microchips producer state/retry behavior is already covered by
``ops/intake/test_microchips_crm_intake.php``; its form source identity and the
real receipt/lead dedupe path are covered by
``tests/test_intake_receipts.py::test_identity_is_not_sender_and_site_copy_joins_exact_source``.
This file exercises the missing Python producer -> actual ASGI receiver seam.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import shutil
import subprocess
import sys
import tempfile
import threading
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit

import pytest

pytest_plugins = ("tests.test_intake_receipts",)

INTAKE_DIR = Path(__file__).resolve().parents[1] / "ops" / "intake"
if str(INTAKE_DIR) not in sys.path:
    sys.path.insert(0, str(INTAKE_DIR))

import mail_delivery  # noqa: E402
import mail_receipts  # noqa: E402
import mail_stage  # noqa: E402
import mottor_bridge  # noqa: E402
import mottor_receipts  # noqa: E402
import receipt_queue  # noqa: E402
from tests import test_intake_receipts as receiver  # noqa: E402


def _email(*, message_id: str, sender: str = "buyer@example.invalid", attachment: bool = False) -> bytes:
    message = EmailMessage()
    message["From"] = f"Synthetic Buyer <{sender}>"
    message["To"] = "admin@enersys.by"
    message["Subject"] = "Запрос аккумуляторов для синтетического стенда"
    message["Message-ID"] = f"<{message_id}@example.invalid>"
    message.set_content("Просим рассчитать аккумуляторы для тестового оборудования.")
    if attachment:
        message.add_attachment(
            b"%PDF-1.4 synthetic specification\n%%EOF\n",
            maintype="application", subtype="pdf", filename="synthetic-request.pdf",
        )
    return message.as_bytes()


async def _run_with_receiver(env, operation, *, get_override=None):
    """Run a sync SQLite producer in a worker and bridge its HTTP calls to ASGI."""
    loop = asyncio.get_running_loop()
    observed = {"posts": [], "gets": []}

    async def post_async(payload):
        response = await env.api.post(receiver.URL, json=payload)
        assert response.status_code in (200, 202), response.text
        result = response.json()
        observed["posts"].append((payload, result))
        return result

    async def get_async(receipt_id):
        if get_override is not None:
            result = await get_override(receipt_id)
        else:
            await env.relay()
            result = await receiver.receipt(env, receipt_id)
        observed["gets"].append(result)
        return result

    def post(payload):
        return asyncio.run_coroutine_threadsafe(post_async(payload), loop).result(timeout=30)

    def get(receipt_id):
        return asyncio.run_coroutine_threadsafe(get_async(receipt_id), loop).result(timeout=30)

    result = await asyncio.to_thread(operation, post, get)
    return result, observed


async def _run_microchips_php_bridge(env, runner: Path, spool: Path, php: str):
    """Run the PHP producer and route its injected transport over local pipes to ASGI."""
    loop = asyncio.get_running_loop()
    exchanges = []

    async def dispatch(event):
        parts = urlsplit(event["url"])
        assert parts.scheme == "https" and parts.netloc == "belakb.by"
        assert not parts.query and not parts.fragment
        headers = {}
        for raw_header in event["headers"]:
            name, separator, value = raw_header.partition(":")
            assert separator
            headers[name.strip().lower()] = value.strip()
        assert headers.get("x-intake-token") == "test-intake-only"

        method = event["method"]
        body = event["body"]
        if method == "POST":
            assert parts.path == receiver.URL
            assert isinstance(body, str)
            assert "test-intake-only" not in body
            response = await env.api.post(
                receiver.URL, content=body,
                headers={
                    "Accept": headers["accept"],
                    "Content-Type": headers["content-type"],
                    "X-Intake-Token": headers["x-intake-token"],
                },
            )
        elif method == "GET":
            assert parts.path.startswith(receiver.URL + "/receipts/")
            assert body is None
            response = await env.api.get(
                parts.path,
                headers={"Accept": headers["accept"], "X-Intake-Token": headers["x-intake-token"]},
            )
        else:
            raise AssertionError(f"unexpected PHP transport method: {method}")

        assert response.status_code in (200, 202), response.text
        return {"http_code": response.status_code, "body": response.text}

    def run():
        process = None
        timer = None
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as errors:
            try:
                process = subprocess.Popen(
                    [php, str(runner), str(spool)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=errors,
                    text=True,
                    encoding="utf-8",
                    bufsize=1,
                )
                timer = threading.Timer(
                    60, lambda: process.kill() if process.poll() is None else None,
                )
                timer.daemon = True
                timer.start()
                assert process.stdin is not None and process.stdout is not None
                result = None
                for line in process.stdout:
                    message = json.loads(line)
                    if message.get("kind") == "transport":
                        reply = asyncio.run_coroutine_threadsafe(dispatch(message), loop).result(timeout=30)
                        exchanges.append({"request": message, "response": reply})
                        process.stdin.write(json.dumps(reply, separators=(",", ":")) + "\n")
                        process.stdin.flush()
                    elif message.get("kind") == "result" and result is None:
                        result = message
                    else:
                        raise AssertionError("unexpected PHP bridge output")
                return_code = process.wait(timeout=5)
                errors.seek(0)
                error_text = errors.read()
                assert return_code == 0, f"PHP bridge failed ({return_code}): {error_text[:1000]}"
                assert result is not None, f"PHP bridge returned no result: {error_text[:1000]}"
                return result, exchanges
            finally:
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)
                    if process.stdin is not None:
                        process.stdin.close()
                    if process.stdout is not None:
                        process.stdout.close()
                if timer is not None:
                    timer.cancel()

    return await asyncio.to_thread(run)


def _mottor_delivery(queue_path: Path, post, get):
    db = mottor_bridge.connect(queue_path)
    try:
        receipt_queue.setup(db)
        now = dt.datetime(2026, 9, 24, 12, 0, tzinfo=dt.timezone.utc)
        mottor_bridge.initialize(db, now - dt.timedelta(minutes=1))
        source = {
            "id": 730001,
            "d_created": now.isoformat(),
            "name": "Synthetic Mottor Buyer",
            "phone": "+375290001122",
            "email": "mottor-buyer@example.invalid",
            "page": {"site_id": 1191119, "site": {"attached_domain": "enersys.by"}},
            "form": {"name": "synthetic acceptance"},
        }
        with db:
            db.execute(
                "INSERT INTO deliveries VALUES(?,?,?,?,?)",
                (source["id"], "pending", json.dumps(source), now.isoformat(), ""),
            )

        mottor_receipts.stage(db)
        mottor_receipts.stage(db)  # The source's second appearance must not add another outbox row.
        row = db.execute(
            "SELECT payload FROM receipt_outbox WHERE namespace='enersys.by'"
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        accepted = receipt_queue.deliver(db, post, get)
        mottor_receipts.reconcile(db)
        return {
            "payload": payload,
            "accepted": accepted,
            "source_states": mottor_bridge.status(db),
            "receipt_states": receipt_queue.status(db),
            "outbox_count": db.execute("SELECT COUNT(*) FROM receipt_outbox").fetchone()[0],
        }
    finally:
        db.close()


def _mail_delivery(queue_path: Path, raw: bytes, post, get):
    db = mail_stage.open_queue(queue_path)
    try:
        mail_delivery.setup(db)
        with db:
            mail_stage.set_meta(db, "uidvalidity", "9101")
            mail_stage.stage(db, 17, raw)
        mail_delivery.prepare_pending(db)
        mail_delivery.prepare_pending(db)
        row = db.execute("SELECT payload FROM receipt_outbox").fetchone()
        payload = json.loads(row[0]) if row else None
        accepted = receipt_queue.deliver(db, post, get)
        mail_delivery.reconcile(db)
        return {
            "payload": payload,
            "accepted": accepted,
            "states": mail_delivery.status(db),
            "outbox_count": db.execute("SELECT COUNT(*) FROM receipt_outbox").fetchone()[0],
        }
    finally:
        db.close()


async def test_mottor_producer_creates_one_receipted_lead_and_replay_is_idempotent(intake_env, tmp_path):
    env = intake_env
    result, observed = await _run_with_receiver(
        env, lambda post, get: _mottor_delivery(tmp_path / "mottor.sqlite3", post, get),
    )

    assert result["payload"]["source_id"] == "mottor:1191119:730001"
    assert result["payload"]["delivery_id"] == "mottor:1191119:730001:initial"
    assert result["accepted"] == 1
    assert result["source_states"] == {"delivered": 1}
    assert result["receipt_states"] == {"delivered": 1}
    assert result["outbox_count"] == 1
    assert observed["gets"][0]["status"] == "delivered"
    assert observed["gets"][0]["lead_id"] > 0
    assert await receiver.count(env.session, receiver.Lead) == 1
    assert await receiver.count(env.session, receiver.IntakeIdentity) == 1
    assert await receiver.count(env.session, receiver.Counterparty) == 0

    replay = await env.api.post(receiver.URL, json=result["payload"])
    assert replay.status_code == 200
    assert replay.json()["receipt_id"] == observed["gets"][0]["receipt_id"]
    assert replay.json()["lead_id"] == observed["gets"][0]["lead_id"]
    assert await receiver.count(env.session, receiver.Lead) == 1
    assert await receiver.count(env.session, receiver.IntakeReceipt) == 1


async def test_mottor_failed_receipt_remains_visible_in_producer_queue(intake_env, tmp_path, monkeypatch):
    env = intake_env
    from modules.leads import leads

    original_score = leads.apply_initial_score
    failed = {"once": False}

    async def fail_once(lead, session):
        if not failed["once"]:
            failed["once"] = True
            raise RuntimeError("synthetic acceptance failure")
        return await original_score(lead, session)

    monkeypatch.setattr(leads, "apply_initial_score", fail_once)
    result, observed = await _run_with_receiver(
        env, lambda post, get: _mottor_delivery(tmp_path / "mottor-failed.sqlite3", post, get),
    )

    payload = result["payload"]
    assert failed["once"]
    assert payload["source_id"] == "mottor:1191119:730001"
    assert payload["delivery_id"] == "mottor:1191119:730001:initial"
    assert result["accepted"] == 0
    assert result["source_states"] == {"v1_pending": 1}
    assert result["receipt_states"] == {"failed": 1}
    assert result["outbox_count"] == 1

    failed_receipt = observed["gets"][0]
    assert failed_receipt["status"] == "failed"
    assert failed_receipt["source_id"] == payload["source_id"]
    assert failed_receipt["delivery_id"] == payload["delivery_id"]
    assert failed_receipt["lead_id"] is None
    assert await receiver.count(env.session, receiver.Lead) == 0
    assert await receiver.count(env.session, receiver.Counterparty) == 0
    assert await receiver.count(env.session, receiver.IntakeReceipt) == 1


async def test_microchips_php_producer_joins_actual_asgi_receipt_and_replay(intake_env, tmp_path):
    env = intake_env
    php = shutil.which("php")
    if php is None:
        pytest.skip("PHP CLI is required for the joined producer-to-receiver acceptance")
    runner = INTAKE_DIR / "test_microchips_crm_intake_asgi_bridge.php"
    spool = (tmp_path / "microchips-php-asgi-spool").resolve()

    first, first_exchanges = await _run_microchips_php_bridge(env, runner, spool, php)
    assert first["queue_state"] == "spooled"
    assert first["source_id"] == "form:1:result:987654"
    assert first["consume"]["processed"] == 1
    assert first["consume"]["errors"] == 0
    assert first["status"]["state"] == "queued"
    assert first["status"]["remote_status"] == "queued"
    assert first["status"]["lead_id"] is None
    assert first["pending_count"] == 1 and first["done_count"] == 0
    assert len(first_exchanges) == 1
    first_post = first_exchanges[0]
    assert first_post["request"]["method"] == "POST"
    assert first_post["response"]["http_code"] == 202
    first_body = first_post["request"]["body"]
    payload = json.loads(first_body)
    assert payload["namespace"] == "microchips.by"
    assert payload["source_id"] == "form:1:result:987654"
    assert payload["delivery_id"] == payload["source_id"]
    queued = json.loads(first_post["response"]["body"])
    assert queued["receipt_id"] == first["status"]["receipt_id"]
    assert queued["status"] == "queued"
    assert await receiver.count(env.session, receiver.IntakeReceipt) == 1
    assert await receiver.count(env.session, receiver.Lead) == 0

    await env.relay()
    delivered = await receiver.receipt(env, queued["receipt_id"])
    assert delivered["status"] == "delivered"
    assert delivered["receipt_id"] == queued["receipt_id"]
    assert delivered["source_id"] == payload["source_id"]
    assert delivered["delivery_id"] == payload["delivery_id"]
    assert delivered["lead_id"] > 0
    assert delivered["identity_namespace"] == "microchips.by"
    assert await receiver.count(env.session, receiver.Lead) == 1

    replay, replay_exchanges = await _run_microchips_php_bridge(env, runner, spool, php)
    assert replay["queue_state"] == "duplicate"
    assert replay["consume"]["processed"] == 1
    assert replay["consume"]["errors"] == 0
    assert replay["status"]["state"] == "delivered"
    assert replay["status"]["remote_status"] == "delivered"
    assert replay["status"]["receipt_id"] == delivered["receipt_id"]
    assert replay["status"]["lead_id"] == str(delivered["lead_id"])
    assert replay["pending_count"] == 0 and replay["done_count"] == 1
    assert [item["request"]["method"] for item in replay_exchanges] == ["POST", "GET"]

    replay_post, replay_get = replay_exchanges
    assert replay_post["request"]["body"] == first_body
    assert replay_post["response"]["http_code"] == 200
    replayed = json.loads(replay_post["response"]["body"])
    confirmed = json.loads(replay_get["response"]["body"])
    assert replayed["receipt_id"] == confirmed["receipt_id"] == delivered["receipt_id"]
    assert replayed["lead_id"] == confirmed["lead_id"] == delivered["lead_id"]
    assert confirmed["status"] == "delivered"
    assert await receiver.count(env.session, receiver.Lead) == 1
    assert await receiver.count(env.session, receiver.IntakeIdentity) == 1
    assert await receiver.count(env.session, receiver.IntakeReceipt) == 1
    assert await receiver.count(env.session, receiver.Counterparty) == 0


async def test_mail_producer_delivers_receipt_and_reports_missing_file_as_unavailable(intake_env, tmp_path):
    env = intake_env
    raw = _email(message_id="g05-mail-unavailable", attachment=True)

    async def delete_file_after_delivery(receipt_id):
        await env.relay()
        delivered = await receiver.receipt(env, receipt_id)
        assert delivered["status"] == "delivered"
        assert delivered["lead_id"] > 0 and len(delivered["files"]) == 1
        attachment = await env.session.get(
            receiver.LeadAttachment, delivered["files"][0]["attachment_id"],
        )
        path = receiver.intake_storage.resolve_path(env.root, attachment.storage_path)
        path.unlink()
        return await receiver.receipt(env, receipt_id)

    result, observed = await _run_with_receiver(
        env,
        lambda post, get: _mail_delivery(tmp_path / "mail-unavailable.sqlite3", raw, post, get),
        get_override=delete_file_after_delivery,
    )

    payload = result["payload"]
    assert payload["namespace"] == "admin@enersys.by"
    assert payload["source_id"].startswith("mail:")
    assert payload["delivery_id"] == payload["source_id"]
    assert result["accepted"] == 0
    assert result["states"]["receipts"] == {"unavailable": 1}
    assert result["states"]["messages"] == {"v1_pending": 1}
    assert result["outbox_count"] == 1
    assert observed["gets"][0]["status"] == "unavailable"
    assert observed["gets"][0]["lead_id"] is None
    assert await receiver.count(env.session, receiver.Lead) == 1
    assert await receiver.count(env.session, receiver.LeadAttachment) == 1
    assert await receiver.count(env.session, receiver.Counterparty) == 0


async def test_mail_failed_receipt_remains_visible_in_producer_queue(intake_env, tmp_path, monkeypatch):
    env = intake_env
    from modules.leads import leads

    original_score = leads.apply_initial_score
    failed = {"once": False}

    async def fail_once(lead, session):
        if not failed["once"]:
            failed["once"] = True
            raise RuntimeError("synthetic acceptance failure")
        return await original_score(lead, session)

    monkeypatch.setattr(leads, "apply_initial_score", fail_once)
    raw = _email(message_id="g05-mail-failed")
    result, observed = await _run_with_receiver(
        env, lambda post, get: _mail_delivery(tmp_path / "mail-failed.sqlite3", raw, post, get),
    )

    assert failed["once"]
    assert observed["gets"][0]["status"] == "failed"
    assert observed["gets"][0]["lead_id"] is None
    assert result["states"]["receipts"] == {"failed": 1}
    assert result["states"]["messages"] == {"v1_pending": 1}
    assert await receiver.count(env.session, receiver.Lead) == 0
    assert await receiver.count(env.session, receiver.Counterparty) == 0


async def test_legat_mail_stays_reviewable_without_verified_tender_parser(tmp_path):
    raw = _email(
        message_id="g05-legat-review", sender="notices@legat.by",
    )
    queue_path = tmp_path / "legat-review.sqlite3"
    db = mail_stage.open_queue(queue_path)
    try:
        mail_delivery.setup(db)
        with db:
            mail_stage.set_meta(db, "uidvalidity", "9102")
            mail_stage.stage(db, 18, raw)
        mail_delivery.prepare_pending(db)
        status = mail_delivery.status(db)
        payload = mail_receipts.prepare(raw, "9102", 18)
        assert payload == (None, "legat_requires_verified_tender_parser")
        assert status["review_reasons"] == {"legat_requires_verified_tender_parser": 1}
        assert status["receipts"] == {}
        assert db.execute("SELECT COUNT(*) FROM receipt_outbox").fetchone()[0] == 0
    finally:
        db.close()


async def test_mail_producer_creates_one_receipted_lead_and_replay_is_idempotent(intake_env, tmp_path):
    env = intake_env
    raw = _email(message_id="g05-mail-success")
    result, observed = await _run_with_receiver(
        env,
        lambda post, get: _mail_delivery(tmp_path / "mail-success.sqlite3", raw, post, get),
    )

    payload = result["payload"]
    assert payload["namespace"] == "admin@enersys.by"
    assert payload["source_id"].startswith("mail:")
    assert payload["delivery_id"] == payload["source_id"]
    assert result["accepted"] == 1
    assert result["states"]["receipts"] == {"delivered": 1}
    assert result["states"]["messages"] == {"delivered": 1}
    assert result["outbox_count"] == 1

    delivered = observed["gets"][0]
    assert delivered["status"] == "delivered"
    assert delivered["namespace"] == payload["namespace"]
    assert delivered["identity_namespace"] == payload["namespace"]
    assert delivered["source_id"] == payload["source_id"]
    assert delivered["delivery_id"] == payload["delivery_id"]
    assert delivered["lead_id"] > 0
    assert await receiver.count(env.session, receiver.Lead) == 1
    assert await receiver.count(env.session, receiver.IntakeIdentity) == 1
    assert await receiver.count(env.session, receiver.IntakeReceipt) == 1
    assert await receiver.count(env.session, receiver.Counterparty) == 0

    replay = await env.api.post(receiver.URL, json=payload)
    assert replay.status_code == 200
    replayed = replay.json()
    assert replayed["receipt_id"] == delivered["receipt_id"]
    assert replayed["source_id"] == delivered["source_id"]
    assert replayed["lead_id"] == delivered["lead_id"]
    assert await receiver.count(env.session, receiver.Lead) == 1
    assert await receiver.count(env.session, receiver.IntakeIdentity) == 1
    assert await receiver.count(env.session, receiver.IntakeReceipt) == 1
