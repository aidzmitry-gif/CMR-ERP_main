from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from modules.office import routes
from modules.office.models import LegalClaim, LegalContract, OfficeDoc
from modules.office.schemas import (
    CarrierRequest,
    LegalClaimCreate,
    LegalClaimPatch,
    LegalContractCreate,
    LegalContractPatch,
    OfficeDocCreate,
    StageUpdate,
)


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class Session:
    def __init__(self, *, gets=None, results=()):
        self.gets = gets or {}
        self.results = list(results)
        self.added = []
        self.commits = 0
        self.refreshed = []
        self.flushes = 0

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = 70 + len(self.added)
        self.added.append(value)

    async def flush(self):
        self.flushes += 1
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = 70

    async def commit(self):
        self.commits += 1

    async def refresh(self, value):
        self.refreshed.append(value)

    async def get(self, model, identity):
        return self.gets.get((model, identity), self.gets.get(identity))

    async def execute(self, _statement):
        return self.results.pop(0) if self.results else Result()


class Bus:
    def __init__(self):
        self.events = []

    def emit(self, session, event_type, payload):
        self.events.append((session, event_type, payload))


def _core(bus=None):
    return SimpleNamespace(event_bus=bus or Bus())


def _doc(**changes):
    values = {
        "id": 5,
        "number": "ДОК-2026-0005",
        "company": "ООО Альфа",
        "title": "АКБ",
        "amount": Decimal("1500"),
        "delivery": "",
        "docs_status": "",
        "priority": "Средний",
        "owner": "Менеджер",
        "stage": "ready",
        "next_step": "",
        "op_date": None,
        "region": "Минск",
        "weight": "10 кг",
        "address": "ул. Ленина",
        "sales_ref": "СД-5",
        "wms_ref": "",
        "logistics_ref": "",
        "finance_ref": "",
        "legal_ref": "",
        "overdue_days": 0,
    }
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_create_doc_generates_number_and_emits_outbox_event():
    session = Session()
    bus = Bus()

    result = await routes.create_doc(
        OfficeDocCreate(company="ООО Альфа", title="АКБ", amount=12.5), session, _core(bus)
    )

    assert isinstance(result, OfficeDoc)
    assert (result.id, result.number, result.amount) == (70, "ДОК-2026-0070", Decimal("12.5"))
    assert session.commits == 1 and session.refreshed == [result]
    assert bus.events[0][1] == "office.doc.created"
    assert bus.events[0][2]["entity_ref"] == "ДОК-2026-0070"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stage", "event"),
    [("ready", "office.shipment.requested"), ("docs", "office.docs.collected"), ("await_pay", "office.payment.awaiting")],
)
async def test_update_doc_emits_event_for_cross_department_stage(stage, event):
    doc = _doc(stage="shipped", overdue_days=20)
    bus = Bus()
    session = Session(gets={(OfficeDoc, 5): doc})

    result = await routes.update_doc(5, StageUpdate(stage=stage), session, _core(bus))

    assert result is doc
    assert doc.stage == stage
    assert bus.events and bus.events[0][1] == event
    assert session.commits == 1


@pytest.mark.asyncio
async def test_update_doc_rejects_missing_or_unknown_stage():
    with pytest.raises(HTTPException) as missing:
        await routes.update_doc(404, StageUpdate(stage="ready"), Session(), _core())
    assert missing.value.status_code == 404

    doc = _doc()
    with pytest.raises(HTTPException) as invalid:
        await routes.update_doc(5, StageUpdate(stage="wrong"), Session(gets={(OfficeDoc, 5): doc}), _core())
    assert invalid.value.status_code == 422


@pytest.mark.asyncio
async def test_carrier_request_updates_doc_and_returns_transport_contract():
    doc = _doc()
    bus = Bus()
    session = Session(gets={(OfficeDoc, 5): doc})

    result = await routes.carrier_request(
        5,
        CarrierRequest(carrier="cdek", region="Гомель", pickup_date="2026-09-20", contact="Склад"),
        session,
        _core(bus),
    )

    assert result.ok is True
    assert (result.log_ref, result.carrier, result.region) == ("ЛОГ-2026-0005", "СДЭК", "Гомель")
    assert (doc.delivery, doc.logistics_ref, doc.region) == ("СДЭК", "ЛОГ-2026-0005", "Гомель")
    assert bus.events[0][1] == "logistics.delivery.requested"


@pytest.mark.asyncio
async def test_carrier_request_rejects_not_ready_and_unknown_carrier():
    shipped = _doc(stage="shipped")
    with pytest.raises(HTTPException) as not_ready:
        await routes.carrier_request(5, CarrierRequest(carrier="cdek"), Session(gets={(OfficeDoc, 5): shipped}), _core())
    assert not_ready.value.status_code == 409

    with pytest.raises(HTTPException) as unknown:
        await routes.carrier_request(5, CarrierRequest(carrier="missing"), Session(gets={(OfficeDoc, 5): _doc()}), _core())
    assert unknown.value.status_code == 422


@pytest.mark.asyncio
async def test_contract_and_claim_crud_maps_fields_and_errors():
    session = Session()
    contract = await routes.create_contract(
        LegalContractCreate(counterparty_name="ООО Бета", amount_byn="99.50"), session
    )
    assert isinstance(contract, LegalContract)
    assert contract.number.startswith("ДОГ-") and contract.amount_byn == "99.50"

    contract_session = Session(gets={(LegalContract, 70): contract})
    patched = await routes.patch_contract(70, LegalContractPatch(status="expired", description="закрыт"), contract_session)
    assert patched.status == "expired" and patched.description == "закрыт"
    assert await routes.get_contract(70, contract_session) is contract

    claim_session = Session()
    claim = await routes.create_claim(
        LegalClaimCreate(counterparty_name="ООО Бета", amount_byn="10.00"), claim_session
    )
    assert isinstance(claim, LegalClaim) and claim.number.startswith("ПРЕТ-")
    claim_session = Session(gets={(LegalClaim, 70): claim})
    patched_claim = await routes.patch_claim(70, LegalClaimPatch(status="resolved"), claim_session)
    assert patched_claim.status == "resolved"
    assert await routes.get_claim(70, claim_session) is claim


@pytest.mark.asyncio
async def test_contract_and_claim_getters_report_not_found():
    with pytest.raises(HTTPException) as contract:
        await routes.get_contract(1, Session())
    with pytest.raises(HTTPException) as claim:
        await routes.get_claim(1, Session())
    assert contract.value.status_code == 404
    assert claim.value.status_code == 404
