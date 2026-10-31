"""БД-тесты «Сделки 2.0»: отказ+причины (SALES-40), история стадий (SALES-43),
прогноз (SALES-44), счётчик непрочитанных (SALES-49). SQLite в памяти."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio

from core.domain.models import Counterparty


@pytest_asyncio.fixture
async def _deals_v2_parties(session):
    """Seed complete directory parties without changing any deal or outcome guard."""
    names = (
        "Synthetic buyer",
        "Synthetic zero",
        "c",
        "ООО R",
        "ООО X",
        "ООО Y",
        "ООО V",
        "ООО Z",
        "ООО Без Истории",
        "ООО Ждёт",
        "ООО Журнал",
        "ООО Параллель",
        "ООО Повтор",
        "ООО Срок",
        "ООО Чат",
        "Одноразовый",
        "Постоянный",
    )
    for index, name in enumerate(names, 1):
        session.add(Counterparty(
            name=name, legal_name=name, unp=str(930000000 + index),
            requisites={"legal_address": "Synthetic Sales v2 test address"},
        ))
    await session.commit()


@pytest_asyncio.fixture
async def _empty_loss_command(api, session):
    """Use the current durable loss workflow only for deals without invoices."""
    from sqlalchemy import select

    from modules.accounting.models import AccessGrant, Organization
    from modules.sales.accounting_ownership import DealOwnership
    from modules.sales.models import DealDocument
    from tests.test_deal_loss import loss_command

    api.headers["X-User"] = "issuer"
    api.headers["X-Expected-Principal"] = "issuer"
    org = Organization(name="Synthetic no-document loss seller", unp="940000001")
    session.add(org)
    await session.flush()
    org_id = org.id
    session.add(AccessGrant(organization_id=org_id, subject="issuer", role="chief"))
    await session.commit()

    async def prepare(deal_id, **changes):
        owner = await session.get(DealOwnership, deal_id)
        if owner is None:
            session.add(DealOwnership(
                deal_id=deal_id, organization_id=org_id, snapshot={},
                evidence="Synthetic exact no-document loss ownership", actor="issuer",
            ))
            await session.commit()
        else:
            assert owner.organization_id == org_id
        assert (await session.scalars(select(DealDocument.id).where(
            DealDocument.deal_id == deal_id, DealDocument.kind == "invoice",
        ))).all() == []
        return await loss_command(api, org_id, deal=deal_id, finalize_if_empty=True, **changes)

    return prepare


@pytest_asyncio.fixture
async def _erp_invoice_command(api, session):
    """Prepare the existing ERP issue contract for each original test deal."""
    from sqlalchemy import select

    from core.domain.models import Sku
    from modules.accounting.models import AccessGrant, Organization
    from modules.sales.accounting_ownership import DealOwnership
    from modules.sales.client_document_register import DealClientBinding, preview_snapshot
    from modules.sales.models import Deal, DealItem
    from modules.wms.models import StockMovement, WarehouseDirectory

    api.headers["X-User"] = "issuer"
    org = Organization(name="Synthetic invoice seller", unp="950000001")
    session.add(org)
    await session.flush()
    org_id = org.id
    session.add(AccessGrant(organization_id=org_id, subject="issuer", role="chief"))
    session.add(WarehouseDirectory(
        organization_id=org_id, name="W", title="Synthetic warehouse",
        created_by="issuer", wms_enabled=False, prohibit_negative_stock=True,
    ))
    await session.commit()
    profile = await api.post(f"/accounting/organizations/{org_id}/seller-profiles", json={
        "source_key": "synthetic-sales-v2-seller", "expected_revision": 0,
        "effective_from": "2026-01-01", "currency": "BYN", "address": "Synthetic seller address",
        "account": "TEST ACCOUNT", "bank": "TEST BANK", "bik": "TEST BIK",
        "director": "Synthetic director", "evidence": "Synthetic seller review", "confirmed": True,
    })
    assert profile.status_code == 201, profile.text

    async def prepare(deal_id, *, reserve_mode="on_order", preview=True):
        deal = await session.get(Deal, deal_id)
        assert deal is not None and deal.counterparty_id is not None
        items = (await session.scalars(select(DealItem).where(
            DealItem.deal_id == deal_id,
        ).order_by(DealItem.id))).all()
        if await session.get(DealOwnership, deal_id) is None:
            session.add(DealOwnership(
                deal_id=deal_id, organization_id=org_id, snapshot={},
                evidence="Synthetic exact invoice ownership", actor="issuer",
            ))
            session.add(DealClientBinding(
                deal_id=deal_id, organization_id=org_id, counterparty_id=deal.counterparty_id,
                snapshot=await preview_snapshot(session, org_id, deal, deal.counterparty_id),
                evidence="Synthetic exact invoice buyer", actor="issuer",
            ))
            # Populate the actual per-organization physical journal, not the cache.
            for item in items:
                sku = await session.get(Sku, item.sku_id)
                if sku is not None:
                    session.add(StockMovement(
                        organization_id=org_id, sku_code=sku.code, warehouse="W", kind="in",
                        qty=item.qty, reason="receipt",
                    ))
            await session.commit()
        base = {
            "organization_id": org_id, "currency": "BYN", "document_date": "2026-09-01",
            "valid_until": "2026-09-06", "reserve_mode": reserve_mode,
            "pricing": [{"item_id": item.id,
                         "unit_price_net": format(item.unit_price, ".2f") if item.unit_price is not None else None,
                         "vat_rate": "20.00"} for item in items],
            "pricing_evidence": "Explicit synthetic confirmed goods-line prices",
        }
        if preview:
            response = await api.post(f"/sales/deals/{deal_id}/invoice-preview", json=base)
            assert response.status_code == 200, response.text
            current = response.json()
            if reserve_mode == "stock":
                assert current["availability"]["organization_id"] == org_id
                assert current["availability"]["source"] == "wms_physical"
            else:
                assert current["availability"] is None
        else:
            # Rejected-input controls have no accepted preview or financial receipt.
            current = {"document_version": 1, "basis_digest": "0" * 64}
        command = {
            "kind": "invoice", **base, "request_key": f"sales-v2-issue-{deal_id}",
            "expected_document_version": current["document_version"],
            "expected_basis_digest": current["basis_digest"], "allocations": [],
        }
        if reserve_mode == "on_order":
            command["unreserved_confirmed"] = True
        else:
            command.update(
                allocations=[{"line_no": line["line_no"], "warehouse": "W", "qty": line["qty"]}
                             for line in current["lines"]],
                evidence="Synthetic complete physical journal", journal_complete=True,
            )
        return command

    return prepare


async def _assert_no_issued_invoice(session, deal_id):
    from sqlalchemy import func, select

    from modules.sales.invoice_issuance import InvoiceIssuanceReceipt
    from modules.sales.models import DealDocument

    assert await session.scalar(select(func.count()).select_from(DealDocument).where(
        DealDocument.deal_id == deal_id, DealDocument.kind == "invoice",
    )) == 0
    assert await session.scalar(select(func.count()).select_from(InvoiceIssuanceReceipt).where(
        InvoiceIssuanceReceipt.deal_id == deal_id,
    )) == 0


async def _new_deal(api, number, **extra):
    payload = {"number": number, "title": "t", "counterparty": "c", **extra}
    r = await api.post("/sales/deals", json=payload)
    assert r.status_code == 201
    return r.json()


async def test_confirmed_item_prices_are_independent_and_original_stays_fixed(
    api, session, _deals_v2_parties, _erp_invoice_command,
):
    from modules.sales.models import PriceQuote
    from modules.sales.routes import _invoice_items

    sku = await _seed_sku(session, "CONFIRMED-PRICE")
    await session.commit()
    a = await _new_deal(api, "PRICE-A", counterparty="Synthetic buyer")
    b = await _new_deal(api, "PRICE-B", counterparty="Synthetic buyer")
    lines = []
    for deal, price in ((a, "100.00"), (b, "250.00")):
        response = await api.post(
            f"/sales/deals/{deal['id']}/items",
            json={"sku_id": sku.id, "qty": 2, "unit_price": price},
        )
        assert response.status_code == 201, response.text
        lines.append(response.json())
        session.add(PriceQuote(sku_code=sku.code, counterparty=deal["counterparty"], price=Decimal(price)))
        await session.commit()

    documents = []
    for deal, expected in ((a, Decimal("100")), (b, Decimal("250"))):
        assert (await _invoice_items(session, deal["id"]))[0]["price"] == expected
        detail = (await api.get(f"/sales/deals/{deal['id']}")).json()
        assert Decimal(str(detail["items"][0]["unit_price"])) == expected
        listed = (await api.get(f"/sales/deals/{deal['id']}/items")).json()
        assert Decimal(str(listed[0]["unit_price"])) == expected
        margin = (await api.get(f"/sales/deals/{deal['id']}/margin")).json()
        assert Decimal(str(margin["lines"][0]["unit_price"])) == expected
        issued = await api.post(
            f"/sales/deals/{deal['id']}/documents",
            json=await _erp_invoice_command(deal["id"]),
        )
        assert issued.status_code == 201, issued.text
        doc = issued.json()["document"]
        assert Decimal(str(doc["amount"])) == expected * 2 * Decimal("1.20")
        documents.append(doc)

    original_id = documents[0]["id"]
    before = await api.get(f"/sales/documents/{original_id}/render")
    assert before.status_code == 200, before.text
    session.add(PriceQuote(sku_code=sku.code, counterparty=a["counterparty"], price=Decimal("999")))
    await session.commit()
    assert (await _invoice_items(session, a["id"]))[0]["price"] == Decimal("100")
    changed = await api.patch(f"/sales/deal-items/{lines[0]['id']}", json={"unit_price": "120.00"})
    assert changed.status_code == 200, changed.text
    after = await api.get(f"/sales/documents/{original_id}/render")
    assert after.status_code == 200
    assert after.content == before.content
    persisted = (await api.get(f"/sales/deals/{a['id']}/documents")).json()[0]
    assert persisted["content_sha256"] == documents[0]["content_sha256"]
    assert persisted["amount"] == 240.0


async def test_item_null_zero_and_partial_update_contract(
    api, session, _deals_v2_parties, _erp_invoice_command,
):
    from modules.sales.models import PriceQuote
    from modules.sales.routes import _invoice_items

    sku = await _seed_sku(session, "CONFIRMED-ZERO")
    await session.commit()
    deal = await _new_deal(api, "PRICE-ZERO", counterparty="Synthetic zero")
    session.add(PriceQuote(sku_code=sku.code, counterparty=deal["counterparty"], price=Decimal("999")))
    await session.commit()
    added = await api.post(f"/sales/deals/{deal['id']}/items", json={"sku_id": sku.id, "qty": 2})
    assert added.status_code == 201, added.text
    item = added.json()
    assert item["unit_price"] is None
    endpoint = f"/sales/deals/{deal['id']}/documents"
    rejected = await api.post(endpoint, json=await _erp_invoice_command(deal["id"], preview=False))
    assert rejected.status_code == 422
    assert any(error["loc"][-1] == "unit_price_net" for error in rejected.json()["detail"])
    await _assert_no_issued_invoice(session, deal["id"])
    # The shared-session test fixture needs the rollback performed by a real request's close.
    await session.rollback()

    patched = await api.patch(f"/sales/deal-items/{item['id']}", json={"unit_price": "0.00"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["qty"] == 2 and patched.json()["unit_price"] == 0
    quantity = await api.patch(f"/sales/deal-items/{item['id']}", json={"qty": 3})
    assert quantity.status_code == 200 and quantity.json()["unit_price"] == 0
    assert (await _invoice_items(session, deal["id"]))[0]["price"] == Decimal("0")
    cleared = await api.patch(f"/sales/deal-items/{item['id']}", json={"unit_price": None})
    assert cleared.status_code == 200 and cleared.json()["unit_price"] is None
    assert cleared.json()["qty"] == 3
    rejected = await api.post(endpoint, json=await _erp_invoice_command(deal["id"], preview=False))
    assert rejected.status_code == 422
    assert any(error["loc"][-1] == "unit_price_net" for error in rejected.json()["detail"])
    await _assert_no_issued_invoice(session, deal["id"])
    await session.rollback()

    assert (await api.patch(f"/sales/deal-items/{item['id']}", json={"qty": None})).status_code == 422
    assert (await api.patch(f"/sales/deal-items/{item['id']}", json={"unit_price": 0})).status_code == 200
    issued = await api.post(endpoint, json=await _erp_invoice_command(deal["id"]))
    assert issued.status_code == 201, issued.text
    assert issued.json()["document"]["amount"] == 0


@pytest.mark.parametrize("price", [-1, "NaN", "Infinity", "1000000000000", "1.001"])
async def test_item_price_rejects_invalid_money(api, session, price, _deals_v2_parties):
    sku = await _seed_sku(session, "CONFIRMED-INVALID")
    deal = await _new_deal(api, "PRICE-INVALID")
    endpoint = f"/sales/deals/{deal['id']}/items"
    assert (await api.post(endpoint, json={"sku_id": sku.id, "unit_price": price})).status_code == 422
    item = (await api.post(endpoint, json={"sku_id": sku.id, "unit_price": "10.50"})).json()
    rejected = await api.patch(f"/sales/deal-items/{item['id']}", json={"unit_price": price})
    assert rejected.status_code == 422
    listed = (await api.get(endpoint)).json()
    assert len(listed) == 1 and listed[0]["unit_price"] == 10.5


async def test_item_price_database_rejects_negative(session):
    from sqlalchemy.exc import IntegrityError

    from modules.sales.models import Deal, DealItem

    deal = Deal(number="PRICE-DB", title="Synthetic", counterparty="Synthetic")
    session.add(deal)
    await session.flush()
    session.add(DealItem(deal_id=deal.id, sku_id=1, qty=1, unit_price=Decimal("-0.01")))
    with pytest.raises(IntegrityError, match="ck_deal_item_unit_price_nonnegative"):
        await session.flush()
    await session.rollback()


async def test_confirmed_price_cannot_issue_an_item_with_missing_sku(
    api, session, _deals_v2_parties, _erp_invoice_command,
):
    from modules.sales.models import DealItem

    deal = await _new_deal(api, "PRICE-ORPHAN")
    session.add(DealItem(deal_id=deal["id"], sku_id=999999, qty=2, unit_price=Decimal("100")))
    await session.commit()
    result = await api.post(f"/sales/deals/{deal['id']}/documents", json=await _erp_invoice_command(
        deal["id"], preview=False,
    ))
    assert result.status_code == 422
    assert result.json()["detail"] == "Invoice goods require an active exact SKU and positive two-place quantity"
    await _assert_no_issued_invoice(session, deal["id"])


# ── SALES-40: отказ + причины ──────────────────────────────────────────────

async def test_lose_requires_reason(api, _deals_v2_parties, _empty_loss_command):
    deal = await _new_deal(api, "L-1", amount=1000)

    # без причины → 422
    bad = await api.post(f"/sales/deals/{deal['id']}/lose", json=await _empty_loss_command(
        deal["id"], reason_code="",
    ))
    assert bad.status_code == 422
    assert any(error["loc"][-1] == "reason_code" for error in bad.json()["detail"])
    legacy = await api.post(f"/sales/deals/{deal['id']}/lose", json={"reason_code": "price"})
    assert legacy.status_code == 422

    # с причиной → стадия lost, причина и дата проставлены
    ok = await api.post(
        f"/sales/deals/{deal['id']}/lose",
        json=await _empty_loss_command(deal["id"], reason_code="price", comment="дорого"),
    )
    assert ok.status_code == 200
    assert ok.json()["state"] == "finalized"
    body = (await api.get(f"/sales/deals/{deal['id']}")).json()
    assert body["stage"] == "lost"
    assert body["lost_reason_code"] == "price"
    assert body["lost_comment"] == "дорого"
    assert body["closed_date"]

    # повторно закрыть в отказ нельзя
    again = await api.post(f"/sales/deals/{deal['id']}/lose", json=await _empty_loss_command(
        deal["id"], reason_code="other",
    ))
    assert again.status_code == 409


async def test_lose_validates_against_dictionary(session, api, _deals_v2_parties, _empty_loss_command):
    from modules.sales.models import LossReason

    session.add(LossReason(code="price", title="Дорого", sort_order=1, active=True))
    await session.commit()

    deal = await _new_deal(api, "L-2")
    # код вне справочника → 422
    bad = await api.post(f"/sales/deals/{deal['id']}/lose", json=await _empty_loss_command(
        deal["id"], reason_code="zzz",
    ))
    assert bad.status_code == 422
    assert bad.json()["detail"] == "Unknown loss reason"
    # валидный код → ок
    ok = await api.post(f"/sales/deals/{deal['id']}/lose", json=await _empty_loss_command(
        deal["id"], reason_code="price",
    ))
    assert ok.status_code == 200
    assert ok.json()["state"] == "finalized"


async def test_loss_reasons_endpoint(session, api):
    from modules.sales.models import LossReason

    session.add(LossReason(code="a", title="A", sort_order=2, active=True))
    session.add(LossReason(code="b", title="B", sort_order=1, active=True))
    session.add(LossReason(code="c", title="C", sort_order=3, active=False))
    await session.commit()

    rows = (await api.get("/sales/loss-reasons")).json()
    codes = [r["code"] for r in rows]
    assert codes == ["b", "a"]  # только активные, по sort_order


async def test_lost_emits_event(session, api, _deals_v2_parties, _empty_loss_command):
    from sqlalchemy import select

    from core.domain.models import OutboxEvent

    deal = await _new_deal(api, "L-3", amount=500)
    response = await api.post(f"/sales/deals/{deal['id']}/lose", json=await _empty_loss_command(
        deal["id"], reason_code="competitor",
    ))
    assert response.status_code == 200, response.text
    row = response.json()
    assert row["state"] == "finalized"
    events = (await session.scalars(select(OutboxEvent).where(
        OutboxEvent.event_type == "sales.deal.loss_finalized",
    ))).all()
    assert len(events) == 1
    assert events[0].payload == {
        "deal_id": deal["id"], "organization_id": row["organization_id"],
        "request_id": row["request_id"], "resolution_id": row["resolution"]["resolution_id"],
        "digest": row["resolution"]["digest"], "by": "issuer",
    }


async def test_lost_column_on_board(api, _deals_v2_parties, _empty_loss_command):
    deal = await _new_deal(api, "L-4", amount=700)
    response = await api.post(f"/sales/deals/{deal['id']}/lose", json=await _empty_loss_command(
        deal["id"], reason_code="no_need",
    ))
    assert response.status_code == 200 and response.json()["state"] == "finalized"

    board = (await api.get("/sales/board")).json()
    stages = {s["id"]: s for s in board["stages"]}
    assert "lost" in stages
    assert stages["lost"]["title"] == "Отказ"
    assert stages["lost"]["count"] == 1
    assert stages["lost"]["sum"] == 700


# ── SALES-40: выигрыш ───────────────────────────────────────────────────────

async def test_win_deal(session, api, _deals_v2_parties):
    from sqlalchemy import select

    from core.domain.models import OutboxEvent

    deal = await _new_deal(api, "W-1", amount=2000)
    r = await api.post(f"/sales/deals/{deal['id']}/win")
    assert r.status_code == 200
    body = r.json()
    assert body["stage"] == "won"
    assert body["closed_date"]

    # повторно нельзя
    assert (await api.post(f"/sales/deals/{deal['id']}/win")).status_code == 409

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "sales.deal.won" in types


# ── Цикл 18 (фикс верификации): won-код воронки, реверс из closed ───────────

async def test_win_deal_repeat_clients_resolves_rp_won(api, _deals_v2_parties):
    """Фикс 1: win на сделке repeat_clients ставит ``rp_won`` (не литерал "won", которого
    нет в этой воронке) — иначе сделка выпадала бы с /board?funnel=repeat_clients."""
    await api.get("/sales/stages")  # материализовать канон всех воронок
    deal = await _new_deal(api, "RP-W-1", stage="rp_request", funnel="repeat_clients", amount=1500)

    r = await api.post(f"/sales/deals/{deal['id']}/win")
    assert r.status_code == 200
    body = r.json()
    assert body["stage"] == "rp_won"
    assert body["closed_date"]

    # повторно нельзя — 409 сверяется с ПРАВИЛЬНЫМ won-кодом воронки, не с литералом "won"
    assert (await api.post(f"/sales/deals/{deal['id']}/win")).status_code == 409

    board = (await api.get("/sales/board?funnel=repeat_clients")).json()
    won_col = next(st for st in board["stages"] if st["id"] == "rp_won")
    assert won_col["count"] == 1


async def test_lose_deal_repeat_clients_resolves_rp_lost(api, _deals_v2_parties, _empty_loss_command):
    """Тот же класс бага, что Фикс 1 (win): lose на сделке repeat_clients ставит ``rp_lost``
    (не литерал "lost", которого нет в этой воронке) — иначе закрытая сделка выпадала бы
    с /board?funnel=repeat_clients."""
    await api.get("/sales/stages")  # материализовать канон всех воронок
    deal = await _new_deal(api, "RP-L-1", stage="rp_request", funnel="repeat_clients", amount=800)

    r = await api.post(f"/sales/deals/{deal['id']}/lose", json=await _empty_loss_command(
        deal["id"], reason_code="price",
    ))
    assert r.status_code == 200
    assert r.json()["state"] == "finalized"
    body = (await api.get(f"/sales/deals/{deal['id']}")).json()
    assert body["stage"] == "rp_lost"
    assert body["closed_date"]

    # повторно нельзя — 409 сверяется с ПРАВИЛЬНЫМ lost-кодом воронки, не с литералом "lost"
    again = await api.post(f"/sales/deals/{deal['id']}/lose", json=await _empty_loss_command(
        deal["id"], reason_code="other",
    ))
    assert again.status_code == 409

    board = (await api.get("/sales/board?funnel=repeat_clients")).json()
    lost_col = next(st for st in board["stages"] if st["id"] == "rp_lost")
    assert lost_col["count"] == 1


async def test_reverse_from_won_clears_closed_date(api, _deals_v2_parties):
    """Фикс 2: реверс сделки из won в нетерминальную стадию сбрасывает ``closed_date`` —
    иначе сделка, возвращённая в работу, продолжает числиться закрытой в отчётах."""
    deal = await _new_deal(api, "REV-1", amount=900)
    won = await api.post(f"/sales/deals/{deal['id']}/win")
    assert won.json()["closed_date"]

    back = await api.patch(f"/sales/deals/{deal['id']}", json={"stage": "qual"})
    assert back.status_code == 200
    assert back.json()["closed_date"] is None


# ── SALES-43: история стадий и висяки ───────────────────────────────────────

async def test_stage_history_recorded(api, _deals_v2_parties):
    deal = await _new_deal(api, "H-1", stage="new")
    await api.patch(f"/sales/deals/{deal['id']}", json={"stage": "qual"})
    await api.patch(f"/sales/deals/{deal['id']}", json={"stage": "price_req"})

    hist = (await api.get(f"/sales/deals/{deal['id']}/history")).json()
    transitions = [(h["from_stage"], h["to_stage"]) for h in hist]
    assert ("new", "qual") in transitions
    assert ("qual", "price_req") in transitions


async def test_stage_history_orders_imported_event_before_later_local_event(api, session, _deals_v2_parties):
    from modules.sales.models import DealStageEvent

    deal = await _new_deal(api, "H-MIXED", stage="new")
    session.add(DealStageEvent(
        deal_id=deal["id"], from_stage="new", to_stage="qual",
        changed_at=datetime(2026, 1, 1, 9),
    ))
    await session.flush()
    session.add(DealStageEvent(
        deal_id=deal["id"], source_ref="bitrix:deal-stage:30:80",
        from_stage=None, to_stage="new", changed_at=datetime(2024, 11, 2, 7),
    ))
    await session.commit()

    history = (await api.get(f"/sales/deals/{deal['id']}/history")).json()
    stages = [event["to_stage"] for event in history]
    assert stages.index("new") < stages.index("qual")


async def test_deal_timeline_comments_are_chronological_and_owner_scoped(api, session, _deals_v2_parties):
    from modules.sales.models import CrmTimelineComment

    deal = await _new_deal(api, "C-TIMELINE")
    other = await _new_deal(api, "C-OTHER")
    session.add_all([
        CrmTimelineComment(
            entity_type="deal", deal_id=deal["id"], source_ref="bitrix:timeline-comment:deal:8",
            source_entity_id=str(deal["id"]), body="second", author_display="Manager",
            created_at=datetime(2025, 1, 2, 9),
        ),
        CrmTimelineComment(
            entity_type="deal", deal_id=deal["id"], source_ref="bitrix:timeline-comment:deal:7",
            source_entity_id=str(deal["id"]), body="<script>text only</script>", author_display="Manager",
            created_at=datetime(2025, 1, 1, 9),
        ),
        CrmTimelineComment(
            entity_type="deal", deal_id=other["id"], source_ref="bitrix:timeline-comment:deal:9",
            source_entity_id=str(other["id"]), body="other", author_display="Manager",
            created_at=datetime(2025, 1, 1, 9),
        ),
    ])
    await session.commit()

    response = await api.get(f"/sales/deals/{deal['id']}/timeline/comments")
    assert response.status_code == 200
    assert [row["body"] for row in response.json()] == ["<script>text only</script>", "second"]
    assert all(set(row) == {"id", "body", "author_display", "created_at"}
               for row in response.json())
    assert (await api.get("/sales/deals/999999/timeline/comments")).status_code == 404


def test_timeline_attachment_storage_is_streamed_and_content_addressed(tmp_path):
    import os
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from types import SimpleNamespace

    from modules.sales import timeline_storage

    storage_root = tmp_path.parent / f"timeline-{tmp_path.name[:8]}"
    if os.name == "nt":
        storage_root = Path("\\\\?\\" + str(storage_root.resolve()))
    storage_root.mkdir()
    stored = timeline_storage.store_attachment(
        (chunk for chunk in (b"small ", b"chunks")), root=storage_root, max_size_bytes=12
    )
    repeated = timeline_storage.store_attachment(
        (chunk for chunk in (b"small ", b"chunks")), root=storage_root, max_size_bytes=12
    )
    assert repeated == stored
    assert (storage_root / stored.storage_path).read_bytes() == b"small chunks"
    assert timeline_storage.verify_attachment(
        SimpleNamespace(
            sha256=stored.sha256,
            storage_path=stored.storage_path,
            size_bytes=stored.size_bytes,
        ),
        root=storage_root,
    ) == (storage_root / stored.storage_path).resolve()

    with ThreadPoolExecutor(max_workers=4) as pool:
        concurrent = list(pool.map(
            lambda _: timeline_storage.store_attachment([b"concurrent"], root=storage_root),
            range(4),
        ))
    assert all(item == concurrent[0] for item in concurrent)
    assert {path.name for path in storage_root.rglob("*") if path.is_file()} == {
        stored.sha256, concurrent[0].sha256,
    }
    assert len(list((storage_root / ".staging").glob(".timeline-*"))) == 0

    with pytest.raises(timeline_storage.AttachmentRejected):
        timeline_storage.store_attachment((b"123", b"456"), root=storage_root, max_size_bytes=5)
    with pytest.raises(timeline_storage.AttachmentRejected):
        timeline_storage.store_attachment(
            [], root=storage_root, max_size_bytes=timeline_storage.MAX_ATTACHMENT_BYTES + 1
        )
    assert not list((storage_root / ".staging").glob(".timeline-*"))


def test_timeline_attachment_storage_fails_closed_on_corrupt_digest_path(tmp_path, monkeypatch):
    import hashlib
    from pathlib import Path

    from modules.sales import timeline_storage

    stored = timeline_storage.store_attachment([b"original"], root=tmp_path)
    (tmp_path / stored.storage_path).write_bytes(b"tampered")
    with pytest.raises(timeline_storage.AttachmentRejected):
        timeline_storage.store_attachment([b"original"], root=tmp_path)

    retry_root = tmp_path / "retry-root"
    retry_root.mkdir()
    retry_payload = b"retry after fsync failure"
    retry_digest = hashlib.sha256(retry_payload).hexdigest()
    resolved_retry_root = retry_root.resolve()
    digest_directory = resolved_retry_root / retry_digest[:2] / retry_digest[2:4]
    sync_calls = []
    fail_once = True

    def fail_root_sync_after_install(path):
        nonlocal fail_once
        path = Path(path)
        sync_calls.append(path)
        if path == resolved_retry_root and digest_directory.exists() and fail_once:
            fail_once = False
            raise OSError("simulated root directory fsync failure")

    monkeypatch.setattr(timeline_storage, "_sync_directory", fail_root_sync_after_install)
    with pytest.raises(timeline_storage.AttachmentRejected):
        timeline_storage.store_attachment([retry_payload], root=retry_root)
    assert fail_once is False

    retry_sync_start = len(sync_calls)
    retried = timeline_storage.store_attachment([retry_payload], root=retry_root)
    assert retried.sha256 == retry_digest
    expected_ancestors = set()
    directory = digest_directory.resolve()
    while True:
        expected_ancestors.add(directory)
        if directory.parent == directory:
            break
        directory = directory.parent
    assert expected_ancestors <= set(sync_calls[retry_sync_start:])


def test_timeline_attachment_model_uses_bigint_and_restrictive_comment_fk():
    from sqlalchemy import BigInteger

    from modules.sales.models import CrmTimelineAttachment

    table = CrmTimelineAttachment.__table__
    assert isinstance(table.c.size_bytes.type, BigInteger)
    foreign_key = next(iter(table.c.comment_id.foreign_keys))
    assert foreign_key.target_fullname == "sales.crm_timeline_comment.id"
    assert foreign_key.ondelete is None
    assert table.c.source_ref.nullable is False
    assert any(constraint.name == "uq_crm_timeline_attachment_source_ref"
               for constraint in table.constraints)


async def test_deal_task_source_ref_allows_manual_rows_and_rejects_duplicate_sources(api, session, _deals_v2_parties):
    from sqlalchemy import func, select
    from sqlalchemy.exc import IntegrityError

    from modules.sales.models import DealTask

    table = DealTask.__table__
    assert table.c.source_ref.nullable is True
    assert table.c.source_ref.type.length == 128
    assert any(constraint.name == "uq_deal_task_source_ref"
               for constraint in table.constraints)

    deal = await _new_deal(api, "DEAL-TASK-SOURCE-REF")
    session.add_all([
        DealTask(deal_id=deal["id"], title="Manual task A", source_ref=None),
        DealTask(deal_id=deal["id"], title="Manual task B", source_ref=None),
    ])
    await session.commit()
    assert await session.scalar(
        select(func.count()).select_from(DealTask).where(DealTask.source_ref.is_(None))
    ) == 2

    session.add(DealTask(
        deal_id=deal["id"], title="Imported task", source_ref="bitrix:task:9001",
    ))
    await session.commit()
    session.add(DealTask(
        deal_id=deal["id"], title="Duplicate imported task", source_ref="bitrix:task:9001",
    ))
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()
    assert await session.scalar(select(func.count()).select_from(DealTask)) == 3


async def test_deal_task_fidelity_supports_unbound_tasks_and_ordered_crm_links(api, session, _deals_v2_parties):
    from sqlalchemy import Boolean, Text, func, select
    from sqlalchemy.exc import IntegrityError

    from modules.sales.models import DealTask, DealTaskCrmLink

    task_table = DealTask.__table__
    link_table = DealTaskCrmLink.__table__
    assert task_table.c.deal_id.nullable is True
    assert isinstance(task_table.c.description.type, Text)
    assert isinstance(task_table.c.description_in_bbcode.type, Boolean)
    assert task_table.c.source_responsible_id.type.length == 64
    assert task_table.c.source_status_code.type.length == 16
    assert isinstance(link_table.c.raw_binding.type, Text)
    assert link_table.c.raw_binding.nullable is True
    assert link_table.c.deal_id.nullable is True
    assert any(
        constraint.name == "uq_deal_task_crm_link_task_ordinal"
        for constraint in link_table.constraints
    )

    deal = await _new_deal(api, "DEAL-TASK-FIDELITY")
    unbound_task = DealTask(
        deal_id=None,
        title="Unbound source task",
        description="Long source description",
        description_in_bbcode=False,
        source_responsible_id="9001",
        source_status_code="5",
    )
    linked_task = DealTask(deal_id=deal["id"], title="Multi-link source task")
    session.add_all([unbound_task, linked_task])
    await session.flush()
    linked_task_id = linked_task.id
    session.add_all([
        DealTaskCrmLink(
            task_id=linked_task_id,
            ordinal=0,
            raw_binding="D_" + "x" * 700,
            entity_type="DEAL",
            source_id="101",
            deal_id=deal["id"],
        ),
        DealTaskCrmLink(
            task_id=linked_task_id,
            ordinal=1,
            raw_binding="L_202",
            entity_type="LEAD",
            source_id="202",
            deal_id=None,
        ),
    ])
    await session.commit()

    assert await session.scalar(
        select(func.count()).select_from(DealTask).where(DealTask.deal_id.is_(None))
    ) == 1
    assert await session.scalar(
        select(func.count()).select_from(DealTaskCrmLink).where(
            DealTaskCrmLink.task_id == linked_task_id
        )
    ) == 2
    persisted = await session.scalar(
        select(DealTaskCrmLink.raw_binding).where(
            DealTaskCrmLink.task_id == linked_task_id,
            DealTaskCrmLink.ordinal == 0,
        )
    )
    assert persisted == "D_" + "x" * 700

    session.add(DealTaskCrmLink(
        task_id=linked_task_id,
        ordinal=1,
        raw_binding="duplicate ordinal",
    ))
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()
    assert await session.scalar(
        select(func.count()).select_from(DealTaskCrmLink).where(
            DealTaskCrmLink.task_id == linked_task_id
        )
    ) == 2


async def test_timeline_attachment_source_ref_is_unique(api, session, _deals_v2_parties):
    from sqlalchemy.exc import IntegrityError

    from modules.sales.models import CrmTimelineAttachment, CrmTimelineComment

    deal = await _new_deal(api, "TIMELINE-ATTACHMENT-UNIQUE")
    comment = CrmTimelineComment(
        entity_type="deal", deal_id=deal["id"], body="comment", author_display="",
        created_at=datetime(2025, 1, 1),
    )
    session.add(comment)
    await session.flush()
    common = {
        "comment_id": comment.id, "source_ref": "bitrix:timeline-file:unique",
        "sha256": "0" * 64, "size_bytes": 0, "filename": "file.bin",
        "content_type": "application/octet-stream", "storage_path": "00/00/" + "0" * 64,
    }
    session.add_all([CrmTimelineAttachment(**common), CrmTimelineAttachment(**common)])
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_timeline_attachment_api_lists_private_metadata_and_streams_verified_file(
    api, session, tmp_path, monkeypatch
, _deals_v2_parties):
    import asyncio
    import tempfile

    from modules.sales import routes as sales_routes
    from modules.sales import timeline_storage
    from modules.sales.models import CrmTimelineAttachment, CrmTimelineComment

    monkeypatch.setattr(timeline_storage, "storage_root", lambda: tmp_path)
    deal = await _new_deal(api, "TIMELINE-ATTACHMENT")
    comment = CrmTimelineComment(
        entity_type="deal", deal_id=deal["id"], source_ref="bitrix:timeline-comment:deal:50",
        source_entity_id=str(deal["id"]), body="file attached", author_display="Manager",
        created_at=datetime(2025, 1, 1),
    )
    session.add(comment)
    await session.flush()
    stored = timeline_storage.store_attachment([b"private attachment bytes"], root=tmp_path)
    attachment = CrmTimelineAttachment(
        comment_id=comment.id, source_ref="bitrix:timeline-file:50:1",
        sha256=stored.sha256, size_bytes=stored.size_bytes,
        filename="../../report\r\nX-Injected: yes.pdf", content_type="text/html",
        storage_path=stored.storage_path,
    )
    session.add(attachment)
    await session.commit()

    base = f"/sales/deals/{deal['id']}/timeline/comments/{comment.id}/attachments"
    listed = await api.get(base)
    assert listed.status_code == 200, listed.text
    assert listed.json() == [{
        "id": attachment.id,
        "filename": "reportX-Injected: yes.pdf",
        "content_type": attachment.content_type,
        "size_bytes": stored.size_bytes,
    }]
    assert "storage_path" not in listed.text and "source_ref" not in listed.text
    assert "sha256" not in listed.text

    source_path = tmp_path / stored.storage_path
    original_snapshot = timeline_storage.snapshot_attachment
    snapshots = []

    def snapshot_then_mutate_source(item):
        snapshot = original_snapshot(item)
        snapshots.append(snapshot)
        if item.id == attachment.id:
            source_path.write_bytes(b"source changed after snapshot verification")
        return snapshot

    monkeypatch.setattr(timeline_storage, "snapshot_attachment", snapshot_then_mutate_source)

    downloaded = await api.get(f"{base}/{attachment.id}/download")
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == b"private attachment bytes"
    assert snapshots[-1].closed
    assert downloaded.headers["cache-control"] == "private, no-store"
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    disposition = downloaded.headers["content-disposition"]
    assert "attachment" in disposition and "filename*=utf-8''report" in disposition
    assert "X-Injected" in disposition and "\r" not in disposition and "\n" not in disposition
    assert downloaded.headers["content-type"].startswith("text/html")

    mismatch = await api.get(
        f"/sales/deals/{deal['id']}/timeline/comments/{comment.id + 1}/attachments/{attachment.id}/download"
    )
    assert mismatch.status_code == 404

    unsafe_path = CrmTimelineAttachment(
        comment_id=comment.id, source_ref="bitrix:timeline-file:50:2",
        sha256=stored.sha256, size_bytes=stored.size_bytes, filename="unsafe.txt",
        content_type="text/plain", storage_path="../../outside-file",
    )
    session.add(unsafe_path)
    await session.commit()
    rejected_path = await api.get(f"{base}/{unsafe_path.id}/download")
    assert rejected_path.status_code == 404
    assert "outside-file" not in rejected_path.text

    (tmp_path / stored.storage_path).write_bytes(b"corrupt")
    corrupted = await api.get(f"{base}/{attachment.id}/download")
    assert corrupted.status_code == 404
    assert "corrupt" not in corrupted.text and stored.sha256 not in corrupted.text

    cancelled_snapshot = tempfile.TemporaryFile(mode="w+b")
    cancelled_snapshot.write(b"stream then cancel")
    cancelled_snapshot.seek(0)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def cancel_during_body(message):
        if message["type"] == "http.response.body" and message.get("body"):
            raise asyncio.CancelledError

    response = sales_routes._TimelineAttachmentStreamingResponse(
        cancelled_snapshot, media_type="application/octet-stream"
    )
    with pytest.raises(asyncio.CancelledError):
        await response(
            {"type": "http", "asgi": {"spec_version": "2.4"}},
            receive,
            cancel_during_body,
        )
    assert cancelled_snapshot.closed


async def test_stage_change_updates_stage_changed_at(session, api, _deals_v2_parties):
    from modules.sales.models import Deal

    deal = await _new_deal(api, "H-2", stage="new")
    # состарим вход в стадию
    obj = await session.get(Deal, deal["id"])
    obj.stage_changed_at = datetime(2020, 1, 1)
    await session.commit()

    await api.patch(f"/sales/deals/{deal['id']}", json={"stage": "qual"})
    obj2 = await session.get(Deal, deal["id"])
    assert obj2.stage_changed_at.year >= 2026  # обновилось при смене стадии


async def test_stuck_deals_filter(session, api, _deals_v2_parties):
    from modules.sales.models import Deal

    stale = await _new_deal(api, "ST-1", stage="qual")
    fresh = await _new_deal(api, "ST-2", stage="qual")
    won = await _new_deal(api, "ST-3", stage="qual")

    old = datetime(2020, 1, 1)
    for num in (stale["id"], won["id"]):
        o = await session.get(Deal, num)
        o.stage_changed_at = old
    # won — закрыт, не должен попадать в висяки даже будучи старым
    won_obj = await session.get(Deal, won["id"])
    won_obj.stage = "won"
    await session.commit()

    rows = (await api.get("/sales/deals?stuck_days=7")).json()
    ids = {d["id"] for d in rows}
    assert stale["id"] in ids
    assert fresh["id"] not in ids
    assert won["id"] not in ids


# ── SALES-44: вероятность и взвешенная сумма ───────────────────────────────

async def test_probability_patch(api, _deals_v2_parties):
    deal = await _new_deal(api, "P-1", amount=1000)
    r = await api.patch(
        f"/sales/deals/{deal['id']}",
        json={"probability": 65, "expected_close_date": "30.06.2026"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["probability"] == 65
    assert body["expected_close_date"] == "30.06.2026"


async def test_board_weighted(api, _deals_v2_parties):
    # явная вероятность
    await _new_deal(api, "WT-1", stage="has_price", amount=1000, probability=20)
    # без вероятности → дефолт стадии has_price = 45%
    await _new_deal(api, "WT-2", stage="has_price", amount=1000)

    board = (await api.get("/sales/board")).json()
    col = next(s for s in board["stages"] if s["id"] == "has_price")
    assert col["sum"] == 2000
    assert col["weighted"] == 200 + 450  # 1000*20% + 1000*45%(дефолт)


# ── SALES-49: непрочитанные сообщения ──────────────────────────────────────

async def test_chats_unread_and_mark_read(api, _deals_v2_parties):
    deal = await _new_deal(api, "U-1", counterparty="ООО Чат")
    # входящее от клиента → непрочитано
    await api.post(
        f"/sales/deals/{deal['id']}/messages",
        json={"channel": "whatsapp", "text": "Здравствуйте", "direction": "in"},
    )
    await api.post(
        f"/sales/deals/{deal['id']}/messages",
        json={"channel": "whatsapp", "text": "Ещё вопрос", "direction": "in"},
    )

    chats = (await api.get("/sales/chats")).json()
    chat = next(c for c in chats if c["deal_id"] == deal["id"])
    assert chat["unread"] == 2

    # отметить прочитанным → счётчик обнуляется
    r = await api.post(f"/sales/deals/{deal['id']}/messages/read")
    assert r.status_code == 200 and r.json()["read"] == 2

    chats2 = (await api.get("/sales/chats")).json()
    chat2 = next(c for c in chats2 if c["deal_id"] == deal["id"])
    assert chat2["unread"] == 0


# ── Цикл 17: возраст ожидания ответа ────────────────────────────────────────

async def test_chats_waiting_since(session, api, _deals_v2_parties):
    """waiting_since = created_at САМОГО СТАРОГО непрочитанного входящего (MIN, не MAX).

    Цикл 18 (фикс верификации): оба сообщения создаются в один SQLite-тик (секундная точность
    created_at) — без явного расхождения дат min==max, и тест прошёл бы даже с ошибочным
    func.max. Выставляем created_at напрямую разными датами, чтобы отличить min от max.
    """
    from sqlalchemy import select

    from modules.sales.models import Message

    deal = await _new_deal(api, "U-2", counterparty="ООО Ждёт")

    await api.post(
        f"/sales/deals/{deal['id']}/messages",
        json={"channel": "whatsapp", "text": "Первое", "direction": "in"},
    )
    await api.post(
        f"/sales/deals/{deal['id']}/messages",
        json={"channel": "whatsapp", "text": "Второе", "direction": "in"},
    )

    rows = (
        await session.execute(
            select(Message).where(Message.deal_id == deal["id"]).order_by(Message.id)
        )
    ).scalars().all()
    rows[0].created_at = datetime(2026, 1, 1, 10, 0, 0)  # «Первое» — старше
    rows[1].created_at = datetime(2026, 1, 1, 11, 0, 0)  # «Второе» — младше
    await session.commit()

    msgs = (await api.get(f"/sales/deals/{deal['id']}/messages")).json()
    oldest_created_at, newest_created_at = msgs[0]["created_at"], msgs[1]["created_at"]

    chats = (await api.get("/sales/chats")).json()
    chat = next(c for c in chats if c["deal_id"] == deal["id"])
    assert chat["waiting_since"] == oldest_created_at
    assert chat["waiting_since"] != newest_created_at

    # отметить прочитанным → бейдж гаснет (waiting_since вновь None)
    r = await api.post(f"/sales/deals/{deal['id']}/messages/read")
    assert r.status_code == 200 and r.json()["read"] == 2

    chats2 = (await api.get("/sales/chats")).json()
    chat2 = next(c for c in chats2 if c["deal_id"] == deal["id"])
    assert chat2["waiting_since"] is None


# ── Сделки 2.0: редактор стадий (sales.stage CRUD) ──────────────────────────
async def test_stage_editor_lazy_seed_and_crud(api):
    # первый GET лениво материализует канон (11 new_clients + 5 repeat_clients + 5 tenders = 21)
    stages = (await api.get("/sales/stages")).json()
    new_clients = [s for s in stages if s["funnel"] == "new_clients"]
    repeat_clients = [s for s in stages if s["funnel"] == "repeat_clients"]
    tenders = [s for s in stages if s["funnel"] == "tenders"]
    assert len(new_clients) == 11 and len(repeat_clients) == 5 and len(tenders) == 5
    assert new_clients[0]["code"] == "new"
    won = next(s for s in stages if s["code"] == "won")
    assert won["kind"] == "won" and won["probability"] == 100

    created = await api.post(
        "/sales/stages", json={"code": "nurture", "title": "Дожим", "probability": 40}
    )
    assert created.status_code == 201
    # дубль кода → 409
    assert (await api.post("/sales/stages", json={"code": "nurture", "title": "x"})).status_code == 409

    upd = await api.patch("/sales/stages/nurture", json={"title": "Дожим клиента", "probability": 42})
    assert upd.status_code == 200 and upd.json()["title"] == "Дожим клиента"

    # удалить пустую стадию → 204
    assert (await api.delete("/sales/stages/nurture")).status_code == 204


async def test_stage_delete_blocked_when_deals_exist(api, _deals_v2_parties):
    await api.get("/sales/stages")  # материализовать канон
    await _new_deal(api, "ST-1", stage="qual")
    # в стадии есть сделка → удаление запрещено (409, целостность Deal.stage)
    assert (await api.delete("/sales/stages/qual")).status_code == 409


# ── П1: факт-маржа через landed_cost ────────────────────────────────────────────
class _FakeLanded:
    """Стенд фасада landed_cost для тестов: SKU1 → unit_landed_cost_byn 10, остальные → None."""

    async def last_landed_cost(self, session, sku_code):
        return await self._one(sku_code)

    async def last_landed_cost_batch(self, session, sku_codes):
        return {c: await self._one(c) for c in sku_codes}

    async def _one(self, code):
        if code == "SKU1":
            from decimal import Decimal as D
            return {
                "unit_landed_cost_byn": D("10.00"),
                "shipment_id": 42,
                "fixed_at": datetime(2026, 6, 1, 10, 0),
                "stage": "closed",
                "fx_rate": D("3.21"),
                "fx_date": "2026-06-01",
            }
        return None


async def _seed_sku(session, code, title="t", unit="шт"):
    from core.domain.models import Sku

    sku = Sku(code=code, title=title, unit=unit)
    session.add(sku)
    await session.flush()
    return sku


async def test_deal_margin_priced_no_price_no_cost(api, session, _deals_v2_parties):
    """П1: margin отдаёт revenue/cogs/gross для priced; статусы no_price/no_cost для остальных."""
    from modules.sales.models import DealItem, PriceQuote

    # Заменим landed-фасад в core на стенд
    sku1 = await _seed_sku(session, "SKU1", "A1")
    sku2 = await _seed_sku(session, "SKU2", "A2")
    sku3 = await _seed_sku(session, "SKU3", "A3")
    deal = await _new_deal(api, "MGN-1", counterparty="ООО X")
    session.add_all([
        DealItem(deal_id=deal["id"], sku_id=sku1.id, qty=5, unit_price=15),
        DealItem(deal_id=deal["id"], sku_id=sku2.id, qty=3, unit_price=20),
        DealItem(deal_id=deal["id"], sku_id=sku3.id, qty=2),
        PriceQuote(sku_code="SKU1", counterparty="ООО X", price=15),
        PriceQuote(sku_code="SKU2", counterparty="ООО X", price=20),
    ])
    await session.commit()
    # подменяем фасад на стенд
    app = api._transport.app  # type: ignore[attr-defined]

    app.state.core.services.landed_cost = _FakeLanded()
    try:
        r = (await api.get(f"/sales/deals/{deal['id']}/margin")).json()
    finally:
        app.state.core.services.landed_cost = None
    assert r["revenue"] == 75.0
    assert r["cogs_landed"] == 50.0
    assert r["gross_profit"] == 25.0
    assert r["margin_pct"] == 33
    assert r["priced_count"] == 1 and r["total_count"] == 3
    statuses = {li["sku_code"]: li["status"] for li in r["lines"]}
    assert statuses == {"SKU1": "priced", "SKU2": "no_cost", "SKU3": "no_price"}


async def test_invoice_document_amount_includes_vat(
    api, session, _deals_v2_parties, _erp_invoice_command,
):
    """Счёт клиенту — С НДС: сумма документа (→ дебиторка/1С/KPI «Оплаты с НДС») = грандтотал
    печатной формы (нетто+НДС 20%), а не нетто. Решение оператора «с НДС» (PLATFORM #1)."""
    from decimal import Decimal

    from modules.integrations.models import StockItem
    from modules.sales.models import DealItem, PriceQuote
    from modules.sales.routes import _invoice_gross, _invoice_items, _invoice_line

    # чистая математика строки: 10×100 → нетто 1000, НДС 200, всего 1200
    assert _invoice_line(Decimal("10"), Decimal("100")) == (
        Decimal("1000.00"),
        Decimal("200.00"),
        Decimal("1200.00"),
    )

    sku1 = await _seed_sku(session, "VAT1")
    sku2 = await _seed_sku(session, "VAT2")
    await session.commit()
    deal = await _new_deal(api, "VAT-1", counterparty="ООО V")
    session.add_all([
        DealItem(deal_id=deal["id"], sku_id=sku1.id, qty=5, unit_price=15),  # 75 нетто → 90 с НДС
        DealItem(deal_id=deal["id"], sku_id=sku2.id, qty=3, unit_price=20),  # 60 нетто → 72 с НДС
        PriceQuote(sku_code="VAT1", counterparty="ООО V", price=15),
        PriceQuote(sku_code="VAT2", counterparty="ООО V", price=20),
        StockItem(sku_code="VAT1", qty_available=5, qty_reserved=0),
        StockItem(sku_code="VAT2", qty_available=3, qty_reserved=0),
    ])
    await session.commit()

    items = await _invoice_items(session, deal["id"])
    assert _invoice_gross(items) == Decimal("162.00")  # (75+15)+(60+12); нетто было бы 135

    issued = await api.post(f"/sales/deals/{deal['id']}/documents", json=await _erp_invoice_command(
        deal["id"], reserve_mode="stock",
    ))
    assert issued.status_code == 201, issued.text
    doc = issued.json()["document"]
    assert doc["amount"] == 162.0  # С НДС, не 135.0 нетто


async def test_deal_margin_facade_missing(api, session, _deals_v2_parties):
    """П1: фасад landed_cost None → cogs/gross_profit/margin_pct = None + reason."""
    from modules.sales.models import DealItem, PriceQuote

    sku = await _seed_sku(session, "SKU-X")
    deal = await _new_deal(api, "MGN-2", counterparty="ООО Y")
    session.add_all([
        DealItem(deal_id=deal["id"], sku_id=sku.id, qty=2),
        PriceQuote(sku_code="SKU-X", counterparty="ООО Y", price=50),
    ])
    await session.commit()
    app = api._transport.app  # type: ignore[attr-defined]

    app.state.core.services.landed_cost = None
    r = (await api.get(f"/sales/deals/{deal['id']}/margin")).json()
    assert r["cogs_landed"] is None and r["gross_profit"] is None and r["margin_pct"] is None
    assert "procurement" in (r["reason"] or "")


# ── П4: мульти-воронки в /board ────────────────────────────────────────────────
async def test_board_funnel_filter(api, _deals_v2_parties):
    await api.get("/sales/stages")  # материализовать канон всех воронок
    await _new_deal(api, "F-1", stage="new")  # default funnel = new_clients
    await _new_deal(api, "F-2", stage="rp_request", funnel="repeat_clients")
    b_new = (await api.get("/sales/board?funnel=new_clients")).json()
    b_rep = (await api.get("/sales/board?funnel=repeat_clients")).json()
    n_new = sum(st["count"] for st in b_new["stages"])
    n_rep = sum(st["count"] for st in b_rep["stages"])
    assert n_new == 1 and n_rep == 1
    cols_new = [st["id"] for st in b_new["stages"]]
    cols_rep = [st["id"] for st in b_rep["stages"]]
    assert "qual" in cols_new and "rp_request" in cols_rep
    assert "rp_request" not in cols_new


# ── Слайс 3: воронка «Тендеры» ──────────────────────────────────────────────────
async def test_board_funnel_tenders(api, _deals_v2_parties):
    await api.get("/sales/stages")  # материализовать канон всех воронок
    await _new_deal(api, "T-1", stage="tn_bidding", funnel="tenders")
    b_tn = (await api.get("/sales/board?funnel=tenders")).json()
    cols_tn = [st["id"] for st in b_tn["stages"]]
    assert cols_tn == ["tn_announced", "tn_submitted", "tn_bidding", "tn_won", "tn_lost"]
    n_tn = sum(st["count"] for st in b_tn["stages"])
    assert n_tn == 1

    funnels = (await api.get("/sales/funnels")).json()
    codes = {f["code"] for f in funnels}
    assert {"new_clients", "repeat_clients", "tenders"} <= codes


# ── П6: pipeline-аналитика ─────────────────────────────────────────────────────
async def test_pipeline_analytics(api, session, _deals_v2_parties):
    from modules.sales.models import Deal, DealStageEvent

    await api.get("/sales/stages")  # канон
    # 3 сделки: 2 в qual, 1 в won; 2 события new->qual
    for i, st in enumerate(("qual", "qual", "won"), start=1):
        await _new_deal(api, f"PA-{i}", stage=st)
    deals = (await session.execute(__import__("sqlalchemy").select(Deal))).scalars().all()
    # У каждой сделки в истории: ?→new (была в new), затем new→текущая (ушла из new).
    # Для won-сделки добавим ещё qual→won, чтобы проверить, что cycle/won считаются.
    for d in deals:
        session.add(DealStageEvent(deal_id=d.id, from_stage=None, to_stage="new"))
        session.add(DealStageEvent(deal_id=d.id, from_stage="new", to_stage=d.stage))
    await session.commit()
    r = (await api.get("/sales/pipeline/analytics?funnel=new_clients")).json()
    by_id = {st["id"]: st for st in r["stages"]}
    assert by_id["qual"]["count"] == 2
    assert by_id["won"]["count"] == 1
    # 3 сделки были в стадии "new" (через события); 2 из них ушли в qual → 67%
    # (3-я ушла в won через qual, поэтому new→qual = 3, но moved_to_next считает по парам
    # (new, qual) и берёт уникальные deal_id, значит 3, denom=3 → 100%).
    assert by_id["new"]["next_conv_pct"] is not None
    assert r["won_count"] == 1


# ── Период-срез конверсии/времени на стадии (pipeline/stage-metrics) ───────────
async def test_pipeline_stage_metrics_period_window(api, session, _deals_v2_parties):
    """entered_count/avg_time_days/conv_next_pct считаются только по сегментам,
    попавшим в окно periода — переход вне окна (SM-OLD) не портит статистику."""
    from datetime import timedelta

    from sqlalchemy import select

    from modules.sales.models import Deal, DealStageEvent

    deal_in = await _new_deal(api, "SM-1", stage="new")
    deal_old = await _new_deal(api, "SM-OLD", stage="new")

    d_in = (
        await session.execute(select(Deal).where(Deal.id == deal_in["id"]))
    ).scalar_one()
    d_old = (
        await session.execute(select(Deal).where(Deal.id == deal_old["id"]))
    ).scalar_one()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # SM-1: вошла в "new" 10 дней назад, ушла в "qual" 3 дня назад (5 дн длительность
    # была бы неверной — реально 7 дн) — внутри окна «месяц» (30 дн).
    d_in.created_at = now - timedelta(days=10)
    d_in.stage = "qual"
    session.add(DealStageEvent(deal_id=d_in.id, from_stage="new", to_stage="qual",
                                changed_at=now - timedelta(days=3)))
    # SM-OLD: переход был 90 дней назад — целиком вне окна «месяц», не должен всплыть.
    d_old.created_at = now - timedelta(days=120)
    d_old.stage = "qual"
    session.add(DealStageEvent(deal_id=d_old.id, from_stage="new", to_stage="qual",
                                changed_at=now - timedelta(days=90)))
    await session.commit()

    r = (await api.get("/sales/pipeline/stage-metrics?funnel=new_clients&period=month")).json()
    by_id = {st["id"]: st for st in r["stages"]}
    assert by_id["new"]["entered_count"] == 1  # только SM-1 (created_at в окне)
    assert by_id["new"]["completed_count"] == 1
    assert by_id["new"]["avg_time_days"] == 7.0
    assert by_id["new"]["conv_next_pct"] == 100

    # honest-empty: стадия без истории за период — None, не 0
    assert by_id["price_req"]["entered_count"] == 0
    assert by_id["price_req"]["avg_time_days"] is None
    assert by_id["price_req"]["conv_next_pct"] is None

    # Явный диапазон дат перекрывает period — окно расширили, SM-OLD теперь виден.
    d_from = (now - timedelta(days=200)).date().isoformat()
    d_to = now.date().isoformat()
    r2 = (
        await api.get(
            f"/sales/pipeline/stage-metrics?funnel=new_clients&date_from={d_from}&date_to={d_to}"
        )
    ).json()
    assert {st["id"]: st for st in r2["stages"]}["new"]["entered_count"] == 2


# ── П8: цикл плана draft→submit→decide + права ────────────────────────────────
async def test_plan_lifecycle_and_permissions(api):
    # 1) Создать draft
    plan = (await api.post(
        "/sales/plans",
        json={"owner_id": 1, "metric": "calls", "period_type": "month",
              "period_key": "2026-06", "target": 100},
    )).json()
    assert plan["status"] == "draft"
    # 2) Submit
    sent = (await api.post(f"/sales/plans/{plan['id']}/submit")).json()
    assert sent["status"] == "pending_approval"
    # 3) Approve как РОП (фикстура api по умолчанию director — super-роль)
    decided = (await api.post(
        f"/sales/plans/{plan['id']}/decide", json={"approved": True, "comment": "ok"}
    )).json()
    assert decided["status"] == "approved"
    # 4) Повторный decide на approved → 409
    assert (await api.post(
        f"/sales/plans/{plan['id']}/decide", json={"approved": False}
    )).status_code == 409


async def test_plan_decide_requires_approve_permission():
    """sales.deal.approve есть только у РОП/super; Менеджер не может decide."""
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from config.modules import ENABLED_MODULES
    from core.db.base import Base
    from core.runtime.app import create_app
    from core.runtime.deps import get_session

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True).execution_options(
        schema_translate_map={m: None for m in ENABLED_MODULES}
    )
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        app = create_app()

        async def _ovr():
            yield s

        app.dependency_overrides[get_session] = _ovr
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t",
                                headers={"X-User-Roles": "director"}) as c1:
            # Создаём план под super → submit
            p = (await c1.post(
                "/sales/plans",
                json={"owner_id": 1, "metric": "calls", "period_type": "month",
                      "period_key": "2026-06", "target": 50},
            )).json()
            await c1.post(f"/sales/plans/{p['id']}/submit")
        # Теперь под не-РОП ролью — decide должен быть 403. ASCII-роль "guest" не имеет
        # sales.deal.approve (она не из ROLES sales) → 403, что и проверяем.
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t",
                                headers={"X-User-Roles": "guest"}) as c2:
            r = await c2.post(f"/sales/plans/{p['id']}/decide", json={"approved": True})
        assert r.status_code == 403
    await engine.dispose()


# ── П10: handoff на win ────────────────────────────────────────────────────────
async def test_handoff_on_won(api, session, _deals_v2_parties):
    """sales.deal.handoff появляется в outbox после перевода сделки в won."""
    from sqlalchemy import select

    from core.domain.models import OutboxEvent
    from core.services.eventbus import EventContext
    app = api._transport.app  # type: ignore[attr-defined]
    from modules.sales.events import on_deal_won_handoff

    deal = await _new_deal(api, "HF-1", stage="invoice", counterparty="ООО Z")
    # Прямой вызов обработчика — relay в тестах не крутится автоматически.
    ctx = EventContext(session=session, services=app.state.core.services)
    await on_deal_won_handoff({"deal_id": deal["id"], "number": deal["number"]}, ctx)
    await session.commit()
    # Идемпотентность: повторный вызов не плодит второй handoff.
    await on_deal_won_handoff({"deal_id": deal["id"], "number": deal["number"]}, ctx)
    await session.commit()
    events = (
        await session.execute(
            select(OutboxEvent).where(OutboxEvent.event_type == "sales.deal.handoff")
        )
    ).scalars().all()
    handoffs = [e for e in events if e.payload.get("deal_id") == deal["id"]]
    assert len(handoffs) == 1
    payload = handoffs[0].payload
    assert payload["counterparty"] == "ООО Z"
    assert payload["funnel"] == "new_clients"

    # GET /handoff отдаёт сводку
    r = (await api.get(f"/sales/deals/{deal['id']}/handoff")).json()
    assert r is not None and r["counterparty"] == "ООО Z"


# ── S3-1: взвешенный прогноз ВАЛОВОЙ МАРЖИ воронки ──────────────────────────────
async def test_margin_forecast_weighted_gross(api, session, _deals_v2_parties):
    """S3-1: revenue/gross взвешены на вероятность; deals_priced=1/2 (priced + no_cost)."""
    from modules.sales.models import DealItem, PriceQuote

    sku1 = await _seed_sku(session, "SKU1", "A1")  # landed=10 в _FakeLanded
    sku2 = await _seed_sku(session, "SKU2", "A2")  # landed=None → no_cost
    a = await _new_deal(api, "MF-1", counterparty="ООО X", probability=40)
    b = await _new_deal(api, "MF-2", counterparty="ООО X", probability=10)
    session.add_all([
        DealItem(deal_id=a["id"], sku_id=sku1.id, qty=5, unit_price=15),   # priced: выручка 75, gross 25
        DealItem(deal_id=b["id"], sku_id=sku2.id, qty=3, unit_price=20),   # no_cost: выручка 60, без gross
        PriceQuote(sku_code="SKU1", counterparty="ООО X", price=15),
        PriceQuote(sku_code="SKU2", counterparty="ООО X", price=20),
    ])
    await session.commit()
    app = api._transport.app  # type: ignore[attr-defined]
    app.state.core.services.landed_cost = _FakeLanded()
    try:
        r = (await api.get("/sales/pipeline/margin-forecast?funnel=new_clients")).json()
    finally:
        app.state.core.services.landed_cost = None
    # выручка взвеш = 75*0.40 + 60*0.10 = 36.0; gross взвеш = 25*0.40 = 10.0
    assert r["revenue_weighted"] == 36.0
    assert r["gross_weighted"] == 10.0
    assert r["margin_pct_blended"] == 28  # round(10/36*100)
    assert r["deals_priced"] == 1 and r["deals_total"] == 2
    assert r["reason"] is None


async def test_margin_forecast_facade_missing(api, session, _deals_v2_parties):
    """S3-1: фасада landed нет → gross_weighted=null + reason, выручка остаётся числом."""
    from modules.sales.models import DealItem, PriceQuote

    sku1 = await _seed_sku(session, "SKU1", "A1")
    a = await _new_deal(api, "MF-3", counterparty="ООО Y", probability=50)
    session.add_all([
        DealItem(deal_id=a["id"], sku_id=sku1.id, qty=4, unit_price=10),
        PriceQuote(sku_code="SKU1", counterparty="ООО Y", price=10),
    ])
    await session.commit()
    app = api._transport.app  # type: ignore[attr-defined]
    app.state.core.services.landed_cost = None
    r = (await api.get("/sales/pipeline/margin-forecast?funnel=new_clients")).json()
    assert r["gross_weighted"] is None          # НЕ 0
    assert r["revenue_weighted"] == 20.0        # 10*4*0.50 — не зависит от landed
    assert r["margin_pct_blended"] is None
    assert r["deals_priced"] == 0
    assert "procurement" in (r["reason"] or "")


# ── S3-3: procurement.received → sales.supply.arrived ───────────────────────────
async def test_procurement_received_signals_active_deals(api, session, _deals_v2_parties):
    """S3-3: поставка по SKU активной сделки → sales.supply.arrived; payload без sku не валит."""
    from sqlalchemy import select

    from core.domain.models import OutboxEvent
    from core.services.eventbus import EventContext
    from modules.sales.events import on_procurement_received
    from modules.sales.models import Deal, DealItem

    app = api._transport.app  # type: ignore[attr-defined]
    sku1 = await _seed_sku(session, "SKU1", "A1")
    active = await _new_deal(api, "SUP-1", stage="qual")
    closed = await _new_deal(api, "SUP-2", stage="qual")
    session.add_all([
        DealItem(deal_id=active["id"], sku_id=sku1.id, qty=2),
        DealItem(deal_id=closed["id"], sku_id=sku1.id, qty=1),
    ])
    await session.commit()
    cobj = await session.get(Deal, closed["id"])
    cobj.stage = "won"  # терминал — не сигналим
    await session.commit()

    ctx = EventContext(session=session, services=app.state.core.services)
    # payload без sku → ранний выход, ничего не эмитим, не падаем
    await on_procurement_received({"qty": "5"}, ctx)
    await session.commit()
    # поставка SKU1 → сигнал только на активную сделку
    await on_procurement_received(
        {"sku_code": "SKU1", "qty": "5", "entity_ref": "purchase:7"}, ctx
    )
    await session.commit()

    evs = (await session.execute(
        select(OutboxEvent).where(OutboxEvent.event_type == "sales.supply.arrived")
    )).scalars().all()
    assert len(evs) == 1
    p = evs[0].payload
    assert p["sku_code"] == "SKU1" and p["qty"] == "5"
    assert active["id"] in p["deal_ids"] and closed["id"] not in p["deal_ids"]


# ── S3-4: сверка маржи sales ↔ finance (sku-агрегат) ────────────────────────────
async def test_margin_reconcile_with_and_without_finance(api, session, _deals_v2_parties):
    """S3-4: без landed-событий → no_finance; с аудитом → delta/converged; actual бьёт estimated."""
    from core.domain.models import OutboxEvent
    from modules.sales.models import DealItem, PriceQuote

    sku1 = await _seed_sku(session, "SKU1", "A1")
    deal = await _new_deal(api, "RC-1", counterparty="ООО R")
    session.add_all([
        DealItem(deal_id=deal["id"], sku_id=sku1.id, qty=5, unit_price=15),
        PriceQuote(sku_code="SKU1", counterparty="ООО R", price=15),
    ])
    await session.commit()
    app = api._transport.app  # type: ignore[attr-defined]
    app.state.core.services.landed_cost = _FakeLanded()  # SKU1 landed=10 → sales gross=(15-10)*5=25
    try:
        # 1) нет landed-событий → no_finance, sales-сторона посчитана
        r0 = (await api.get(f"/sales/deals/{deal['id']}/margin/reconcile")).json()
        assert r0["status"] == "no_finance"
        assert r0["finance_actual_gross"] is None
        assert r0["sales_forecast_gross"] == 25.0
        assert r0["level"] == "sku_aggregate"
        # 2) аудит landed=10 → finance gross=(15-10)*5=25 → converged
        session.add(OutboxEvent(
            event_type="procurement.landed_cost.calculated",
            payload={"sku_code": "SKU1", "unit_landed_cost_byn": "10.00", "qty": "5",
                     "stage": "estimated", "entity_ref": "purchase_order:1"},
        ))
        await session.commit()
        r1 = (await api.get(f"/sales/deals/{deal['id']}/margin/reconcile")).json()
        assert r1["finance_actual_gross"] == 25.0 and r1["delta"] == 0.0
        assert r1["status"] == "converged"
        # 3) более позднее actual=12 бьёт estimated → finance gross=(15-12)*5=15, delta=10 → diverged
        session.add(OutboxEvent(
            event_type="procurement.landed_cost.calculated",
            payload={"sku_code": "SKU1", "unit_landed_cost_byn": "12.00", "qty": "5",
                     "stage": "actual", "entity_ref": "purchase_order:1"},
        ))
        await session.commit()
        r2 = (await api.get(f"/sales/deals/{deal['id']}/margin/reconcile")).json()
        assert r2["finance_actual_gross"] == 15.0 and r2["delta"] == 10.0
        assert r2["status"] == "diverged"
    finally:
        app.state.core.services.landed_cost = None


# ── S3-5: согласованный план РОП → цель скорборда (KpiTarget) ───────────────────
async def test_plan_approved_upserts_kpi_target(api, session):
    """S3-5: approve по метрике скорборда → KpiTarget.target=план; метрика вне скорборда — игнор."""
    from decimal import Decimal

    from sqlalchemy import select

    from core.services.eventbus import EventContext
    from modules.sales.events import on_plan_approved
    from modules.sales.models import KpiTarget

    app = api._transport.app  # type: ignore[attr-defined]
    session.add(KpiTarget(key="calls", title="Звонки", target=Decimal("20"),
                          unit="count", icon="phone", tone="neutral", sort_order=1))
    await session.commit()
    ctx = EventContext(session=session, services=app.state.core.services)

    await on_plan_approved({"metric": "calls", "target": 30.0, "period_type": "day",
                            "period_key": "2026-06-12", "owner_id": 1}, ctx)
    await session.commit()
    kpi = (await session.execute(
        select(KpiTarget).where(KpiTarget.key == "calls")
    )).scalars().first()
    assert float(kpi.target) == 30.0
    rows = (await api.get("/sales/kpis?period=day")).json()
    calls_row = next(r for r in rows if r["key"] == "calls")
    assert calls_row["target"] == 30.0

    # план МЕСЯЦА нормализуется в дневной seed (÷ рабочих дней), /kpis?period=month отдаёт итог
    session.add(KpiTarget(key="leads", title="Лиды", target=Decimal("5"),
                          unit="count", icon="user", tone="neutral", sort_order=2))
    await session.commit()
    await on_plan_approved({"metric": "leads", "target": 440.0, "period_type": "month",
                            "period_key": "2026-06", "owner_id": 1}, ctx)
    await session.commit()
    leads_kpi = (await session.execute(
        select(KpiTarget).where(KpiTarget.key == "leads")
    )).scalars().first()
    assert float(leads_kpi.target) == 20.0  # 440 / 22 рабочих дней месяца
    rows_m = (await api.get("/sales/kpis?period=month")).json()
    leads_row = next(r for r in rows_m if r["key"] == "leads")
    assert leads_row["target"] == 440.0  # 20 × 22 — план месяца не раздут

    # кривой target не валит обработчик и не меняет цель (poison-pill guard для шины)
    await on_plan_approved({"metric": "calls", "target": "n/a", "period_type": "day",
                            "period_key": "2026-06-12", "owner_id": 1}, ctx)
    await session.commit()
    calls_kpi = (await session.execute(
        select(KpiTarget).where(KpiTarget.key == "calls")
    )).scalars().first()
    assert float(calls_kpi.target) == 30.0  # не изменилось

    # метрика вне скорборда — строку не создаём, не падаем
    await on_plan_approved({"metric": "tenders_count", "target": 5.0, "period_type": "day",
                            "period_key": "2026-06-12", "owner_id": 1}, ctx)
    await session.commit()
    absent = (await session.execute(
        select(KpiTarget).where(KpiTarget.key == "tenders_count")
    )).scalars().first()
    assert absent is None


# ── /sales/kpis?period=YYYY-MM: произвольный месяц ──────────────────────────────
async def test_kpis_arbitrary_month_aggregates_only_that_month(session, api):
    """period=2026-05 агрегирует Activity только за май 2026, апрель/июнь не подмешиваются."""
    from decimal import Decimal

    from modules.sales.models import Activity, KpiTarget

    session.add(KpiTarget(key="calls", title="Звонки", target=Decimal("20"),
                          unit="count", icon="phone", tone="neutral", sort_order=1))
    session.add(Activity(kpi_key="calls", value=Decimal("3"), date=date(2026, 4, 30)))
    session.add(Activity(kpi_key="calls", value=Decimal("5"), date=date(2026, 5, 1)))
    session.add(Activity(kpi_key="calls", value=Decimal("7"), date=date(2026, 5, 31)))
    session.add(Activity(kpi_key="calls", value=Decimal("11"), date=date(2026, 6, 1)))
    await session.commit()

    rows = (await api.get("/sales/kpis?period=2026-05")).json()
    calls_row = next(r for r in rows if r["key"] == "calls")
    assert calls_row["actual"] == 12.0  # только 5+7 (апрель/июнь не подмешаны)
    # план: 20/день × число рабочих дней мая-2026 (21 будний день пн-пт)
    assert calls_row["target"] == 20.0 * 21


async def test_kpis_invalid_period_does_not_crash(api):
    """Невалидный period (не relative-ключ и не YYYY-MM) — честный фоллбэк, не 500."""
    # "0000-01" — год < 1 (date() кинул бы ValueError, если год не валидировать) — тоже фоллбэк.
    for bad_period in ("2026-13", "foo", "2026-5", "0000-01", "0000-13"):
        r = await api.get(f"/sales/kpis?period={bad_period}")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ── Крайняя дата отгрузки + штраф за опоздание → сигнал в закупки ───────────────
async def test_deal_ship_deadline_and_penalty_persist(api, _deals_v2_parties):
    """Поля крайней даты и штрафа сохраняются при создании и обновлении сделки."""
    deal = await _new_deal(
        api, "SD-1", ship_deadline="2026-07-15",
        penalty_rate_pct=0.1, penalty_cap_pct=10, penalty_terms="0.1%/день, макс 10%",
    )
    assert deal["ship_deadline"] == "2026-07-15"
    assert deal["penalty_rate_pct"] == 0.1
    assert deal["penalty_cap_pct"] == 10
    assert deal["penalty_terms"] == "0.1%/день, макс 10%"

    upd = (await api.patch(
        f"/sales/deals/{deal['id']}", json={"ship_deadline": "2026-07-20"}
    )).json()
    assert upd["ship_deadline"] == "2026-07-20"
    got = (await api.get(f"/sales/deals/{deal['id']}")).json()
    assert got["ship_deadline"] == "2026-07-20"


async def test_ship_deadline_emits_to_procurement(api, session, _deals_v2_parties):
    """Выставление/смена крайней даты → sales.deal.ship_deadline.set (дата+штраф+позиции)."""
    from sqlalchemy import select

    from core.domain.models import OutboxEvent
    from modules.sales.models import DealItem

    sku = await _seed_sku(session, "SKU-SD", "Товар к сроку")
    deal = await _new_deal(api, "SD-2", counterparty="ООО Срок")
    session.add(DealItem(deal_id=deal["id"], sku_id=sku.id, qty=4))
    await session.commit()

    await api.patch(f"/sales/deals/{deal['id']}", json={
        "ship_deadline": "2026-08-01", "penalty_rate_pct": 0.5,
        "penalty_cap_pct": 15, "penalty_terms": "0.5%/день",
    })
    evs = (await session.execute(
        select(OutboxEvent).where(OutboxEvent.event_type == "sales.deal.ship_deadline.set")
    )).scalars().all()
    assert len(evs) == 1
    p = evs[0].payload
    assert p["deal_id"] == deal["id"]
    assert p["ship_deadline"] == "2026-08-01"
    assert p["penalty_rate_pct"] == 0.5 and p["penalty_cap_pct"] == 15
    assert p["counterparty"] == "ООО Срок"
    assert any(it["sku_code"] == "SKU-SD" and it["qty"] == 4 for it in p["items"])

    # та же дата повторно → нового сигнала нет (эмит только на смену)
    await api.patch(f"/sales/deals/{deal['id']}", json={"ship_deadline": "2026-08-01"})
    # PATCH другого поля → тоже не эмитит
    await api.patch(f"/sales/deals/{deal['id']}", json={"title": "Переименовал"})
    evs2 = (await session.execute(
        select(OutboxEvent).where(OutboxEvent.event_type == "sales.deal.ship_deadline.set")
    )).scalars().all()
    assert len(evs2) == 1


async def test_penalty_out_of_range_rejected(api, _deals_v2_parties):
    """Штраф вне диапазона режется в 422 на валидации, а не падает в 500 (overflow колонок БД)."""
    # ставка > Numeric(6,2) предела (9999.99) → 422
    r = await api.post("/sales/deals", json={
        "number": "PN-1", "title": "t", "counterparty": "c", "penalty_rate_pct": 99999,
    })
    assert r.status_code == 422
    # отрицательная ставка → 422
    r2 = await api.post("/sales/deals", json={
        "number": "PN-2", "title": "t", "counterparty": "c", "penalty_rate_pct": -1,
    })
    assert r2.status_code == 422
    # примечание длиннее String(512) → 422
    deal = await _new_deal(api, "PN-3")
    r3 = await api.patch(f"/sales/deals/{deal['id']}", json={"penalty_terms": "x" * 513})
    assert r3.status_code == 422


# ── повтор прошлого заказа ──────────────────────────────────────────────────

async def test_repeat_last_order_returns_prior_deal_items(api, session, _deals_v2_parties):
    """Вторая сделка того же контрагента → позиции подтягиваются из первой (с позициями)."""
    from modules.sales.models import DealItem

    sku1 = await _seed_sku(session, "RLO-1", "Товар 1")
    sku2 = await _seed_sku(session, "RLO-2", "Товар 2")
    first = await _new_deal(api, "RLO-D1", counterparty="ООО Повтор")
    session.add_all([
        DealItem(deal_id=first["id"], sku_id=sku1.id, qty=5),
        DealItem(deal_id=first["id"], sku_id=sku2.id, qty=3),
    ])
    await session.commit()
    second = await _new_deal(api, "RLO-D2", counterparty="ООО Повтор")

    r = await api.get(f"/sales/deals/{second['id']}/repeat-last-order")
    assert r.status_code == 200
    items = r.json()
    assert {(i["code"], i["qty"]) for i in items} == {("RLO-1", 5.0), ("RLO-2", 3.0)}


async def test_repeat_last_order_empty_when_no_prior_deals(api, _deals_v2_parties):
    """Нет предыдущих сделок контрагента с позициями → пустой список, статус 200."""
    deal = await _new_deal(api, "RLO-D3", counterparty="ООО Без Истории")
    r = await api.get(f"/sales/deals/{deal['id']}/repeat-last-order")
    assert r.status_code == 200
    assert r.json() == []


async def test_repeat_last_order_404_for_missing_deal(api):
    """Несуществующая сделка → 404."""
    r = await api.get("/sales/deals/999999/repeat-last-order")
    assert r.status_code == 404


async def test_repeat_last_order_ignores_newer_parallel_deal(api, session, _deals_v2_parties):
    """Повтор берёт ПРЕДЫДУЩУЮ сделку (id меньше), а не более новую параллельную.

    Регрессия из code-review: раньше выбиралась «последняя другая» по created_at без
    условия «раньше текущей» → черновик более новой параллельной сделки подменял
    реально заказанное из прошлой.
    """
    from modules.sales.models import DealItem

    old_sku = await _seed_sku(session, "RLO-OLD", "Старый заказ")
    new_sku = await _seed_sku(session, "RLO-NEW", "Черновик новее")
    first = await _new_deal(api, "RLO-P1", counterparty="ООО Параллель")  # прошлый заказ
    session.add(DealItem(deal_id=first["id"], sku_id=old_sku.id, qty=2))
    await session.commit()
    middle = await _new_deal(api, "RLO-P2", counterparty="ООО Параллель")  # текущая (звоним по ней)
    newer = await _new_deal(api, "RLO-P3", counterparty="ООО Параллель")  # созданная ПОЗЖЕ
    session.add(DealItem(deal_id=newer["id"], sku_id=new_sku.id, qty=9))
    await session.commit()

    items = (await api.get(f"/sales/deals/{middle['id']}/repeat-last-order")).json()
    # только позиции ПРЕДЫДУЩЕЙ сделки (first), не черновик более новой (newer)
    assert {i["code"] for i in items} == {"RLO-OLD"}


# ── Журнал продаж (GET /sales/journal) ──────────────────────────────────────────

async def test_journal_only_won_deals(api, _deals_v2_parties):
    """Журнал отдаёт ТОЛЬКО won-сделки — активная и отказная в реестр не попадают."""
    active = await _new_deal(api, "JRN-ACT", amount=100)
    lost = await _new_deal(api, "JRN-LST", amount=200)
    await api.post(f"/sales/deals/{lost['id']}/lose", json={"reason_code": "price"})
    won = await _new_deal(api, "JRN-WON", amount=300)
    await api.post(f"/sales/deals/{won['id']}/win")

    rows = (await api.get("/sales/journal")).json()
    ids = {r["deal_id"] for r in rows}
    assert won["id"] in ids
    assert active["id"] not in ids
    assert lost["id"] not in ids


async def test_journal_funnel_aware_repeat_clients(api, _deals_v2_parties):
    """Сделка repeat_clients, выигранная через /win (стадия ``rp_won``, не литерал "won"),
    попадает в журнал с funnel=repeat_clients — тот же класс бага, что Фикс 1 win/lose."""
    await api.get("/sales/stages")  # материализовать канон всех воронок
    deal = await _new_deal(api, "JRN-RP-1", stage="rp_request", funnel="repeat_clients", amount=500)
    r = await api.post(f"/sales/deals/{deal['id']}/win")
    assert r.json()["stage"] == "rp_won"

    rows = (await api.get("/sales/journal")).json()
    row = next(x for x in rows if x["deal_id"] == deal["id"])
    assert row["funnel"] == "repeat_clients"


async def test_journal_payment_paid_and_none(session, api, _deals_v2_parties, _erp_invoice_command):
    """Оплаченный счёт → payment="paid"+invoice_number; сделка без счетов → payment="none"."""
    from core.services.eventbus import EventContext
    from modules.accounting.models import Account, Policy
    from modules.sales.events import on_payment_paid
    from modules.sales.models import DealDocument
    from tests.accounting.test_invoice_settlements import bank

    paid_deal = await _new_deal(api, "JRN-PAY-1", amount=1000)
    sku = await _seed_sku(session, "JRN-PAID-GOODS")
    await session.commit()
    item = await api.post(f"/sales/deals/{paid_deal['id']}/items", json={
        "sku_id": sku.id, "qty": 1, "unit_price": "833.33",
    })
    assert item.status_code == 201, item.text
    doc = (
        await api.post(f"/sales/deals/{paid_deal['id']}/documents", json=await _erp_invoice_command(
            paid_deal["id"], reserve_mode="stock",
        ))
    )
    assert doc.status_code == 201, doc.text
    issued = doc.json()
    org_id = issued["organization_id"]
    doc = issued["document"]
    await on_payment_paid({"ref": doc["number"]}, EventContext(session, None))
    await session.commit()
    # A legacy ref-only event cannot establish payment for a current ERP invoice.
    assert (await session.get(DealDocument, doc["id"])).status == "issued"
    policy = Policy(
        organization_id=org_id, effective_from=date(2026, 1, 1), reference="TEST ONLY",
        inventory_method="specific", allocation_basis="direct_cost",
        depreciation_method="straight_line", normative_reference="synthetic fixture",
        normative_verified=True, approved_by="issuer",
    )
    session.add(policy)
    for code, cash in (("51", True), ("62", False)):
        session.add(Account(
            organization_id=org_id, code=code, title="Synthetic", category="asset",
            valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=True,
            quantity_tracking=False, cash=cash, normative_ref="synthetic",
        ))
    await session.commit()
    amount = format(Decimal(str(doc["amount"])), ".2f")
    bank_entry = await bank(api, (org_id, policy.id), doc["id"], "journal-paid", amount=amount)
    invoice_url = f"/sales/organizations/{org_id}/invoices/{doc['id']}"
    settlement = await api.post(invoice_url + "/settlements", json={
        "bank_entry_id": bank_entry, "source_key": "journal-paid", "amount": amount,
        "evidence": "Synthetic posted bank receipt and exact invoice allocation",
    })
    assert settlement.status_code == 201, settlement.text
    basis = await api.get(invoice_url + "/money-basis")
    assert basis.status_code == 200, basis.text
    assert basis.json()["money_state"] == "funds_held"
    settlements = await api.get(invoice_url + "/settlements")
    assert settlements.status_code == 200, settlements.text
    assert Decimal(settlements.json()["net_received"]) == Decimal(amount)
    await api.post(f"/sales/deals/{paid_deal['id']}/win")

    unpaid_deal = await _new_deal(api, "JRN-PAY-2", amount=500)
    await api.post(f"/sales/deals/{unpaid_deal['id']}/win")

    rows = (await api.get("/sales/journal")).json()
    paid_row = next(r for r in rows if r["deal_id"] == paid_deal["id"])
    unpaid_row = next(r for r in rows if r["deal_id"] == unpaid_deal["id"])
    assert paid_row["payment"] == "paid"
    assert paid_row["invoice_number"] == doc["number"]
    assert unpaid_row["payment"] == "none"
    assert unpaid_row["invoice_number"] is None


async def test_journal_sorted_by_closed_on_desc(session, api, _deals_v2_parties):
    """Сортировка реестра: closed_on DESC (свежезакрытые — первыми)."""
    from sqlalchemy import select

    from modules.sales.models import Deal

    old = await _new_deal(api, "JRN-OLD", amount=10)
    await api.post(f"/sales/deals/{old['id']}/win")
    new = await _new_deal(api, "JRN-NEW", amount=20)
    await api.post(f"/sales/deals/{new['id']}/win")

    old_obj = (await session.execute(select(Deal).where(Deal.id == old["id"]))).scalar_one()
    new_obj = (await session.execute(select(Deal).where(Deal.id == new["id"]))).scalar_one()
    old_obj.closed_date = "01.01.2026"
    new_obj.closed_date = "10.07.2026"
    await session.commit()

    rows = (await api.get("/sales/journal")).json()
    ids = [r["deal_id"] for r in rows if r["deal_id"] in (old["id"], new["id"])]
    assert ids == [new["id"], old["id"]]  # DESC по closed_on


async def test_journal_honest_margin_without_facade(session, api, _deals_v2_parties):
    """Честная деградация: без фасада landed_cost margin_pct is None + margin_reason непустой
    (НЕ 0 — дефолт тестового ядра, core.services.landed_cost is None, пока не подменён стендом)."""
    from modules.sales.models import DealItem

    sku = await _seed_sku(session, "JRN-SKU")
    deal = await _new_deal(api, "JRN-MGN-1", counterparty="ООО Журнал", amount=400)
    session.add(DealItem(deal_id=deal["id"], sku_id=sku.id, qty=1))
    await session.commit()
    await api.post(f"/sales/deals/{deal['id']}/win")

    rows = (await api.get("/sales/journal")).json()
    row = next(r for r in rows if r["deal_id"] == deal["id"])
    assert row["revenue"] is None
    assert row["gross_profit"] is None
    assert row["margin_pct"] is None
    assert row["margin_reason"]


# ── Конструктор месячного плана продавца (GET /plan-sources, PUT /plan-items) ────

async def test_plan_sources_regulars_cycle_and_single_order(session, api, _deals_v2_parties):
    """≥2 won-заказа одного контрагента → цикл перезаказа (среднее интервалов) и ожидание
    следующего в месяце; контрагент с 1 заказом — cycle_days/expected пусты, in_month=False."""
    from sqlalchemy import select

    from modules.sales.models import Deal

    d1 = await _new_deal(api, "REG-1", counterparty="Постоянный", amount=1000)
    await api.post(f"/sales/deals/{d1['id']}/win")
    d2 = await _new_deal(api, "REG-2", counterparty="Постоянный", amount=1000)
    await api.post(f"/sales/deals/{d2['id']}/win")
    obj1 = (await session.execute(select(Deal).where(Deal.id == d1["id"]))).scalar_one()
    obj2 = (await session.execute(select(Deal).where(Deal.id == d2["id"]))).scalar_one()
    obj1.closed_date = "10.01.2026"
    obj2.closed_date = "10.03.2026"

    d3 = await _new_deal(api, "REG-3", counterparty="Одноразовый", amount=500)
    await api.post(f"/sales/deals/{d3['id']}/win")
    obj3 = (await session.execute(select(Deal).where(Deal.id == d3["id"]))).scalar_one()
    obj3.closed_date = "01.02.2026"
    await session.commit()

    rows = (await api.get("/sales/plan-sources", params={"month": "2026-05"})).json()
    by_cp = {r["counterparty"]: r for r in rows["regulars"]}

    regular = by_cp["Постоянный"]
    assert regular["orders_count"] == 2
    assert 58 <= regular["cycle_days"] <= 60
    assert regular["expected"].startswith("2026-05")
    assert regular["in_month"] is True

    single = by_cp["Одноразовый"]
    assert single["orders_count"] == 1
    assert single["cycle_days"] is None
    assert single["expected"] is None
    assert single["in_month"] is False


@pytest.mark.parametrize(
    ("closed_dates", "cycle_days", "expected", "in_month"),
    [
        (["10.01.2026", "10.01.2026"], None, None, False),
        (["10.01.2026", "10.01.2026", "10.03.2026"], 59, "2026-05-08", True),
        (["10.01.2026", "10.03.2026", "10.03.2026", "09.05.2026"], 60, "2026-07-08", False),
    ],
    ids=["same-day-only", "duplicate-first-day", "duplicate-middle-day"],
)
async def test_plan_sources_cycle_uses_distinct_dates(
    session, api, _deals_v2_parties, closed_dates, cycle_days, expected, in_month,
):
    """Several real won deals on one date count as deals, not zero-day intervals."""
    from modules.sales.models import Deal

    for index, closed_on in enumerate(closed_dates, 1):
        deal = await _new_deal(api, f"REG-DATES-{index}", counterparty="Постоянный", amount=1000)
        won = await api.post(f"/sales/deals/{deal['id']}/win")
        assert won.status_code == 200, won.text
        row = await session.get(Deal, deal["id"])
        row.closed_date = closed_on
    await session.commit()

    response = await api.get("/sales/plan-sources", params={"month": "2026-05"})
    assert response.status_code == 200, response.text
    regular = next(row for row in response.json()["regulars"] if row["counterparty"] == "Постоянный")
    assert regular["orders_count"] == len(closed_dates)
    assert regular["last_order"] == ("2026-05-09" if len(closed_dates) == 4 else
                                     "2026-03-10" if len(closed_dates) == 3 else "2026-01-10")
    assert regular["cycle_days"] == cycle_days
    assert regular["expected"] == expected
    assert regular["in_month"] is in_month
    assert regular["avg_check"] == 1000


async def test_plan_sources_committed_open_only(api, _deals_v2_parties):
    """committed отдаёт ОТКРЫТУЮ сделку с expected_close_date в месяце; won-сделку — нет."""
    open_deal = await _new_deal(api, "CMT-1", amount=800, expected_close_date="15.08.2026")
    won_deal = await _new_deal(api, "CMT-2", amount=900, expected_close_date="20.08.2026")
    await api.post(f"/sales/deals/{won_deal['id']}/win")

    rows = (await api.get("/sales/plan-sources", params={"month": "2026-08"})).json()
    refs = {c["ref"] for c in rows["committed"]}
    assert f"deal:{open_deal['id']}" in refs
    assert f"deal:{won_deal['id']}" not in refs


async def test_plan_items_replace_all_snapshot(api):
    """PUT /plan-items — снапшот-замена: 2 строки → saved_items==2; 1 строка → стало 1."""
    owner_id, period = 501, "2026-08"
    row_a = {"source": "committed", "ref": "deal:1", "title": "A", "when_label": "закрытие ~15.08",
             "revenue": 1000, "gross": 200, "probability": 70, "enabled": True}
    row_b = {"source": "regular", "ref": "cp:Клиент", "title": "Клиент", "when_label": "",
             "revenue": 500, "gross": 100, "probability": 60, "enabled": True}

    put1 = await api.put(
        "/sales/plan-items", params={"owner_id": owner_id, "period_key": period},
        json=[row_a, row_b],
    )
    assert put1.status_code == 200
    assert len(put1.json()) == 2

    src1 = (await api.get(
        "/sales/plan-sources", params={"month": period, "owner_id": owner_id}
    )).json()
    assert len(src1["saved_items"]) == 2

    put2 = await api.put(
        "/sales/plan-items", params={"owner_id": owner_id, "period_key": period}, json=[row_a],
    )
    assert len(put2.json()) == 1

    src2 = (await api.get(
        "/sales/plan-sources", params={"month": period, "owner_id": owner_id}
    )).json()
    assert len(src2["saved_items"]) == 1


async def test_plan_sources_base_gross_from_approved_plan(api):
    """base_gross — согласованный (approved) PlanTarget gross_profit за месяц владельца."""
    owner_id, month = 502, "2026-09"
    plan = (await api.post(
        "/sales/plans",
        json={"owner_id": owner_id, "metric": "gross_profit", "period_type": "month",
              "period_key": month, "target": 15000},
    )).json()
    await api.post(f"/sales/plans/{plan['id']}/submit")
    await api.post(f"/sales/plans/{plan['id']}/decide", json={"approved": True})

    src = (await api.get(
        "/sales/plan-sources", params={"month": month, "owner_id": owner_id}
    )).json()
    assert src["base_gross"] == 15000.0


async def test_plan_sources_invalid_month_422(api):
    """Кривой month → 422 на GET /plan-sources и на PUT /plan-items (period_key)."""
    bad_get = await api.get("/sales/plan-sources", params={"month": "2026-13"})
    assert bad_get.status_code == 422

    bad_put = await api.put(
        "/sales/plan-items", params={"owner_id": 1, "period_key": "not-a-month"}, json=[]
    )
    assert bad_put.status_code == 422
