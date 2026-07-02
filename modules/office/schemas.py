"""Pydantic-схемы модуля Office."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class OfficeDocCreate(BaseModel):
    company: str = ""
    title: str = ""
    amount: float = 0
    delivery: str = ""
    docs_status: str = ""
    priority: str = "Средний"
    owner: str = ""
    stage: str = "ready"
    next_step: str = ""
    number: str = ""
    op_date: str | None = None
    region: str = ""
    weight: str = ""
    address: str = ""
    sales_ref: str = ""


class OfficeDocOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    number: str
    company: str
    title: str
    amount: float
    delivery: str
    docs_status: str
    priority: str
    owner: str
    stage: str
    next_step: str
    op_date: str | None = None
    region: str = ""
    weight: str = ""
    address: str = ""
    sales_ref: str = ""
    wms_ref: str = ""
    logistics_ref: str = ""
    finance_ref: str = ""
    legal_ref: str = ""
    overdue_days: int = 0


class StageUpdate(BaseModel):
    stage: str


class CarrierOut(BaseModel):
    id: str
    name: str
    type: str
    rating: float
    eta: str
    price_from: int
    zone: str
    heavy: bool


class CarrierRequest(BaseModel):
    """Заявка перевозчику на доставку по РБ из карточки документа."""

    carrier: str                 # id перевозчика (см. carriers.py)
    region: str = ""             # направление (город РБ)
    pickup_date: str = ""        # дата забора груза
    contact: str = ""            # контактное лицо (склад)
    comment: str = ""            # комментарий перевозчику


class CarrierRequestOut(BaseModel):
    ok: bool
    log_ref: str                 # сгенерированный номер заявки ЛОГ-2026-NNNN
    carrier: str
    region: str
    doc: OfficeDocOut


class LegalContractCreate(BaseModel):
    counterparty_name: str
    contract_type: str = "supply"   # supply | service | lease | nda
    status: str = "active"
    signed_at: str | None = None
    expires_at: str | None = None
    amount_byn: str = "0.00"
    description: str = ""
    number: str = ""                 # если пустой — автономер


class LegalContractOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    number: str
    counterparty_name: str
    contract_type: str
    status: str
    signed_at: str | None = None
    expires_at: str | None = None
    amount_byn: str
    description: str


class LegalContractPatch(BaseModel):
    status: str | None = None
    description: str | None = None
    expires_at: str | None = None
    amount_byn: str | None = None


class LegalClaimCreate(BaseModel):
    counterparty_name: str
    claim_type: str = "overdue_payment"
    status: str = "open"
    amount_byn: str = "0.00"
    filed_at: str | None = None
    description: str = ""
    office_doc_ref: str = ""
    number: str = ""


class LegalClaimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    number: str
    counterparty_name: str
    claim_type: str
    status: str
    amount_byn: str
    filed_at: str | None = None
    resolved_at: str | None = None
    description: str
    office_doc_ref: str = ""


class LegalClaimPatch(BaseModel):
    status: str | None = None
    resolved_at: str | None = None
    description: str | None = None
    amount_byn: str | None = None
