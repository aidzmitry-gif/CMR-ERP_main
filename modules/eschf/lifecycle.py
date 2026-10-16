"""Offline delivery policy. No transport, signer, queue or automatic resend.

Evidence must come from a future authenticated adapter that verifies portal ECP.
An HTTP response / 1C posted=True / SMTP receipt must never populate this object.
"""

import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

PORTAL_STATES = {
    "COMPLETED": "issued",
    "COMPLETED_SIGNED": "recipient_signed",
    "ON_AGREEMENT": "agreement_pending",
    "CANCELLED": "cancelled",
    "ON_AGREEMENT_CANCEL": "cancellation_pending",
    "IN_PROGRESS": "portal_processing",
    "NOT_FOUND": "reconciliation_required",  # Also means insufficient access, SDK appendix 2.
    "ERROR": "portal_error",
}


@dataclass(frozen=True)
class Delivery:
    number: str
    taxpayer_unp: str
    signed_sha256: str
    state: str = "signed"
    portal_since: datetime | None = None
    evidence_sha256: str | None = None


@dataclass(frozen=True)
class PortalEvidence:
    number: str
    taxpayer_unp: str
    signed_sha256: str
    kind: Literal["receipt", "status"]
    code: str
    since: datetime
    evidence_sha256: str
    signature_verified: bool


def begin_attempt(delivery: Delivery) -> Delivery:
    if delivery.state != "signed":
        raise ValueError("automatic repeat is forbidden; reconcile the previous attempt")
    return replace(delivery, state="in_flight")


def uncertain(delivery: Delivery) -> Delivery:
    if delivery.state != "in_flight":
        raise ValueError("no active attempt")
    return replace(delivery, state="delivery_unknown")


def observe(delivery: Delivery, evidence: PortalEvidence) -> Delivery:
    if evidence.signature_verified is not True:
        raise ValueError("portal signature has not been verified")
    if (delivery.number, delivery.taxpayer_unp, delivery.signed_sha256) != (
            evidence.number, evidence.taxpayer_unp, evidence.signed_sha256):
        raise ValueError("evidence is for another signed document")
    if evidence.since.tzinfo is None:
        raise ValueError("timezone is required")
    if not re.fullmatch(r"[0-9a-f]{64}", evidence.evidence_sha256):
        raise ValueError("evidence artifact hash is required")
    if delivery.state == "signed":
        raise ValueError("there was no delivery attempt")
    if delivery.evidence_sha256 == evidence.evidence_sha256:
        return delivery
    if delivery.portal_since and evidence.since <= delivery.portal_since:
        raise ValueError("stale/conflicting portal evidence; reconcile")
    if evidence.kind == "receipt":
        if delivery.state not in {"in_flight", "delivery_unknown"}:
            raise ValueError("late receipt cannot replace an observed portal status")
        if evidence.code not in {"ACCEPTED", "REJECTED"}:
            raise ValueError("unknown receipt result")
        state = "portal_processing" if evidence.code == "ACCEPTED" else "precheck_rejected"
    elif evidence.kind == "status":
        state = PORTAL_STATES.get(evidence.code, "reconciliation_required")
        # Terminal/regressive observations require review; never silently downgrade.
        allowed = {
            "issued": {"issued", "recipient_signed", "cancellation_pending", "cancelled"},
            "recipient_signed": {"recipient_signed", "cancellation_pending", "cancelled"},
            "cancelled": {"cancelled"},
        }
        if delivery.state in allowed and state not in allowed[delivery.state]:
            raise ValueError("portal status regression; reconcile")
    else:
        raise ValueError("unsupported evidence type")
    return replace(delivery, state=state, portal_since=evidence.since,
                   evidence_sha256=evidence.evidence_sha256)
