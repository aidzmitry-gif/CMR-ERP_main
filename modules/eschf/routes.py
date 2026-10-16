"""Local durable API. Every mutation and its outbox entry share one transaction.

Trusted application startup may set app.state.eschf_source_provider and
app.state.eschf_evidence_adapter. Neither is constructed from request data.
The source provider must authorize the effective user, resolve an issued source
at the requested version, and check native binding/freshness before returning.
It must not sign or send. Missing wiring fails closed with 503.

Attaching signed bytes and authenticated observations only persists evidence;
there is no HTTP dispatch/claim endpoint or background transport registration.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, NoResultFound, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.runtime.deps import get_session
from core.services.auth import CurrentUser, get_current_user, require_permission
from modules.eschf.bridge import PreparedSource, PreviewStale, require_material_fingerprint
from modules.eschf.models import Attempt, Decision, Observation, SignedArtifact
from modules.eschf.preparation import sha256
from modules.eschf.repository import Repository, SnapshotInput

router = APIRouter(tags=["eschf"], dependencies=[Depends(require_permission("eschf.read"))])
Session = Annotated[AsyncSession, Depends(get_session)]
User = Annotated[CurrentUser, Depends(get_current_user)]
PositiveID = Annotated[int, Field(strict=True, gt=0, le=2147483647)]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024


class SourceProvider(Protocol):
    async def prepare_source(
        self,
        request: Request,
        user: CurrentUser,
        source_document_id: int,
        source_document_version: int,
    ) -> PreparedSource:
        """Authorize source access and return the final, current native projection.

        PermissionError means forbidden source access; ValueError means a stale
        or ineligible source. No caller-provided native identity is accepted.
        Synthetic providers must keep environment='synthetic'.
        Return PreparedSource with a mandatory final DB-only recheck; the router
        calls it inside the durable write transaction. Raw SnapshotInput is not
        an accepted provider result.
        """
        ...

    async def revalidate_source(
        self,
        request: Request,
        user: CurrentUser,
        persisted: SnapshotInput,
    ) -> PreparedSource:
        """Return the exact persisted value plus a fresh DB-only recheck, or fail."""
        ...


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PreparationRequest(EmptyRequest):
    source_document_id: PositiveID
    source_document_version: PositiveID


class RefreshRequest(EmptyRequest):
    source_document_version: PositiveID


class ApprovalRequest(EmptyRequest):
    binding_sha256: Hash
    unsigned_sha256: Hash


def _repository(request: Request, session: AsyncSession) -> Repository:
    core = request.app.state.core
    return Repository(
        session,
        core=core,
        event_bus=core.event_bus,
        adapter=getattr(request.app.state, "eschf_evidence_adapter", None),
    )


@asynccontextmanager
async def _transaction(session: AsyncSession):
    # Exception translation is outside begin(): failures (including outbox and
    # commit failures) roll back. Never disclose SQL or raw provider evidence.
    try:
        async with session.begin():
            yield
    except PermissionError as exc:
        raise HTTPException(403, "eschf_access_denied") from exc
    except NoResultFound as exc:
        raise HTTPException(404, "eschf_snapshot_not_found") from exc
    except PreviewStale as exc:
        raise HTTPException(409, "preview_stale") from exc
    except (ValueError, IntegrityError) as exc:
        raise HTTPException(409, "eschf_state_or_evidence_conflict") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(503, "eschf_storage_unavailable") from exc


async def _prepare_source(request: Request, user: CurrentUser, source_id: int, version: int):
    provider: SourceProvider | None = getattr(request.app.state, "eschf_source_provider", None)
    if provider is None:
        raise HTTPException(503, "eschf_source_provider_unavailable")
    try:
        prepared = await provider.prepare_source(request, user, source_id, version)
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(403, "eschf_source_access_denied") from exc
    except ValueError as exc:
        raise HTTPException(409, "eschf_source_stale_or_ineligible") from exc
    except Exception as exc:
        raise HTTPException(503, "eschf_source_provider_unavailable") from exc
    # Trusted wiring still has to return the requested source/version. A binding
    # digest proves storage integrity; it does not replace the provider's ACL or
    # native freshness check. Repository validates the full canonical contract.
    try:
        if not isinstance(prepared, PreparedSource) or not callable(prepared.recheck):
            raise ValueError("source recheck required")
        value = prepared.value
        if not isinstance(value, SnapshotInput):
            raise ValueError("unexpected provider result")
        binding = json.loads(value.binding_snapshot)
        if (
            type(binding["source_document_id"]) is not int
            or type(binding["source_document_version"]) is not int
            or binding["source_document_id"] != source_id
            or binding["source_document_version"] != version
        ):
            raise ValueError("provider source mismatch")
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(503, "eschf_source_provider_contract_mismatch") from exc
    return prepared


async def _saved_preview(repository, user, snapshot_id, state, expected=None):
    snapshot, delivery = await repository.get(user, snapshot_id)
    value = SnapshotInput(
        snapshot.number,
        snapshot.taxpayer_unp,
        snapshot.binding_snapshot,
        snapshot.unsigned_xml,
        snapshot.adapter_id,
        snapshot.environment,
    )
    if (
        delivery.state != state
        or sha256(value.binding_snapshot) != snapshot.binding_sha256
        or sha256(value.unsigned_xml) != snapshot.unsigned_sha256
        or (expected is not None and value != expected)
    ):
        raise PreviewStale("preview_stale")
    require_material_fingerprint(value)
    return value


async def _revalidate_source(request, user, persisted):
    provider = getattr(request.app.state, "eschf_source_provider", None)
    if provider is None or not callable(getattr(provider, "revalidate_source", None)):
        raise HTTPException(503, "eschf_source_provider_unavailable")
    try:
        prepared = await provider.revalidate_source(request, user, persisted)
        if (
            not isinstance(prepared, PreparedSource)
            or not callable(prepared.recheck)
            or prepared.value != persisted
        ):
            raise PreviewStale("preview_stale")
        return prepared
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(403, "eschf_source_access_denied") from exc
    except ValueError as exc:
        raise HTTPException(409, "preview_stale") from exc
    except Exception as exc:
        raise HTTPException(503, "eschf_source_provider_unavailable") from exc


async def _summary(repository: Repository, user: CurrentUser, snapshot_id: UUID) -> dict:
    snapshot, delivery = await repository.get(user, snapshot_id)
    signed = await repository.session.get(SignedArtifact, snapshot_id)
    return {
        "id": snapshot.id,
        "original_id": snapshot.original_id,
        "supersedes_id": snapshot.supersedes_id,
        "document_type": snapshot.document_type,
        "source_document_id": snapshot.source_document_id,
        "source_document_version": snapshot.source_document_version,
        "source_content_sha256": snapshot.source_content_sha256,
        "source_snapshot_sha256": snapshot.source_snapshot_sha256,
        "number": snapshot.number,
        "taxpayer_unp": snapshot.taxpayer_unp,
        "binding_sha256": snapshot.binding_sha256,
        "unsigned_sha256": snapshot.unsigned_sha256,
        "signed_sha256": signed.signed_sha256 if signed else None,
        "environment": snapshot.environment,
        "preparation_adapter_id": snapshot.adapter_id,
        "signed_adapter_id": signed.adapter_id if signed else None,
        "created_by": snapshot.created_by,
        "created_at": snapshot.created_at,
        "state": delivery.state,
        "approved_by": delivery.approved_by,
        "approved_at": delivery.approved_at,
        "approved_binding_sha256": delivery.approved_binding_sha256,
        "approved_unsigned_sha256": delivery.approved_unsigned_sha256,
        "queued_at": delivery.queued_at,
        "observation_id": delivery.observation_id,
        "portal_since": delivery.portal_since,
        "evidence_sha256": delivery.evidence_sha256,
        "unknown_reason": delivery.unknown_reason,
    }


@router.post(
    "/preparations", status_code=201, dependencies=[Depends(require_permission("eschf.prepare"))]
)
async def prepare(body: PreparationRequest, request: Request, session: Session, user: User):
    prepared = await _prepare_source(
        request, user, body.source_document_id, body.source_document_version
    )
    repository = _repository(request, session)
    async with _transaction(session):
        await prepared.recheck(session, user)
        snapshot_id = await repository.prepare(user, prepared.value)
        return await _summary(repository, user, snapshot_id)


@router.post(
    "/{snapshot_id}/refresh",
    status_code=201,
    dependencies=[Depends(require_permission("eschf.prepare"))],
)
async def refresh(
    snapshot_id: UUID, body: RefreshRequest, request: Request, session: Session, user: User
):
    repository = _repository(request, session)
    async with _transaction(session):
        snapshot, _ = await repository.get(user, snapshot_id)
        source_id = snapshot.source_document_id
    # No provider/native I/O while holding a database lock. Supersede locks and
    # rechecks current revision and absence of ANY attempt after the read gap.
    prepared = await _prepare_source(request, user, source_id, body.source_document_version)
    async with _transaction(session):
        await prepared.recheck(session, user)
        new_id = await repository.supersede(user, snapshot_id, prepared.value)
        return await _summary(repository, user, new_id)


@router.get("/{snapshot_id}")
async def get_snapshot(snapshot_id: UUID, request: Request, session: Session, user: User):
    async with _transaction(session):
        return await _summary(_repository(request, session), user, snapshot_id)


@router.get("/{snapshot_id}/xml")
async def get_xml(snapshot_id: UUID, request: Request, session: Session, user: User):
    async with _transaction(session):
        snapshot, _ = await _repository(request, session).get(user, snapshot_id)
        return Response(
            snapshot.unsigned_xml,
            media_type="application/xml",
            headers={
                "ETag": f'"{snapshot.unsigned_sha256}"',
                "Content-Disposition": f'attachment; filename="eschf-{snapshot_id}.xml"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )


@router.get("/{snapshot_id}/history")
async def get_history(snapshot_id: UUID, request: Request, session: Session, user: User):
    async with _transaction(session):
        snapshot, _ = await _repository(request, session).get(user, snapshot_id)
        decisions = (
            await session.scalars(
                select(Decision)
                .where(Decision.snapshot_id == snapshot_id)
                .order_by(Decision.at, Decision.kind)
            )
        ).all()
        attempt = await session.get(Attempt, snapshot_id)
        observations = (
            await session.scalars(
                select(Observation)
                .where(Observation.snapshot_id == snapshot_id)
                .order_by(Observation.since.desc(), Observation.id.desc())
                .limit(101)
            )
        ).all()
        return {
            "snapshot_id": snapshot_id,
            "environment": snapshot.environment,
            "decisions": [
                {
                    "kind": d.kind,
                    "actor": d.actor,
                    "at": d.at,
                    "binding_sha256": d.binding_sha256,
                    "unsigned_sha256": d.unsigned_sha256,
                    "reason": d.reason,
                }
                for d in decisions
            ],
            "attempt": {
                "claim_id": attempt.claim_id,
                "worker_id": attempt.worker_id,
                "started_at": attempt.started_at,
                "signed_sha256": attempt.signed_sha256,
            }
            if attempt
            else None,
            "observations": [
                {
                    "id": o.id,
                    "kind": o.kind,
                    "code": o.code,
                    "since": o.since,
                    "state": o.resulting_state,
                    "adapter_id": o.adapter_id,
                    "evidence_sha256": o.evidence_sha256,
                }
                for o in observations[:100]
            ],
            "has_more_observations": len(observations) > 100,
        }


@router.post("/{snapshot_id}/approval", dependencies=[Depends(require_permission("eschf.approve"))])
async def approve(
    snapshot_id: UUID, body: ApprovalRequest, request: Request, session: Session, user: User
):
    repository = _repository(request, session)
    async with _transaction(session):
        persisted = await _saved_preview(repository, user, snapshot_id, "prepared")
        if (body.binding_sha256, body.unsigned_sha256) != (
            sha256(persisted.binding_snapshot),
            sha256(persisted.unsigned_xml),
        ):
            raise PreviewStale("preview_stale")
    checked = await _revalidate_source(request, user, persisted)
    async with _transaction(session):
        await _saved_preview(repository, user, snapshot_id, "prepared", persisted)
        # Acquire the durable locks before the final source/expiry check, so a
        # wait for this snapshot cannot outlive the checked receipt unnoticed.
        await checked.recheck(session, user)
        await repository.approve(
            user,
            snapshot_id,
            binding_sha256=body.binding_sha256,
            unsigned_sha256=body.unsigned_sha256,
        )
        return await _summary(repository, user, snapshot_id)


@router.post("/{snapshot_id}/queue", dependencies=[Depends(require_permission("eschf.queue"))])
async def enqueue(
    snapshot_id: UUID, body: EmptyRequest, request: Request, session: Session, user: User
):
    repository = _repository(request, session)
    async with _transaction(session):
        persisted = await _saved_preview(repository, user, snapshot_id, "signed")
    checked = await _revalidate_source(request, user, persisted)
    async with _transaction(session):
        await _saved_preview(repository, user, snapshot_id, "signed", persisted)
        await checked.recheck(session, user)
        await repository.enqueue(user, snapshot_id)
        return await _summary(repository, user, snapshot_id)


@router.post(
    "/{snapshot_id}/recovery", dependencies=[Depends(require_permission("eschf.reconcile"))]
)
async def recover(
    snapshot_id: UUID, body: EmptyRequest, request: Request, session: Session, user: User
):
    repository = _repository(request, session)
    async with _transaction(session):
        await repository.recover_projection(user, snapshot_id)
        return await _summary(repository, user, snapshot_id)


async def _artifact(request: Request) -> bytes:
    if getattr(request.app.state, "eschf_evidence_adapter", None) is None:
        raise HTTPException(503, "eschf_evidence_adapter_unavailable")
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/octet-stream"
    ):
        raise HTTPException(415, "eschf_binary_artifact_required")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_ARTIFACT_BYTES:
            raise HTTPException(413, "eschf_artifact_too_large")
        data.extend(chunk)
    if not data:
        raise HTTPException(422, "eschf_artifact_empty")
    return bytes(data)


@router.post(
    "/{snapshot_id}/signed-artifact", dependencies=[Depends(require_permission("eschf.approve"))]
)
async def attach_signed(snapshot_id: UUID, request: Request, session: Session, user: User):
    raw = await _artifact(request)
    repository = _repository(request, session)
    async with _transaction(session):
        await repository.attach_signed(user, snapshot_id, raw)
        return await _summary(repository, user, snapshot_id)


@router.post(
    "/{snapshot_id}/observations", dependencies=[Depends(require_permission("eschf.reconcile"))]
)
async def observe(snapshot_id: UUID, request: Request, session: Session, user: User):
    raw = await _artifact(request)
    repository = _repository(request, session)
    async with _transaction(session):
        await repository.observe(user, snapshot_id, raw)
        return await _summary(repository, user, snapshot_id)
