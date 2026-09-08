"""Versioned intake: authenticated bounded input -> durable inbox -> lead receipt.

Legacy web/email endpoints remain unchanged. Producers must retain their spool
until GET returns delivered with lead_id and every expected file hash/attachment_id.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import IntakeIdentity, IntakeReceipt
from core.runtime.core import Core
from core.runtime.deps import get_core, get_session
from core.services import intake_storage as storage
from core.services.eventbus import EventContext
from modules.integrations.schemas import IntakeRequestIn

router = APIRouter()
logger = logging.getLogger("aios.integrations.intake")
MAX_BODY_BYTES = 32 * 1024 * 1024
MAX_TOTAL_FILE_BYTES = 20 * 1024 * 1024


def _authenticate(request: Request, core: Core) -> None:
    expected = core.config.intake_webhook_token
    actual = request.headers.get("X-Intake-Token", "")
    if not expected or not hmac.compare_digest(actual.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Неверный или ненастроенный токен приёма")


def _object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Повтор ключа JSON")
        result[key] = value
    return result


def _reject_constant(value: str):
    raise ValueError("Недопустимая JSON-константа")


async def _read_request(request: Request) -> IntakeRequestIn:
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        raise HTTPException(status_code=415, detail="Нужен application/json")
    if request.headers.get("content-encoding", "identity") != "identity":
        raise HTTPException(status_code=415, detail="Сжатое тело не поддерживается")
    length = request.headers.get("content-length")
    if length is not None:
        try:
            count = int(length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Некорректный Content-Length") from exc
        if count < 0:
            raise HTTPException(status_code=400, detail="Некорректный Content-Length")
        if count > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Тело запроса слишком велико")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Тело запроса слишком велико")
        body.extend(chunk)
    try:
        raw = json.loads(body.decode("utf-8"), object_pairs_hook=_object, parse_constant=_reject_constant)
        return IntakeRequestIn.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422, detail=exc.errors(include_input=False, include_context=False)
        ) from exc
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise HTTPException(status_code=400, detail="Некорректный JSON") from exc


def _prepare(request: IntakeRequestIn) -> tuple[dict, str, list]:
    """All files validated before any database row or file is written."""
    payload = request.model_dump(exclude={"files"})
    files, total = [], 0
    for item in sorted(request.files, key=lambda file: file.file_id):
        content_type, data = storage.decode_data_url(item.data_url)
        storage.validate_attachment(content_type, data)
        digest = hashlib.sha256(data).hexdigest()
        if len(data) != item.size_bytes or digest != item.sha256:
            raise storage.AttachmentRejected("Размер или SHA256 вложения не совпадает")
        total += len(data)
        if total > MAX_TOTAL_FILE_BYTES:
            raise storage.AttachmentRejected("Суммарный размер файлов превышен")
        files.append(({
            "file_id": item.file_id, "filename": item.filename, "content_type": content_type,
            "size_bytes": len(data), "sha256": digest,
        }, data))
    payload["files"] = [metadata for metadata, _ in files]
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return payload, hashlib.sha256(canonical.encode()).hexdigest(), files


async def _insert_once(session: AsyncSession, model, values: dict, keys: list[str]) -> None:
    dialect = session.get_bind().dialect.name
    insert = pg_insert if dialect == "postgresql" else sqlite_insert
    if dialect not in {"postgresql", "sqlite"}:
        raise RuntimeError("Unsupported intake database")
    await session.execute(insert(model).values(**values).on_conflict_do_nothing(index_elements=keys))


async def _view(
    receipt: IntakeReceipt, identity: IntakeIdentity, session: AsyncSession, core: Core,
) -> dict:
    status, error = receipt.status, receipt.error_code
    if status == "delivered":
        try:
            check = {"receipt_id": receipt.id, "verified": False}
            await core.event_bus.dispatch(
                "intake.receipt.check", check, EventContext(session, core.services),
            )
            if check.get("verified") is not True:
                raise storage.AttachmentRejected("Delivery records are unavailable")
        except Exception as exc:
            logger.warning("Intake receipt check failed: %s", type(exc).__name__)
            status, error = "unavailable", "delivered_record_unavailable"
    return {
        "receipt_id": receipt.id, "status": status, "namespace": receipt.namespace,
        "identity_namespace": identity.namespace, "source_id": identity.source_id,
        "delivery_id": receipt.delivery_id, "payload_sha256": receipt.payload_sha256,
        "lead_id": identity.lead_id if status == "delivered" else None,
        "files": [{k: v for k, v in item.items() if k != "storage_path"} for item in receipt.files],
        "error_code": error,
    }


@router.post("/intake/v1")
async def receive(
    request: Request,
    core: Core = Depends(get_core),
    session: AsyncSession = Depends(get_session),
):
    _authenticate(request, core)  # Must precede body parsing, including malformed requests.
    incoming = await _read_request(request)
    try:
        payload, digest, files = _prepare(incoming)
    except storage.AttachmentRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        await _insert_once(session, IntakeIdentity, {
            "namespace": incoming.identity_namespace, "source_id": incoming.source_id,
        }, ["namespace", "source_id"])
        # Consistent lock order with the subscriber: identity, then receipt.
        identity = (await session.execute(select(IntakeIdentity).where(
            IntakeIdentity.namespace == incoming.identity_namespace,
            IntakeIdentity.source_id == incoming.source_id,
        ).with_for_update().execution_options(populate_existing=True))).scalar_one()
        candidate_id = uuid4().hex
        await _insert_once(session, IntakeReceipt, {
            "id": candidate_id, "identity_id": identity.id, "namespace": incoming.namespace,
            "delivery_id": incoming.delivery_id, "payload_sha256": digest, "payload": payload,
            "files": [], "status": "queued",
        }, ["namespace", "delivery_id"])
        receipt = (await session.execute(select(IntakeReceipt).where(
            IntakeReceipt.namespace == incoming.namespace,
            IntakeReceipt.delivery_id == incoming.delivery_id,
        ).with_for_update().execution_options(populate_existing=True))).scalar_one()
        if receipt.payload_sha256 != digest or receipt.identity_id != identity.id:
            raise HTTPException(status_code=409, detail="delivery_id уже имеет другое содержимое")
        if receipt.status == "delivered":
            result = await _view(receipt, identity, session, core)
            await session.commit()
            return JSONResponse(result, status_code=200)

        manifest = []
        blob_key = hashlib.sha256(
            f"{incoming.namespace}\0{incoming.delivery_id}\0{digest}".encode()
        ).hexdigest()
        for metadata, data in files:
            name = hashlib.sha256(metadata["file_id"].encode()).hexdigest()
            path = f"_intake/{blob_key}/{name}{storage.ALLOWED_CONTENT_TYPES[metadata['content_type']]}"
            entry = {**metadata, "storage_path": path, "attachment_id": None}
            # Stable across rolled-back inserts; retries re-fsync, including when
            # a previous write succeeded but its directory fsync/DB commit failed.
            storage.durable_write(storage.attachment_root(), path, data)
            manifest.append(entry)
        receipt.files = manifest
        if receipt.id == candidate_id or receipt.status == "failed":
            receipt.status, receipt.error_code = "queued", None
            receipt.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            # Receipt is inserted first, both are committed atomically after durable files.
            core.event_bus.emit(session, "intake.lead.received", {"receipt_id": receipt.id})
        await session.commit()
        return JSONResponse(await _view(receipt, identity, session, core), status_code=202)
    except HTTPException:
        await session.rollback()
        raise
    except Exception as exc:
        await session.rollback()
        logger.warning("Intake enqueue failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Приём не подтверждён; повторите delivery_id") from exc


@router.get("/intake/v1/receipts/{receipt_id}")
async def get_receipt(
    receipt_id: str,
    request: Request,
    core: Core = Depends(get_core),
    session: AsyncSession = Depends(get_session),
):
    _authenticate(request, core)
    receipt = await session.get(IntakeReceipt, receipt_id, populate_existing=True)
    if receipt is None:
        raise HTTPException(status_code=404, detail="Подтверждение не найдено")
    identity = await session.get(IntakeIdentity, receipt.identity_id, populate_existing=True)
    return await _view(receipt, identity, session, core)
