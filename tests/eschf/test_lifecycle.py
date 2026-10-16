from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from modules.eschf.lifecycle import (
    PORTAL_STATES,
    Delivery,
    PortalEvidence,
    begin_attempt,
    observe,
    uncertain,
)


def delivery():
    return Delivery("100000000-2026-0000000001", "100000000", "a" * 64)


def evidence(kind="receipt", code="ACCEPTED", **changes):
    base = PortalEvidence(delivery().number, "100000000", "a" * 64, kind, code,
                          datetime(2026, 9, 9, tzinfo=timezone.utc), "b" * 64, True)
    return replace(base, **changes)


def test_receipt_is_not_issuance_and_late_receipt_cannot_regress_status():
    state = observe(begin_attempt(delivery()), evidence())
    assert state.state == "portal_processing"
    status = evidence("status", "COMPLETED", since=evidence().since + timedelta(hours=3),
                      evidence_sha256="c" * 64)
    state = observe(state, status)
    assert state.state == "issued"
    assert observe(state, status) == state
    with pytest.raises(ValueError, match="late receipt"):
        observe(state, evidence(since=status.since + timedelta(seconds=1)))


@pytest.mark.parametrize("code,expected", [*PORTAL_STATES.items(), ("NEW_STATUS", "reconciliation_required")])
def test_status_mapping(code, expected):
    assert observe(begin_attempt(delivery()), evidence("status", code)).state == expected


def test_unknown_delivery_and_not_found_never_allow_automatic_repeat():
    state = uncertain(begin_attempt(delivery()))
    with pytest.raises(ValueError, match="repeat"):
        begin_attempt(state)
    state = observe(state, evidence("status", "NOT_FOUND"))
    assert state.state == "reconciliation_required"
    with pytest.raises(ValueError, match="repeat"):
        begin_attempt(state)


@pytest.mark.parametrize("changes", [
    {"signature_verified": False}, {"signature_verified": "true"}, {"taxpayer_unp": "200000000"},
    {"number": "other"}, {"signed_sha256": "d" * 64}, {"evidence_sha256": "z" * 64},
    {"since": datetime(2026, 9, 9)}, {"kind": "smtp"},
])
def test_unverified_or_unrelated_evidence_is_rejected(changes):
    with pytest.raises(ValueError):
        observe(begin_attempt(delivery()), evidence(**changes))


def test_stale_evidence_cancellation_and_unknown_results():
    state = observe(begin_attempt(delivery()), evidence("status", "COMPLETED_SIGNED"))
    with pytest.raises(ValueError, match="stale"):
        observe(state, evidence("status", "COMPLETED", evidence_sha256="c" * 64))
    with pytest.raises(ValueError, match="regression"):
        observe(state, evidence("status", "IN_PROGRESS", evidence_sha256="c" * 64,
                                since=evidence().since + timedelta(hours=1)))
    with pytest.raises(ValueError, match="no delivery"):
        observe(delivery(), evidence())
    with pytest.raises(ValueError, match="unknown receipt"):
        observe(begin_attempt(delivery()), evidence(code="OK"))
    assert observe(begin_attempt(delivery()), evidence(code="REJECTED")).state == "precheck_rejected"
    with pytest.raises(ValueError, match="no active"):
        uncertain(delivery())
