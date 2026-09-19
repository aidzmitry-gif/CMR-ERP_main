"""Reviewed WIP-to-finished-goods transfer.

The production/WMS services own the physical output facts.  This module only
admits a monetary transfer after the full accepted output and exact WIP basis
have been reviewed, and retains the source package for replay/readback.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date

from pydantic import Field, field_validator
from sqlalchemy import select

from modules.accounting import service
from modules.accounting.models import Entry, Policy, ProductionOutputTransferReceipt
from modules.accounting.production_cost_policy import validate_accounts
from modules.accounting.production_output_cost import preview_output_cost_basis
from modules.accounting.schemas import Input, LineInput, PostingInput, ProductionCostPolicyInput
from modules.accounting.service import AccountingError


class ProductionOutputTransferInput(Input):
    policy_id: int = Field(gt=0, strict=True)
    order_id: int = Field(gt=0, strict=True)
    analytical_order: str = Field(min_length=1, max_length=200)
    department: str = Field(min_length=1, max_length=200)
    warehouse: str = Field(min_length=1, max_length=128)
    posting_date: date
    output_document_ids: list[int] = Field(min_length=1, max_length=100)

    @field_validator("output_document_ids")
    @classmethod
    def unique_documents(cls, value):
        if any(type(item) is not int or item <= 0 for item in value) or len(value) != len(
            set(value)
        ):
            raise ValueError("Output document identities must be positive and unique")
        return value


class ProductionOutputTransferConfirmInput(ProductionOutputTransferInput):
    basis_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


def _period(month: str):
    first = date.fromisoformat(month + "-01")
    return first, first.replace(day=monthrange(first.year, first.month)[1])


def _posting_source(org_id: int, order_id: int) -> str:
    return f"production:output-transfer:{org_id}:{order_id}"


async def _policy(session, org_id: int, month: str, policy_id: int, posting_date: date):
    first, last = _period(month)
    if posting_date < first or posting_date > last:
        raise AccountingError("Output transfer posting date must belong to the selected period")
    policy = await session.scalar(
        select(Policy).where(
            Policy.organization_id == org_id,
            Policy.id == policy_id,
        )
    )
    if policy is None or policy.effective_from > first or policy.production_costing is None:
        raise AccountingError(
            "The saved production policy is not available for this output transfer"
        )
    settings = ProductionCostPolicyInput.model_validate(policy.production_costing)
    accounts = await validate_accounts(session, org_id, last, settings)
    return first, last, policy, settings, accounts


async def _document(
    session,
    org_id: int,
    month: str,
    data: ProductionOutputTransferInput,
    production,
    warehouse_gateway,
):
    review = await preview_output_cost_basis(
        session,
        org_id,
        month,
        data.policy_id,
        data.order_id,
        data.analytical_order,
        data.warehouse,
        production,
        warehouse_gateway,
    )
    if review["status"] != "ready_for_transfer_review" or review["candidate_transfer_byn"] is None:
        raise AccountingError("Production output is not ready for a reviewed transfer")
    expected_ids = sorted(item["document_id"] for item in review["output"]["documents"])
    if sorted(data.output_document_ids) != expected_ids:
        raise AccountingError("Output document set changed; review the accepted output again")
    sku_code = review["output"].get("sku_code")
    target_account = review["target"].get("finished_goods_account")
    if not isinstance(sku_code, str) or not sku_code.strip():
        raise AccountingError("Accepted output has no exact catalog SKU")
    if not isinstance(target_account, str) or not target_account.strip():
        raise AccountingError("Finished-goods account must be explicit in the production policy")
    _, _, policy, settings, accounts = await _policy(
        session, org_id, month, data.policy_id, data.posting_date
    )
    target = accounts.get(target_account)
    if target is None:
        raise AccountingError("Finished-goods account is not available on the posting date")
    values = {
        "warehouse": data.warehouse.strip(),
        "sku": sku_code.strip(),
        "order": data.analytical_order.strip(),
        "department": data.department.strip(),
    }
    if isinstance(review["output"].get("lot"), str) and review["output"]["lot"].strip():
        values["lot"] = review["output"]["lot"].strip()
    missing = set(target.required_dimensions) - values.keys()
    if missing:
        raise AccountingError(
            f"Finished-goods analytics require explicit values: {sorted(missing)}"
        )
    dimensions = {key: values[key] for key in target.required_dimensions}
    try:
        operation_dates = [
            date.fromisoformat(item["operation_date"]) for item in review["output"]["documents"]
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise AccountingError("Accepted output documents have no valid operation date") from exc
    if not operation_dates:
        raise AccountingError("At least one accepted output document is required")
    operation_date = max(operation_dates)
    if operation_date > data.posting_date:
        raise AccountingError("Output transfer posting cannot precede accepted output")
    amount = review["candidate_transfer_byn"]
    quantity = review["output"]["accepted_quantity"]
    wip_groups = review["wip"].get("groups")
    if not isinstance(wip_groups, list) or not wip_groups:
        raise AccountingError("WIP cost basis has no positive analytic groups for transfer")
    wip_lines = []
    for group in wip_groups:
        if not isinstance(group, dict) or not isinstance(group.get("dimensions"), dict):
            raise AccountingError("WIP cost basis has invalid analytic group")
        wip_lines.append(
            LineInput(
                account=settings.wip_account,
                side="credit",
                amount=group.get("balance_byn"),
                dimensions=group["dimensions"],
            )
        )
    posting = PostingInput(
        source=_posting_source(org_id, data.order_id),
        source_version=1,
        operation="production_output_transfer",
        document_date=operation_date,
        operation_date=operation_date,
        posting_date=data.posting_date,
        policy_id=policy.id,
        rule_version="production-output-transfer-v1",
        explanation=f"Перенос НЗП в готовую продукцию по наряду {data.order_id}; {data.department.strip()}",
        lines=[
            LineInput(
                account=target_account,
                side="debit",
                amount=amount,
                dimensions=dimensions,
                quantity=quantity,
            ),
            *wip_lines,
        ],
    )
    await service.validate_posting(session, org_id, posting, production_output_transfer=True)
    return review, posting


async def prepare_output_transfer(
    session,
    org_id: int,
    month: str,
    data: ProductionOutputTransferInput,
    production,
    warehouse_gateway,
):
    review, posting = await _document(session, org_id, month, data, production, warehouse_gateway)
    return {
        **review,
        "posting_document": posting.model_dump(mode="json"),
        "basis_digest": review["basis_digest"],
        "digest": service.digest(posting),
        "posting_available": True,
        "final_cost_certified": False,
    }


async def confirm_output_transfer(
    session,
    org_id: int,
    month: str,
    data: ProductionOutputTransferConfirmInput,
    actor,
    event_bus=None,
    production=None,
    warehouse_gateway=None,
):
    # Serialize the read/prepare/post/receipt package.  Without the company
    # lock, a concurrent retry can observe the first transfer's WIP credit,
    # recalculate a zero basis, and fail instead of replaying the same result.
    await service.lock_organization(session, org_id)
    source = _posting_source(org_id, data.order_id)
    existing = await session.scalar(
        select(Entry).where(
            Entry.organization_id == org_id,
            Entry.source == source,
            Entry.source_version == 1,
            Entry.operation == "production_output_transfer",
        )
    )
    if existing is not None:
        receipt = await session.get(ProductionOutputTransferReceipt, existing.id)
        if (
            receipt is None
            or existing.digest != data.digest
            or receipt.basis_digest != data.basis_digest
            or receipt.actor != actor
            or receipt.command != data.model_dump(mode="json")
        ):
            raise AccountingError("Output transfer already exists with different content")
        return existing
    if production is None or warehouse_gateway is None:
        raise AccountingError("Production and warehouse reconciliation services are unavailable")
    prepared = await prepare_output_transfer(
        session, org_id, month, data, production, warehouse_gateway
    )
    if prepared["basis_digest"] != data.basis_digest or prepared["digest"] != data.digest:
        raise AccountingError("Output cost basis changed; preview again")
    posting = PostingInput.model_validate(prepared["posting_document"])
    entry = await service.post(
        session, org_id, posting, actor, event_bus, production_output_transfer=True
    )
    existing_receipt = await session.get(ProductionOutputTransferReceipt, entry.id)
    if existing_receipt is not None:
        if (
            existing_receipt.organization_id != org_id
            or existing_receipt.order_id != data.order_id
            or existing_receipt.basis_digest != data.basis_digest
            or existing_receipt.digest != data.digest
            or existing_receipt.actor != actor
            or existing_receipt.command != data.model_dump(mode="json")
        ):
            raise AccountingError("Output transfer already exists with different content")
        return entry
    session.add(
        ProductionOutputTransferReceipt(
            entry_id=entry.id,
            organization_id=org_id,
            order_id=data.order_id,
            month=month,
            command=data.model_dump(mode="json"),
            basis=prepared,
            posting=posting.model_dump(mode="json"),
            basis_digest=data.basis_digest,
            digest=data.digest,
            actor=actor,
        )
    )
    await session.flush()
    return entry
