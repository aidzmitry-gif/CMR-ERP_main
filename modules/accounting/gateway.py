from fastapi import HTTPException
from sqlalchemy import select

from config.access import is_package_allowed
from modules.accounting.models import AccessGrant, Organization, Period, SourceControl
from modules.accounting.routes import organization_role, serialize, subject
from modules.accounting.service import lock_organization


class AccountingService:
    def __init__(self, services=None):
        # Resolve at call time: procurement may register after accounting.
        self.services = services

    async def additional_expense_status(self, session, organization_id, user, expense_id):
        from modules.accounting.models import Entry, LateCostReceipt

        await self.source_member(session, organization_id, user)
        saved = await session.scalar(select(LateCostReceipt).where(LateCostReceipt.organization_id == organization_id,
            LateCostReceipt.expense_id == expense_id))
        if saved is None:
            return None
        entry = await session.get(Entry, saved.entry_id)
        if (entry is None or entry.organization_id != organization_id or entry.digest != saved.digest
            or entry.source != f"procurement:additional-expense:{expense_id}" or entry.source_version != saved.source_version):
            raise HTTPException(409, "Additional expense posting identity is inconsistent")
        return {"entry_id": entry.id, "version": saved.source_version, "digest": saved.digest,
                **({"command_version": 2} if saved.command.get("command_version") == 2 else {})}

    async def physical_shipment_preview(self, session, organization_id, user, receipt, document):
        from pydantic import ValidationError

        from modules.accounting import service, shipment_preview

        if not is_package_allowed("accounting", user.roles):
            raise HTTPException(403, "Accounting module access required")
        actor = await self.source_member(session, organization_id, user)
        role = await session.scalar(select(AccessGrant.role).where(
            AccessGrant.organization_id == organization_id, AccessGrant.subject == actor,
        ))
        if role not in {"accountant", "chief"}:
            raise HTTPException(403, "Accounting write access required")
        try:
            data = shipment_preview.ShipmentPlanInput.model_validate(document)
            return await shipment_preview.prepare(session, organization_id, receipt, data,
                procurement=getattr(self.services, "procurement_source", None))
        except (ValidationError, service.AccountingError) as exc:
            raise HTTPException(422, str(exc)) from exc

    async def invoice_fulfillment_snapshot(self, session, organization_id, user, document_id):
        from modules.accounting.invoice_fulfillment import snapshot

        await self.source_member(session, organization_id, user)
        return await snapshot(session, organization_id, document_id)

    async def invoice_seller(self, session, organization_id, user, on, currency):
        from modules.accounting import seller_profiles
        await self.source_member(session, organization_id, user)
        return await seller_profiles.current(session, organization_id, on, currency)

    async def lock_event_organization(self, session, organization_id):
        if type(organization_id) is not int or organization_id <= 0:
            raise ValueError("An exact positive source organization is required")
        await lock_organization(session, organization_id)

    async def invoice_bank_basis(self, session, organization_id, user, document_id):
        """Discover exact-invoice bank evidence, including unallocated/corrected entries.

        Caller already holds organization -> deal -> invoice locks. Reacquiring
        the same org lock is safe; never commit here. This is local ledger scope,
        not a claim that all historical bank statements have been imported.
        """
        from modules.accounting.models import Entry, Line

        await self.source_member(session, organization_id, user)
        target = f"sales:document:{document_id}"
        ids = (await session.scalars(select(Entry.id).join(Line, Line.entry_id == Entry.id)
            .where(Entry.organization_id == organization_id,
                   ((Entry.operation == "bank_settlement") | Entry.id.in_(
                       select(Line.entry_id).where(Line.cash.is_(True)))),
                   Line.dimensions["settlement_document"].as_string() == target)
            .distinct().order_by(Entry.id))).all()
        entries = []
        seen = set()
        pending = list(ids)
        while pending:
            batch = [key for key in pending if key not in seen]
            if not batch:
                break
            current = (await session.scalars(select(Entry).where(
                Entry.organization_id == organization_id, Entry.id.in_(batch),
            ).order_by(Entry.id))).all()
            entries.extend(current)
            seen.update(entry.id for entry in current)
            pending = (await session.scalars(select(Entry.id).where(
                Entry.organization_id == organization_id, Entry.correction_of.in_(batch),
            ).order_by(Entry.id))).all()
        result = []
        for entry in sorted(entries, key=lambda entry: entry.id):
            item = {"entry_id": entry.id, "digest": entry.digest,
                    "correction_of": entry.correction_of, "fact": None, "blockers": []}
            try:
                item["fact"] = await self.bank_settlement(session, organization_id, user, entry.id)
                if item["fact"]["settlement_dimensions"].get("settlement_document") != target:
                    item["fact"] = None
                    item["blockers"] = ["bank_invoice_mismatch"]
            except HTTPException as exc:
                if exc.status_code not in {404, 409}:
                    raise
                item["blockers"] = ["bank_evidence_invalid"]
            result.append(item)
        return {"organization_id": organization_id, "document_id": document_id, "entries": result}

    async def bank_settlement(self, session, organization_id, user, entry_id):
        from modules.accounting.models import Entry, Line

        await self.source_member(session, organization_id, user)
        entry = await session.scalar(select(Entry).where(
            Entry.id == entry_id, Entry.organization_id == organization_id,
        ))
        if entry is None:
            raise HTTPException(404, "Bank entry not found in this organization")
        corrected = await session.scalar(select(Entry.id).where(Entry.correction_of == entry.id).limit(1))
        if entry.operation != "bank_settlement" or entry.rule_version != "bank-byn-v1" or entry.opening or entry.correction_of or corrected:
            raise HTTPException(409, "An uncorrected posted bank settlement is required")
        lines = (await session.scalars(select(Line).where(Line.entry_id == entry.id))).all()
        cash = [line for line in lines if line.cash]
        other = [line for line in lines if not line.cash]
        if (len(lines) != 2 or len(cash) != 1 or len(other) != 1
                or cash[0].currency != "BYN" or other[0].currency != "BYN"
                or cash[0].amount <= 0 or cash[0].amount != other[0].amount
                or cash[0].side == other[0].side or not cash[0].dimensions.get("bank_statement")
                or other[0].category not in {"asset", "liability"}):
            raise HTTPException(409, "Bank entry does not contain supported settlement evidence")
        return {"entry_id": entry.id, "digest": entry.digest, "amount": str(cash[0].amount),
                "direction": "receipt" if cash[0].side == "debit" else "refund",
                "operation_date": entry.operation_date.isoformat(),
                "statement_reference": cash[0].dimensions["bank_statement"],
                "settlement_account": other[0].account_code,
                "settlement_category": other[0].category,
                "settlement_dimensions": other[0].dimensions, "currency": "BYN"}

    async def source_owner_authority(self, session, organization_id, user):
        actor = await self.source_member(session, organization_id, user)
        role = await session.scalar(select(AccessGrant.role).where(
            AccessGrant.organization_id == organization_id, AccessGrant.subject == actor,
        ))
        if role != "chief":
            raise HTTPException(403, "Chief accountant must confirm source ownership")
        return actor

    async def source_write_authority(self, session, organization_id, user):
        actor = await self.source_member(session, organization_id, user)
        role = await session.scalar(select(AccessGrant.role).where(
            AccessGrant.organization_id == organization_id, AccessGrant.subject == actor,
        ))
        if role not in {"accountant", "chief"}:
            raise HTTPException(403, "Accounting source write access required")
        return actor

    async def source_changed(self, session, organization_id, user, source, version, operation_date):
        from datetime import date

        from modules.accounting import service

        actor = await self.source_member(session, organization_id, user)
        month = date.fromisoformat(operation_date).strftime("%Y-%m")
        current = await session.scalar(select(SourceControl).where(
            SourceControl.organization_id == organization_id, SourceControl.source == source,
        ))
        if current and current.version == version and current.month == month:
            return
        if current and (current.entry_id is not None or version != current.version + 1):
            raise HTTPException(409, "Source completeness version cannot be changed")
        affected_from = min(month, current.month) if current else month
        closed = await session.scalar(select(Period.id).where(
            Period.organization_id == organization_id, Period.month >= affected_from,
            Period.closed.is_(True),
        ).limit(1))
        if closed:
            raise HTTPException(409, "Source affects a closed period; accountant must reopen it or apply an approved correction workflow")
        if current:
            current.version, current.month = version, month
        else:
            session.add(SourceControl(organization_id=organization_id, source=source,
                                      version=version, month=month))
        await service.period_for(session, organization_id, month)
        affected = (await session.scalars(select(Period).where(
            Period.organization_id == organization_id, Period.month >= affected_from,
        ))).all()
        for period in affected:
            period.generation += 1
            period.evidence = {}
        service.audit(session, organization_id, actor, "source_changed", {
            "source": source, "version": version, "month": month,
        })
        await session.flush()

    async def receipt_posting(self, session, organization_id, user, document, *,
                              confirm_digest, event_bus=None):
        from modules.accounting import service
        from modules.accounting.purchases import PurchaseDocument, preview_purchase

        if not is_package_allowed("accounting", user.roles):
            raise HTTPException(403, "Accounting module access required")
        actor = await self.source_member(session, organization_id, user)
        role = await session.scalar(select(AccessGrant.role).where(
            AccessGrant.organization_id == organization_id, AccessGrant.subject == actor,
        ))
        if role not in {"accountant", "chief"}:
            raise HTTPException(403, "Accounting write access required")
        posting, accounts, policy = await preview_purchase(
            session, organization_id, PurchaseDocument.model_validate(document),
        )
        control = await session.scalar(select(SourceControl).where(
            SourceControl.organization_id == organization_id, SourceControl.source == posting.source,
        ))
        if control is None or control.version != posting.source_version:
            raise HTTPException(409, "Source completeness registration is missing or stale")
        if control.month != posting.posting_date.strftime("%Y-%m"):
            raise HTTPException(422, "Posting in a different source period requires an approved correction rule")
        digest = service.digest(posting)
        if confirm_digest is not None:
            if digest != confirm_digest:
                raise HTTPException(409, "Posting preview is stale; calculate it again")
            entry = await service.post(session, organization_id, posting, actor, event_bus)
            if control.entry_id is None:
                control.entry_id = entry.id
                service.audit(session, organization_id, actor, "source_posted", {
                    "source": posting.source, "version": posting.source_version, "entry_id": entry.id,
                })
            return {"entry_id": entry.id, "digest": digest, "entry": serialize(entry)}
        return {"digest": digest, "normative_verified": policy.normative_verified,
                "vat_deducted": False,
                "lines": [{**line.model_dump(mode="json"), "title": accounts[line.account].title}
                          for line in posting.lines]}

    async def sale_posting(self, session, organization_id, user, document, *,
                           confirm_digest, basis_digest=None, event_bus=None):
        from modules.accounting import sales, service

        if not is_package_allowed("accounting", user.roles):
            raise HTTPException(403, "Accounting module access required")
        actor = await self.source_member(session, organization_id, user)
        role = await session.scalar(select(AccessGrant.role).where(
            AccessGrant.organization_id == organization_id, AccessGrant.subject == actor,
        ))
        if role not in {"accountant", "chief"}:
            raise HTTPException(403, "Accounting write access required")
        data = sales.SaleDocument.model_validate(document)
        control = await session.scalar(select(SourceControl).where(
            SourceControl.organization_id == organization_id, SourceControl.source == data.source,
        ))
        if control is None or control.version != data.source_version:
            raise HTTPException(409, "Source completeness registration is missing or stale")
        if control.month != data.posting_date.strftime("%Y-%m"):
            raise HTTPException(422, "Posting in a different source period requires an approved correction rule")
        if confirm_digest is None:
            if basis_digest is not None:
                raise HTTPException(422, "A confirmation digest is required with a cost basis")
            return await sales.prepare(session, organization_id, data,
                procurement=getattr(self.services, "procurement_source", None))
        if basis_digest is None:
            raise HTTPException(422, "Confirmed sale requires its cost basis digest")
        entry = await sales.confirm(session, organization_id, data, basis_digest, confirm_digest, actor, event_bus,
            procurement=getattr(self.services, "procurement_source", None))
        if control.entry_id is not None and control.entry_id != entry.id:
            raise HTTPException(409, "Source revision is linked to another entry")
        if control.entry_id is None:
            control.entry_id = entry.id
            service.audit(session, organization_id, actor, "source_posted", {
                "source": data.source, "version": data.source_version, "entry_id": entry.id,
            })
        await session.flush()
        return {"entry_id": entry.id, "digest": confirm_digest, "entry": serialize(entry)}

    async def source_member(self, session, organization_id, user):
        actor = subject(user)
        # Serialize source operations in the same book, including creation of
        # keys that do not exist yet. The caller owns transaction completion.
        await organization_role(session, organization_id, actor)
        return actor

    async def source_organizations(self, session, user):
        actor = subject(user)
        rows = (await session.scalars(select(Organization).join(AccessGrant).where(
            AccessGrant.subject == actor, AccessGrant.role.in_(["reader", "accountant", "chief"]),
        ).order_by(Organization.id))).all()
        return [{"id": row.id, "name": row.name, "unp": row.unp} for row in rows]
