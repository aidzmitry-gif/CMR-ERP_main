"""Explicit branch identity; transaction boundaries belong to the caller."""
from copy import deepcopy
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import (
    AuditLog,
    Contact,
    Counterparty,
    CounterpartyBranch,
    CounterpartyBranchAlias,
)
from core.services.mdm import CounterpartyContactPatch, CounterpartyWriteError, _contact_dict


class BranchPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    address: str | None = Field(default=None, max_length=1000)
    tax_mode: Literal["unknown", "shared", "independent"] | None = None
    portal_branch_code: str | None = Field(default=None, pattern=r"^[0-9]{4}$")
    is_active: bool | None = None

    @field_validator("name", "address", mode="before")
    @classmethod
    def strip_text(cls, value):
        if isinstance(value, str):
            value.encode("utf-8")
            if any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError("Недопустимый управляющий символ")
            return value.strip()
        return value

    @field_validator("name", "tax_mode", "is_active")
    @classmethod
    def nonnull_if_supplied(cls, value):
        if value is None:
            raise ValueError("Поле не может быть пустым")
        return value


class BranchWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_legal_entity_revision: int = Field(ge=1)
    expected_revision: int | None = Field(default=None, ge=1)
    manual: BranchPatch
    contacts: list[CounterpartyContactPatch] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def distinct_contacts(self):
        ids = [c.id for c in self.contacts if c.id is not None]
        if len(ids) != len(set(ids)) or sum(c.is_primary is True for c in self.contacts) > 1:
            raise ValueError("Контакты не должны повторяться; основной контакт может быть только один")
        return self


def branch_dict(branch: CounterpartyBranch) -> dict:
    return {field: deepcopy(getattr(branch, field)) for field in (
        "id", "legal_entity_id", "name", "address", "tax_mode", "portal_branch_code",
        "is_active", "provenance", "revision",
    )}


async def branches_for_parent(session: AsyncSession, legal_entity_id: int) -> dict:
    parent = await session.get(Counterparty, legal_entity_id)
    if parent is None:
        raise CounterpartyWriteError("not_found", "Головное предприятие не найдено", 404)
    branches = (await session.scalars(select(CounterpartyBranch).where(
        CounterpartyBranch.legal_entity_id == legal_entity_id,
    ).order_by(CounterpartyBranch.name, CounterpartyBranch.id))).all()
    contacts = (await session.scalars(select(Contact).where(
        Contact.counterparty_id == legal_entity_id, Contact.branch_id.is_not(None),
    ).order_by(Contact.is_primary.desc(), Contact.id))).all()
    by_branch: dict[int, list[dict]] = {}
    for contact in contacts:
        by_branch.setdefault(contact.branch_id, []).append(_contact_dict(contact))
    return {
        "legal_entity": {"id": parent.id, "name": parent.display_name or parent.name,
                         "legal_name": parent.legal_name, "unp": parent.unp,
                         "revision": parent.revision, "is_active": parent.is_active},
        "branches": [{**branch_dict(branch), "contacts": by_branch.get(branch.id, [])} for branch in branches],
    }


async def save_branch(session: AsyncSession, legal_entity_id: int, branch_id: int | None,
                      payload: BranchWrite, *, actor: str) -> CounterpartyBranch:
    if (branch_id is None) != (payload.expected_revision is None):
        raise CounterpartyWriteError("revision_required", "Для изменения нужна версия филиала; для создания она не передаётся", 422)
    # Parent first is the common ordering for create, patch, import and parent merge.
    parent = (await session.scalars(select(Counterparty).where(
        Counterparty.id == legal_entity_id,
    ).with_for_update().execution_options(populate_existing=True))).one_or_none()
    if parent is None:
        raise CounterpartyWriteError("not_found", "Головное предприятие не найдено", 404)
    if not parent.is_active or parent.merged_into_id is not None:
        raise CounterpartyWriteError("parent_archived", "Головное предприятие архивировано или объединено")
    if parent.revision != payload.expected_legal_entity_revision:
        raise CounterpartyWriteError("stale_parent_revision", "Головное предприятие изменено. Обновите карточку")
    if (not parent.unp or len(parent.unp) != 9 or not parent.unp.isascii()
            or not parent.unp.isdigit() or not (parent.legal_name or "").strip()):
        raise CounterpartyWriteError("parent_identity_required", "Сначала подтвердите УНП и юридическое наименование головного предприятия", 422)
    branch = None
    if branch_id is not None:
        branch = (await session.scalars(select(CounterpartyBranch).where(
            CounterpartyBranch.id == branch_id, CounterpartyBranch.legal_entity_id == legal_entity_id,
        ).with_for_update().execution_options(populate_existing=True))).one_or_none()
        if branch is None:
            raise CounterpartyWriteError("branch_not_found", "Филиал не найден у выбранного головного предприятия", 404)
        if branch.revision != payload.expected_revision:
            raise CounterpartyWriteError("stale_revision", "Филиал изменён. Обновите карточку")
    fields = payload.manual.model_dump(exclude_unset=True)
    before = branch_dict(branch) if branch else None
    contacts = list(await session.scalars(select(Contact).where(
        Contact.counterparty_id == legal_entity_id, Contact.branch_id == branch_id,
    ).order_by(Contact.id))) if branch else []
    by_id = {c.id: c for c in contacts}
    if any(c.id is not None and c.id not in by_id for c in payload.contacts):
        raise CounterpartyWriteError("contact_not_owned", "Контакт не принадлежит выбранному филиалу", 422)
    if before is not None:
        before["contacts"] = [_contact_dict(c) for c in contacts]
    if branch is None:
        if not fields.get("name"):
            raise CounterpartyWriteError("name_required", "Нужно наименование филиала", 422)
        branch = CounterpartyBranch(legal_entity_id=legal_entity_id, name=fields["name"],
                                    tax_mode="unknown", is_active=True, provenance={})
        session.add(branch)
    now = datetime.now(UTC).isoformat()
    provenance = deepcopy(branch.provenance or {})
    for key, value in fields.items():
        if getattr(branch, key) != value or key not in provenance:
            setattr(branch, key, value)
            provenance[key] = {"source": "manual", "at": now}
    branch.provenance = provenance
    await session.flush()
    contacts_changed = False
    for patch in payload.contacts:
        contact = by_id.get(patch.id) if patch.id is not None else None
        if contact is None:
            contact = Contact(counterparty_id=legal_entity_id, branch_id=branch.id,
                              full_name=patch.full_name, is_primary=False)
            session.add(contact)
            contacts.append(contact)
            contacts_changed = True
        if patch.is_primary:
            for other in contacts:
                if other is not contact and other.is_primary:
                    other.is_primary = False
                    contacts_changed = True
        for key, value in patch.model_dump(exclude_unset=True, exclude={"id"}).items():
            if getattr(contact, key) != value:
                setattr(contact, key, value)
                contacts_changed = True
    if contacts_changed:
        branch.provenance = {**branch.provenance, "contacts": {"source": "manual", "at": now}}
    await session.flush()
    after = branch_dict(branch)
    after["contacts"] = [_contact_dict(c) for c in contacts]
    if before != after:
        session.add(AuditLog(actor=actor, action="counterparty.branch.created" if before is None else "counterparty.branch.updated",
                            entity_ref=f"counterparty:{legal_entity_id}",
                            detail={"branch_id": branch.id, "before": before, "after": after}))
    return branch


async def branch_for_external_ref(session: AsyncSession, *, source: str, external_ref: str,
                                  legal_entity_id: int) -> CounterpartyBranch | None:
    """Read-only resolver: never fall back to name, UNP or a first candidate."""
    branch = (await session.scalars(select(CounterpartyBranch).join(
        CounterpartyBranchAlias, CounterpartyBranchAlias.branch_id == CounterpartyBranch.id,
    ).where(CounterpartyBranchAlias.source == source,
            CounterpartyBranchAlias.external_ref == external_ref))).one_or_none()
    if branch and (branch.legal_entity_id != legal_entity_id or not branch.is_active):
        raise CounterpartyWriteError("branch_identity_conflict", "Внешний ID связан с другим или архивным филиалом")
    return branch
