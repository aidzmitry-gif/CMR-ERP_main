"""Trusted Sales -> mapping receipt -> G03 capture -> durable preparation bridge.

Application wiring provides all callbacks. This module does not implement native
I/O, mapping discovery or crypto. In particular onec_ref/post_document are never
used as binding evidence. A G03 LocalEnvelope retains its local-only scope.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from fastapi import HTTPException, Request
from pydantic import AwareDatetime
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.auth import CurrentUser
from integrations.onec_eschf.adapter import (
    Binding,
    Digest,
    Frozen,
    NativeCapture,
    NativeResult,
    Text,
    canonical,
    capture_local,
    sha256,
)
from modules.eschf.repository import SnapshotInput
from modules.eschf.source import SalesSourceResolver, SourcePin


@dataclass(frozen=True)
class PreparedSource:
    value: SnapshotInput
    # Mandatory server callback; called in the SAME transaction as persistence.
    recheck: Callable[[AsyncSession, CurrentUser], Awaitable[None]]


class MappingReceipt(Frozen):
    receipt_id: Text
    issuer: Text
    environment: Literal["synthetic", "native"]
    source_pin_sha256: Digest
    source_material_sha256: Digest
    binding: Binding
    issued_at: AwareDatetime
    expires_at: AwareDatetime


class MappingResolver(Protocol):
    async def resolve(self, source: SourcePin) -> bytes:
        """Fetch the exact mapping receipt for this source; no fuzzy/native guess."""
        ...


class MappingVerifier(Protocol):
    verifier_id: str

    def verify(self, raw_receipt: bytes) -> MappingReceipt:
        """Authenticate issuer, signature/provenance and parse claims, or raise.

        Verifiers come from trusted application wiring. A caller's boolean or
        evidence reference is never an implementation of this contract.
        """
        ...


@dataclass(frozen=True)
class VerifiedCapture:
    native: NativeCapture
    result: NativeResult
    xml_bytes: bytes
    codec: Literal["utf-8", "utf-8-sig"]
    byte_evidence_ref: str
    proof: bytes
    expires_at: datetime
    scope: Literal["synthetic_fixture", "native_runtime_verified", "local_envelope_only"]


class NativeCaptureProvider(Protocol):
    adapter_id: str
    environment: Literal["synthetic", "native"]

    async def capture_verified(self, source: SourcePin, mapping: MappingReceipt) -> VerifiedCapture:
        """Obtain and authenticate exact XML plus complete native dependency state.

        A future native implementation must prove atomic freshness, exact basis/
        parties, configuration and byte provenance; return bounded raw proof.
        LocalEnvelope alone never satisfies this capability. No implementation
        is supplied here. Synthetic fixtures have their own environment/scope.
        No signing, sending or production operation belongs to this callback.
        """
        ...


def _bounded(raw: bytes) -> None:
    if type(raw) is not bytes or not raw or len(raw) > 2 * 1024 * 1024:
        raise ValueError("mapping_or_capture_evidence_invalid")


def _fresh(issued_at: datetime, expires_at: datetime, now: datetime) -> None:
    if issued_at.tzinfo is None or expires_at.tzinfo is None or not issued_at <= now < expires_at:
        raise ValueError("mapping_or_capture_evidence_expired")


class PreviewStale(ValueError):
    """Refresh the preview and obtain new consent; never replace approved bytes."""


@contextmanager
def _stale_preview():
    try:
        yield
    except PreviewStale:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise PreviewStale("preview_stale") from exc
    except HTTPException as exc:
        if exc.status_code == 409:
            raise PreviewStale("preview_stale") from exc
        raise


def require_material_fingerprint(value: SnapshotInput) -> dict:
    with _stale_preview():
        data = json.loads(value.binding_snapshot)
        evidence = data["binding_evidence"]
        fingerprint = evidence["source_material_sha256"]
        if (
            type(evidence["material_schema"]) is not int
            or evidence["material_schema"] != 1
            or not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or any(c not in "0123456789abcdef" for c in fingerprint)
            or canonical(data) != value.binding_snapshot
        ):
            raise PreviewStale("preview_stale")
        return data


class SalesNativeSourceProvider:
    """Install as app.state.eschf_source_provider from trusted startup wiring.

    Mapping resolver, receipt verifier and capture provider are all explicit;
    the default constructor is unwired and responds with 503. Future native
    capture proof must establish full dependency freshness: its expiry alone
    is never evidence that the native state was read atomically or is current.
    """

    def __init__(
        self,
        *,
        mapping_resolver: MappingResolver | None = None,
        mapping_verifier: MappingVerifier | None = None,
        capture_provider: NativeCaptureProvider | None = None,
    ) -> None:
        self.mapping_resolver = mapping_resolver
        self.mapping_verifier = mapping_verifier
        self.capture_provider = capture_provider
        self.source_resolver = SalesSourceResolver()

    async def prepare_source(
        self,
        request: Request,
        user: CurrentUser,
        source_document_id: int,
        source_document_version: int,
    ) -> PreparedSource:
        if (
            self.mapping_resolver is None
            or self.mapping_verifier is None
            or self.capture_provider is None
        ):
            raise HTTPException(503, "eschf_native_bridge_unavailable")
        factory = request.app.state.core.services.db.session_factory
        async with factory() as session, session.begin():
            pin = await self.source_resolver.load(
                session, request, user, source_document_id, source_document_version
            )
        # Closed read transaction: every callback/native I/O runs without source
        # locks or a live source DB transaction. Only final recheck acquires locks.
        raw = await self.mapping_resolver.resolve(pin)
        _bounded(raw)
        mapping = self.mapping_verifier.verify(raw)
        if (
            not isinstance(mapping, MappingReceipt)
            or mapping.source_pin_sha256 != pin.digest
            or mapping.source_material_sha256 != pin.material_digest
        ):
            raise ValueError("mapping_receipt_source_mismatch")
        mapping = mapping.model_copy(deep=True)
        _fresh(mapping.issued_at, mapping.expires_at, datetime.now(UTC))
        capture = await self.capture_provider.capture_verified(pin, mapping.model_copy(deep=True))
        if not isinstance(capture, VerifiedCapture):
            raise ValueError("verified_capture_required")
        expected_scope = {"synthetic": "synthetic_fixture", "native": "native_runtime_verified"}
        if (
            mapping.environment != self.capture_provider.environment
            or capture.scope != expected_scope.get(mapping.environment)
        ):
            raise ValueError("native_runtime_evidence_unproven")
        _bounded(capture.proof)
        if (
            type(capture.xml_bytes) is not bytes
            or not 0 < len(capture.xml_bytes) <= 16 * 1024 * 1024
        ):
            raise ValueError("native_xml_size_invalid")
        _fresh(mapping.issued_at, capture.expires_at, datetime.now(UTC))
        if (
            not self.capture_provider.adapter_id.strip()
            or not self.mapping_verifier.verifier_id.strip()
        ):
            raise ValueError("adapter_provenance_required")
        envelope = capture_local(
            pin.source,
            mapping.binding,
            capture.native,
            capture.result,
            capture.xml_bytes,
            codec=capture.codec,
            byte_evidence_ref=capture.byte_evidence_ref,
        )
        # The durable binding stores both the unpromoted local envelope and the
        # independently authenticated receipt/proof. Exact original bytes survive.
        binding = mapping.binding
        value = SnapshotInput(
            number=envelope.number,
            taxpayer_unp=envelope.number.split("-", 1)[0],
            unsigned_xml=envelope.xml_bytes,
            adapter_id=self.capture_provider.adapter_id,
            environment=mapping.environment,
            binding_snapshot=canonical(
                {
                    "source_document_id": binding.source_document_id,
                    "source_document_version": binding.source_document_version,
                    "source_content_sha256": binding.source_content_sha256,
                    "source_snapshot_sha256": binding.source_snapshot_sha256,
                    "provider_identity": binding.provider.model_dump(mode="json"),
                    "recipient_selection": binding.recipient_selection.model_dump(mode="json"),
                    "native_information_base_id": binding.invoice.information_base_id,
                    "native_metadata_object": binding.invoice.metadata_object,
                    "native_invoice_uuid": binding.invoice.reference,
                    "basis_reference": binding.basis.reference,
                    "native_version_evidence": {
                        "scope": capture.scope,
                        "native_capture_sha256": binding.native_capture_sha256,
                        "proof_sha256": sha256(capture.proof),
                        "proof_base64": base64.b64encode(capture.proof).decode("ascii"),
                        "expires_at": capture.expires_at.isoformat(),
                    },
                    "binding_evidence": {
                        "receipt_id": mapping.receipt_id,
                        "issuer": mapping.issuer,
                        "verifier_id": self.mapping_verifier.verifier_id,
                        "raw_sha256": sha256(raw),
                        "raw_base64": base64.b64encode(raw).decode("ascii"),
                        "source_pin_sha256": pin.digest,
                        "material_schema": 1,
                        "source_material_sha256": pin.material_digest,
                        "expires_at": mapping.expires_at.isoformat(),
                    },
                    "prepared_xml_sha256": envelope.xml_sha256,
                    "full_projection": json.loads(envelope.snapshot),
                }
            ),
        )
        expires_at = min(mapping.expires_at, capture.expires_at)

        async def recheck(session: AsyncSession, current_user: CurrentUser) -> None:
            _fresh(mapping.issued_at, expires_at, datetime.now(UTC))
            await self.source_resolver.recheck(session, request, current_user, pin)
            _fresh(mapping.issued_at, expires_at, datetime.now(UTC))

        return PreparedSource(value, recheck)

    async def revalidate_source(
        self,
        request: Request,
        user: CurrentUser,
        persisted: SnapshotInput,
    ) -> PreparedSource:
        """Check the saved preview against fresh source/mapping/capture, without writes.

        The original receipt must still be valid. A newly issued receipt cannot
        silently extend its lifetime. Fresh actor/access pins and proof timestamps
        may differ; the complete G03 envelope and exact XML must remain identical.
        """
        saved = require_material_fingerprint(persisted)
        if (
            self.mapping_resolver is None
            or self.mapping_verifier is None
            or self.capture_provider is None
        ):
            raise HTTPException(503, "eschf_native_bridge_unavailable")
        with _stale_preview():
            evidence = saved["binding_evidence"]
            raw = base64.b64decode(evidence["raw_base64"], validate=True)
            _bounded(raw)
            if (
                sha256(raw) != evidence["raw_sha256"]
                or self.mapping_verifier.verifier_id != evidence["verifier_id"]
            ):
                raise PreviewStale("preview_stale")
            original = self.mapping_verifier.verify(raw)
            if (
                not isinstance(original, MappingReceipt)
                or original.environment != persisted.environment
                or original.source_material_sha256 != evidence["source_material_sha256"]
                or original.source_pin_sha256 != evidence["source_pin_sha256"]
                or original.receipt_id != evidence["receipt_id"]
                or original.issuer != evidence["issuer"]
                or original.binding.model_dump(mode="json") != saved["full_projection"]["binding"]
                or original.expires_at.isoformat() != evidence["expires_at"]
            ):
                raise PreviewStale("preview_stale")
            proof = saved["native_version_evidence"]
            raw_proof = base64.b64decode(proof["proof_base64"], validate=True)
            _bounded(raw_proof)
            if sha256(raw_proof) != proof["proof_sha256"]:
                raise PreviewStale("preview_stale")
            original_deadline = min(
                original.expires_at, datetime.fromisoformat(proof["expires_at"])
            )
            _fresh(original.issued_at, original_deadline, datetime.now(UTC))
            # Reuse the real source ACL, receipt verifier and capture validation.
            # prepare_source returns an in-memory candidate only; it writes no DB.
            current = await self.prepare_source(
                request, user, saved["source_document_id"], saved["source_document_version"]
            )
            fresh = require_material_fingerprint(current.value)

            # Evidence issuance timestamps/full access pins are checked separately.
            # Every persisted material field, including full source/native/binding,
            # is compared exactly; neither signed nor unsigned bytes are replaced.
            def material(data):
                return {
                    k: v
                    for k, v in data.items()
                    if k not in {"binding_evidence", "native_version_evidence"}
                }

            if (
                material(fresh) != material(saved)
                or fresh["binding_evidence"]["source_material_sha256"]
                != evidence["source_material_sha256"]
                or fresh["binding_evidence"]["issuer"] != evidence["issuer"]
                or fresh["native_version_evidence"]["scope"] != proof["scope"]
                or fresh["native_version_evidence"]["native_capture_sha256"]
                != proof["native_capture_sha256"]
                or current.value.unsigned_xml != persisted.unsigned_xml
                or current.value.adapter_id != persisted.adapter_id
                or current.value.environment != persisted.environment
                or current.value.number != persisted.number
                or current.value.taxpayer_unp != persisted.taxpayer_unp
                or sha256(persisted.unsigned_xml) != saved["prepared_xml_sha256"]
            ):
                raise PreviewStale("preview_stale")

        async def recheck(session: AsyncSession, current_user: CurrentUser) -> None:
            with _stale_preview():
                _fresh(original.issued_at, original_deadline, datetime.now(UTC))
                await current.recheck(session, current_user)
                _fresh(original.issued_at, original_deadline, datetime.now(UTC))

        return PreparedSource(persisted, recheck)
