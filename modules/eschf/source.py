"""Read an authorized immutable Sales original and pin its current party state.

No recapture, native lookup, alias/name matching or post_document is performed.
Final recheck uses PostgreSQL NOWAIT share locks held by the caller transaction;
native I/O must finish before this short critical section.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import Counterparty, CounterpartyBranch, User
from core.services.auth import CurrentUser, has_permission, resolve_effective_oidc_user
from integrations.onec_eschf.adapter import Selection, SourceOriginal, canonical, sha256
from modules.sales.access import get_deal_access, visible_deal_or_404
from modules.sales.documents import original
from modules.sales.models import Deal, DealDocument


@dataclass(frozen=True)
class SourcePin:
    """Detached canonical bytes: a provider cannot mutate the loaded ORM source."""

    data: bytes

    @property
    def digest(self) -> str:
        return sha256(self.data)

    @property
    def material_digest(self) -> str:
        # An independent authorized approver may have a different identity/scope.
        # Those facts remain in digest for the final check of EACH operation.
        material = json.loads(self.data)
        for key in ("actor", "access", "owner_id"):
            material.pop(key)
        return sha256(canonical({"schema": 1, "material": material}))

    @property
    def source(self) -> SourceOriginal:
        return SourceOriginal.model_validate(json.loads(self.data)["source"])

    @property
    def selection(self) -> Selection:
        return Selection.model_validate(json.loads(self.data)["selection"])


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise ValueError(code)


async def _one(session: AsyncSession, model, criterion, lock: bool):
    statement = select(model).where(criterion).execution_options(populate_existing=True)
    if lock:
        statement = statement.with_for_update(read=True, nowait=True)
    return (await session.scalars(statement)).one_or_none()


class SalesSourceResolver:
    async def load(
        self,
        session: AsyncSession,
        request: Request,
        user: CurrentUser,
        document_id: int,
        version: int,
        *,
        lock: bool = False,
    ) -> SourcePin:
        core = request.app.state.core
        if not has_permission(core, user, "sales.deal.read"):
            raise PermissionError("sales.deal.read required for source")
        _require(
            type(document_id) is int and document_id > 0 and type(version) is int and version > 0,
            "source_identity_invalid",
        )
        if lock:
            _require(
                session.in_transaction() and session.bind.dialect.name == "postgresql",
                "source_recheck_requires_postgresql_transaction",
            )

        # Lock the live access row too: disabling/scope-changing a user between
        # native preparation and commit must not preserve an earlier decision.
        identity = (
            User.keycloak_user_id == user.keycloak_user_id
            if user.keycloak_user_id
            else User.username == user.username
        )
        member = await _one(session, User, identity, lock)
        if member is not None and (
            member.status != "active" or (user.keycloak_user_id and member.role not in user.roles)
        ):
            raise PermissionError("current source account denied")
        if user.keycloak_user_id:
            # Reuse the owner's revocation/restricted-role rules, including the
            # current invitation/audit facts, rather than trusting an old token.
            user = await resolve_effective_oidc_user(user, session)
            if not has_permission(core, user, "sales.deal.read"):
                raise PermissionError("current source permission denied")
        access = await get_deal_access(request, session, user)
        doc = await _one(session, DealDocument, DealDocument.id == document_id, False)
        if doc is None:
            raise HTTPException(404, "source_document_not_found")
        # Sales issues/replaces documents under the Deal lock. Use the same
        # order, but SELECT FOR SHARE rather than Sales' mutating no-op UPDATE.
        await _one(session, Deal, Deal.id == doc.deal_id, lock)
        deal = await visible_deal_or_404(session, doc.deal_id, access)
        if lock:
            doc = await _one(session, DealDocument, DealDocument.id == document_id, True)
        _require(doc is not None and doc.deal_id == deal.id, "source_deal_changed")
        _require(doc.kind == "invoice" and doc.version == version, "source_version_or_kind_changed")
        _require(
            doc.superseded_by_id is None and doc.cancelled_at is None and doc.status != "cancelled",
            "source_not_current",
        )
        html = original(doc, issued_only=True)
        snapshot = doc.snapshot_json
        _require(
            snapshot.get("kind") == doc.kind
            and type(snapshot.get("deal_id")) is int
            and snapshot["deal_id"] == doc.deal_id
            and snapshot.get("number") == doc.number,
            "source_snapshot_document_mismatch",
        )
        _require(
            snapshot.get("document_id") == document_id
            and type(snapshot.get("document_id")) is int
            and snapshot.get("version") == version
            and type(snapshot.get("version")) is int,
            "source_snapshot_identity_mismatch",
        )
        _require(
            type(snapshot.get("schema_version")) is int and snapshot["schema_version"] == 1,
            "source_schema_unproven",
        )
        if snapshot.get("issuance_mode") == "erp_issuance_v1":
            from modules.sales.invoice_issuance import verified_receipt
            organization_id = snapshot.get("organization_id")
            _require(type(organization_id) is int and organization_id > 0,
                     "source_organization_unproven")
            await core.services.accounting.source_member(session, organization_id, user)
            await verified_receipt(session, doc, organization_id)
        party = snapshot.get("party")
        _require(
            isinstance(party, dict) and party.get("identity_status") == "selected",
            "source_party_unproven",
        )
        selected = {key: party.get(key) for key in Selection.model_fields}
        if all(
            selected[key] is None for key in Selection.model_fields if key.startswith("branch_")
        ):
            selected["branch_tax_mode"] = "head"
        selection = Selection.model_validate(selected)
        cp = await _one(session, Counterparty, Counterparty.id == selection.legal_entity_id, lock)
        _require(
            cp is not None and cp.is_active and cp.merged_into_id is None,
            "source_party_unavailable",
        )
        _require(
            cp.revision == selection.legal_entity_revision
            and cp.legal_name == party.get("legal_name")
            and cp.unp == party.get("legal_entity_unp"),
            "source_party_changed",
        )
        _require(
            isinstance(cp.legal_name, str)
            and bool(cp.legal_name.strip())
            and isinstance(cp.unp, str)
            and bool(cp.unp.strip()),
            "source_official_party_unproven",
        )
        branch = None
        if selection.branch_id is not None:
            branch = await _one(
                session, CounterpartyBranch, CounterpartyBranch.id == selection.branch_id, lock
            )
            _require(
                branch is not None and branch.is_active and branch.legal_entity_id == cp.id,
                "source_branch_unavailable",
            )
            _require(
                branch.revision == selection.branch_revision
                and branch.tax_mode == selection.branch_tax_mode
                and branch.portal_branch_code == selection.portal_branch_code
                and branch.name == party.get("branch_name")
                and branch.address == party.get("branch_address"),
                "source_branch_changed",
            )
        source = SourceOriginal(
            document_id=doc.id,
            version=doc.version,
            content_sha256=doc.content_sha256,
            snapshot=snapshot,
            original_html=html,
            issued=True,
            superseded=False,
        )

        # Capture whole current records as an additional final recheck, including
        # requisites/provenance changed by a SQL writer without incrementing rev.
        def state(row):
            return (
                {column.name: getattr(row, column.name) for column in row.__table__.columns}
                if row is not None
                else None
            )

        return SourcePin(
            canonical(
                {
                    "source": source.model_dump(mode="json"),
                    "selection": selection.model_dump(mode="json"),
                    "actor": user.keycloak_user_id or user.username,
                    "access": {
                        "visibility": access.visibility,
                        "employee_id": access.employee_id,
                        "member_id": member.id if member else None,
                        "role": member.role if member else None,
                    },
                    "deal_id": deal.id,
                    "owner_id": deal.owner_id,
                    "counterparty": state(cp),
                    "branch": state(branch),
                }
            )
        )

    async def recheck(
        self,
        session: AsyncSession,
        request: Request,
        user: CurrentUser,
        pin: SourcePin,
    ) -> None:
        source = pin.source
        current = await self.load(
            session, request, user, source.document_id, source.version, lock=True
        )
        _require(current.data == pin.data, "source_changed_during_preparation")
