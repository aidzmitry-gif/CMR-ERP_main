"""SALES-53: договор по шаблону + реквизиты по УНП + пакет «счёт + договор»."""
from decimal import Decimal

import pytest
from sqlalchemy import select

from core.domain.models import Counterparty, Sku
from modules.integrations.models import StockItem
from modules.sales.models import DealItem, PriceQuote

TEMPLATE_BODY = (
    "ДОГОВОР {{number}}\n"
    "Продавец: {{seller.name}}, УНП {{seller.unp}}\n"
    "Покупатель: {{buyer.name}}, УНП {{buyer.unp}}, {{buyer.address}}\n"
    "Спецификация: {{items}}\n"
    "Сумма: {{total}}\n"
    "Оплата: {{payment_terms}}\n"
)


async def _make_template(api):
    r = await api.post(
        "/sales/contract-templates",
        json={"code": "supply", "name": "Поставка товара", "body": TEMPLATE_BODY},
    )
    assert r.status_code == 201, r.text


async def _make_deal(api, counterparty="ООО «Аккумулятор»"):
    r = await api.post(
        "/sales/deals",
        json={"number": "D-53", "title": "Поставка АКБ", "counterparty": counterparty},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


async def _package_deal(api, session, *, counterparty):
    """A package requires a real priced goods line before invoice issuance."""
    session.add(Counterparty(name=counterparty))
    await session.commit()
    deal = await _make_deal(api, counterparty=counterparty)
    sku = Sku(code="PACKAGE-GOODS", title="Synthetic package goods", unit="шт")
    session.add(sku)
    await session.flush()
    session.add(DealItem(deal_id=deal["id"], sku_id=sku.id, qty=Decimal("1"), unit_price=Decimal("100")))
    session.add(PriceQuote(sku_code=sku.code, counterparty=counterparty, price=Decimal("100")))
    await session.commit()
    return deal


async def _scoped_invoice_request(api, session, deal):
    """Use the same explicit seller/buyer/stock protocol as invoice acceptance tests."""
    from modules.accounting.models import AccessGrant, Organization
    from modules.sales.accounting_ownership import DealOwnership
    from modules.sales.client_document_register import DealClientBinding, preview_snapshot
    from modules.sales.models import Deal
    from modules.wms.models import StockMovement, WarehouseDirectory

    actor = "contract-fixture"
    api.headers["X-User"] = actor
    source = await session.get(Deal, deal["id"])
    buyer = await session.get(Counterparty, source.counterparty_id)
    assert buyer is not None
    config = api._transport.app.state.core.config
    org = Organization(name=config.seller_name, unp=config.seller_unp)
    session.add(org)
    await session.flush()
    session.add(AccessGrant(organization_id=org.id, subject=actor, role="chief"))
    session.add(DealOwnership(deal_id=source.id, organization_id=org.id, snapshot={},
                              evidence="Synthetic contract ownership", actor=actor))
    await session.flush()
    session.add(DealClientBinding(deal_id=source.id, organization_id=org.id, counterparty_id=buyer.id,
        snapshot=await preview_snapshot(session, org.id, source, buyer.id), evidence="Synthetic exact buyer", actor=actor))
    session.add(WarehouseDirectory(organization_id=org.id, name="W", title="Synthetic contract warehouse",
                                   created_by=actor, wms_enabled=False, prohibit_negative_stock=True))
    rows = (await session.execute(select(DealItem, Sku).join(Sku, Sku.id == DealItem.sku_id)
                                  .where(DealItem.deal_id == source.id).order_by(DealItem.id))).all()
    pricing = []
    for item, sku in rows:
        session.add(StockMovement(organization_id=org.id, sku_code=sku.code, warehouse="W", kind="in",
                                  qty=item.qty, reason="receipt"))
        quote = await session.scalar(select(PriceQuote).where(PriceQuote.sku_code == sku.code,
                                     PriceQuote.counterparty == deal["counterparty"]))
        if quote is not None:
            pricing.append({"item_id": item.id, "unit_price_net": f"{quote.price:.2f}", "vat_rate": "20.00"})
    await session.commit()
    profile = await api.post(f"/accounting/organizations/{org.id}/seller-profiles", json={
        "source_key": "synthetic-contract-seller", "expected_revision": 0, "effective_from": "2026-01-01",
        "currency": "BYN", "address": "Synthetic address", "account": "TEST ACCOUNT", "bank": "TEST BANK",
        "bik": "TEST BIK", "director": "Synthetic director", "evidence": "Synthetic approved seller", "confirmed": True,
    })
    assert profile.status_code == 201, profile.text
    return {"org": org.id, "deal": source.id}, {
        "organization_id": org.id, "currency": "BYN", "document_date": "2026-09-01", "valid_until": "2026-09-06",
        "pricing": pricing, "pricing_evidence": "Explicit synthetic price and VAT from fixture quotes",
    }


async def _issue_contract_invoice(api, session, deal):
    from uuid import uuid4

    from tests.test_invoice_issuance import command, create

    ids, base = await _scoped_invoice_request(api, session, deal)
    payload, _ = await command(api, ids, base, key=str(uuid4()))
    return await create(api, ids, payload)


@pytest.mark.parametrize("fault", ["missing_receipt", "receipt_digest", "foreign_owner", "cancelled", "superseded",
                                  "contract_seller", "contract_buyer"])
async def test_package_rejects_unverified_or_inactive_erp_invoice(api, session, fault):
    from sqlalchemy import delete, update

    from modules.accounting.models import Organization
    from modules.sales.accounting_ownership import DealOwnership
    from modules.sales.invoice_issuance import InvoiceIssuanceReceipt
    from modules.sales.models import DealDocument, DocumentPackage

    await _make_template(api)
    deal = await _package_deal(api, session, counterparty="Synthetic package buyer")
    issued = await _issue_contract_invoice(api, session, deal)
    assert issued.status_code == 201, issued.text
    invoice_id = issued.json()["document"]["id"]
    contract = await api.post(f"/sales/deals/{deal['id']}/contract", json={"template_code": "supply"})
    assert contract.status_code == 201, contract.text
    contract_id = contract.json()["id"]
    assert (await api.post(f"/sales/documents/{contract_id}/decide", json={"approved": True})).status_code == 200
    # Deliberately bypass ORM guards in this isolated fixture: the package boundary
    # must independently refuse forged or inactive persisted invoice state.
    if fault == "missing_receipt":
        await session.execute(delete(InvoiceIssuanceReceipt).where(InvoiceIssuanceReceipt.document_id == invoice_id))
    elif fault == "receipt_digest":
        await session.execute(update(InvoiceIssuanceReceipt).where(InvoiceIssuanceReceipt.document_id == invoice_id)
                              .values(content_sha256="f" * 64))
    elif fault == "foreign_owner":
        other = Organization(name="Synthetic other seller", unp="999999997")
        session.add(other)
        await session.flush()
        await session.execute(update(DealOwnership).where(DealOwnership.deal_id == deal["id"])
                              .values(organization_id=other.id))
    elif fault == "cancelled":
        await session.execute(update(DealDocument).where(DealDocument.id == invoice_id).values(status="cancelled"))
    elif fault == "superseded":
        await session.execute(update(DealDocument).where(DealDocument.id == invoice_id)
                              .values(superseded_by_id=contract_id))
    else:
        from copy import deepcopy

        saved = await session.get(DealDocument, contract_id)
        changed = deepcopy(saved.snapshot_json)
        if fault == "contract_seller":
            changed["seller"]["unp"] = "999999997"
        else:
            changed["party"]["legal_entity_id"] += 1000
        await session.execute(update(DealDocument).where(DealDocument.id == contract_id).values(snapshot_json=changed))
    await session.commit()
    session.expire_all()
    refused = await api.post(f"/sales/deals/{deal['id']}/send-package")
    assert refused.status_code == 409, refused.text
    assert (await session.scalars(select(DocumentPackage))).all() == []


@pytest.mark.parametrize("status", ["posted", "paid"])
async def test_package_retains_captured_legacy_invoice(api, session, status):
    from modules.sales import documents
    from modules.sales.models import DealDocument

    await _make_template(api)
    deal = await _package_deal(api, session, counterparty="Synthetic historical buyer")
    invoice = DealDocument(deal_id=deal["id"], kind="invoice", number="SYN-LEGACY", status=status)
    session.add(invoice)
    await session.flush()
    core = api._transport.app.state.core
    await documents.capture(session, core, invoice)
    await documents.mark_issued(session, core, invoice, "historical-fixture")
    await session.commit()
    invoice_id, original = invoice.id, invoice.original_html
    contract = await api.post(f"/sales/deals/{deal['id']}/contract", json={"template_code": "supply"})
    assert contract.status_code == 201, contract.text
    contract_id = contract.json()["id"]
    assert (await api.post(f"/sales/documents/{contract_id}/decide", json={"approved": True})).status_code == 200
    packaged = await api.post(f"/sales/deals/{deal['id']}/send-package")
    assert packaged.status_code == 200, packaged.text
    assert packaged.json()["invoice_id"] == invoice_id and packaged.json()["sent"] is False
    rendered = await api.get(packaged.json()["render_url"])
    assert rendered.status_code == 200 and original in rendered.text
    again = await api.post(f"/sales/deals/{deal['id']}/send-package")
    assert again.status_code == 200 and again.json()["package_id"] == packaged.json()["package_id"]


async def test_prepare_contract_enriches_by_unp(api, session):
    # УНП 191234567 есть в mock-реестре ЕГР (RegistryClient)
    session.add(Counterparty(name="ООО «Аккумулятор»"))
    await session.commit()
    await _make_template(api)
    deal = await _make_deal(api)
    r = await api.post(
        f"/sales/deals/{deal['id']}/contract",
        json={"template_code": "supply", "unp": "191234567", "payment_terms": "100% предоплата"},
    )
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["kind"] == "contract" and doc["status"] == "pending_approval"

    # Counterparty обогащён УНП (без правки shared-схемы — адрес уходит в terms_json)
    cp = (
        await session.execute(select(Counterparty).where(Counterparty.name == "ООО «Аккумулятор»"))
    ).scalars().first()
    assert cp is not None and cp.unp == "191234567"

    # рендер подставляет реквизиты покупателя из ЕГР, продавца — из конфига
    html = (await api.get(f"/sales/documents/{doc['id']}/render")).text
    assert "191234567" in html
    assert "г. Минск, ул. Промышленная, 5" in html  # адрес из реестра
    assert "100% предоплата" in html
    assert "ООО «Аккумуляторные решения»" in html  # продавец (seller_name из конфига)


async def test_render_prefills_from_deal(api, session):
    session.add(Counterparty(name="ООО «МеталлПром»"))
    await session.commit()
    await _make_template(api)
    deal = await _make_deal(api, counterparty="ООО «МеталлПром»")
    # позиция сделки с реальным SKU (shared kernel) — должна попасть в спецификацию
    session.add(Sku(code="AKB-60", title="АКБ 6СТ-60", unit="шт"))
    await session.flush()
    sku = (await session.execute(select(Sku).where(Sku.code == "AKB-60"))).scalars().first()
    session.add(DealItem(deal_id=deal["id"], sku_id=sku.id, qty=Decimal("3")))
    await session.flush()

    r = await api.post(
        f"/sales/deals/{deal['id']}/contract",
        json={"template_code": "supply", "unp": "190000001", "delivery_terms": "EXW Минск"},
    )
    assert r.status_code == 201, r.text
    html = (await api.get(f"/sales/documents/{r.json()['id']}/render")).text
    assert "АКБ 6СТ-60" in html  # наименование позиции из сделки
    assert "BYN" in html  # сумма сделки


async def test_send_package_one_record(api, session):
    await _make_template(api)
    deal = await _package_deal(api, session, counterparty="АО «СтройКомплект»")
    # без счёта и договора — 409
    assert (await api.post(f"/sales/deals/{deal['id']}/send-package")).status_code == 409
    inv = await _issue_contract_invoice(api, session, deal)
    assert inv.status_code == 201, inv.text
    con = await api.post(
        f"/sales/deals/{deal['id']}/contract",
        json={"template_code": "supply", "unp": "190000002"},
    )
    assert con.status_code == 201, con.text
    # договор ещё на согласовании → пакет нельзя (ТЗ C.4: после согласования)
    assert (await api.post(f"/sales/deals/{deal['id']}/send-package")).status_code == 409
    dec = await api.post(
        f"/sales/documents/{con.json()['id']}/decide", json={"approved": True, "by": "РОП"}
    )
    assert dec.status_code == 200, dec.text

    pkg = await api.post(f"/sales/deals/{deal['id']}/send-package")
    assert pkg.status_code == 200, pkg.text
    body = pkg.json()
    assert body["sent"] is False and body["invoice_number"] and body["contract_number"]
    # Подготовка фиксируется без ложного сообщения об отправке.
    msgs = (await api.get(f"/sales/deals/{deal['id']}/messages")).json()
    assert len([m for m in msgs if "Подготовлен пакет" in m["text"]]) == 1
    assert not any("Отправлен пакет" in m["text"] for m in msgs)


async def test_package_render_combines_invoice_and_contract(api, session):
    await _make_template(api)
    deal = await _package_deal(api, session, counterparty="ООО «ПакетТест»")
    inv = await _issue_contract_invoice(api, session, deal)
    assert inv.status_code == 201, inv.text
    con = await api.post(
        f"/sales/deals/{deal['id']}/contract",
        json={"template_code": "supply", "unp": "190000003"},
    )
    assert con.status_code == 201, con.text
    # до согласования договора пакет ещё не собрать (тот же гейт, что у send-package)
    assert (await api.get(f"/sales/deals/{deal['id']}/package/render")).status_code == 409
    dec = await api.post(
        f"/sales/documents/{con.json()['id']}/decide", json={"approved": True, "by": "РОП"}
    )
    assert dec.status_code == 200, dec.text
    assert (await api.post(f"/sales/deals/{deal['id']}/send-package")).status_code == 200
    r = await api.get(f"/sales/deals/{deal['id']}/package/render")
    assert r.status_code == 200, r.text
    html = r.text
    assert inv.json()["document"]["number"] in html  # счёт в пакете
    assert "ДОГОВОР" in html  # тело договора по шаблону
    assert "page-break-before" in html  # разрыв страницы между счётом и договором


async def test_package_render_template_less_contract_cover(api, session):
    # Договор «по форме клиента» (template_id=None) — «открыть» и пакет отдают честную обложку,
    # а не 409 (регресс на находку верификатора: _contract_html падал на template-less договоре).
    deal = await _package_deal(api, session, counterparty="ООО «ФормаКлиента»")
    inv = await _issue_contract_invoice(api, session, deal)
    assert inv.status_code == 201, inv.text
    con = await api.post(f"/sales/deals/{deal['id']}/documents", json={"kind": "contract"})
    assert con.status_code == 201, con.text
    dec = await api.post(
        f"/sales/documents/{con.json()['id']}/decide", json={"approved": True, "by": "РОП"}
    )
    assert dec.status_code == 200, dec.text
    # одиночный рендер template-less договора — обложка, не 409
    single = await api.get(f"/sales/documents/{con.json()['id']}/render")
    assert single.status_code == 200, single.text
    assert "Оформлен по форме клиента" in single.text
    # пакет: счёт + template-less договор — 200 с обложкой
    assert (await api.post(f"/sales/deals/{deal['id']}/send-package")).status_code == 200
    pkg = await api.get(f"/sales/deals/{deal['id']}/package/render")
    assert pkg.status_code == 200, pkg.text
    assert "Оформлен по форме клиента" in pkg.text


async def test_prepare_contract_duplicate_409(api, session):
    """Повторная подготовка договора по сделке (активный уже есть) → 409."""
    session.add(Counterparty(name="ООО «АльфаМеталл»"))
    await session.commit()
    await _make_template(api)
    deal = await _make_deal(api, counterparty="ООО «АльфаМеталл»")
    first = await api.post(
        f"/sales/deals/{deal['id']}/contract",
        json={"template_code": "supply", "unp": "190445566"},
    )
    assert first.status_code == 201
    dup = await api.post(
        f"/sales/deals/{deal['id']}/contract",
        json={"template_code": "supply", "unp": "190445566"},
    )
    assert dup.status_code == 409


async def test_prepare_contract_graceful_unknown_unp(api, session):
    """УНП не в реестре → реквизиты минимум из сделки, без падения (graceful)."""
    session.add(Counterparty(name="ООО «Без УНП»"))
    await session.commit()
    await _make_template(api)
    deal = await _make_deal(api, counterparty="ООО «Без УНП»")
    r = await api.post(
        f"/sales/deals/{deal['id']}/contract",
        json={"template_code": "supply", "unp": "000000000"},
    )
    assert r.status_code == 201, r.text
    html = (await api.get(f"/sales/documents/{r.json()['id']}/render")).text
    assert "ООО «Без УНП»" in html  # имя покупателя из сделки


async def test_prepare_contract_unknown_template_404(api, session):
    session.add(Counterparty(name="ООО «Аккумулятор»"))
    await session.commit()
    deal = await _make_deal(api, counterparty="ООО «Аккумулятор»")
    r = await api.post(
        f"/sales/deals/{deal['id']}/contract", json={"template_code": "nope", "unp": ""}
    )
    assert r.status_code == 404


async def test_render_invoice_uses_real_deal_data(api, session):
    """kind=invoice → печатная форма счёта (sales-invoice-template.html), не договор."""
    session.add(Counterparty(name='ООО «АвтоЗапчасть»'))
    await session.commit()
    deal = await _make_deal(api, counterparty="ООО «АвтоЗапчасть»")
    session.add(Sku(code="AKB-77", title="АКБ 6СТ-77", unit="шт"))
    session.add(StockItem(sku_code="AKB-77", qty_available=2, qty_reserved=0))
    await session.flush()
    sku = (await session.execute(select(Sku).where(Sku.code == "AKB-77"))).scalars().first()
    session.add(DealItem(deal_id=deal["id"], sku_id=sku.id, qty=Decimal("2"), unit_price=Decimal("150")))
    session.add(
        PriceQuote(sku_code="AKB-77", counterparty="ООО «АвтоЗапчасть»", price=Decimal("150.00"))
    )
    await session.flush()
    await session.commit()

    inv = await _issue_contract_invoice(api, session, deal)
    assert inv.status_code == 201, inv.text
    doc = inv.json()["document"]
    assert doc["kind"] == "invoice"

    r = await api.get(f"/sales/documents/{doc['id']}/render")
    assert r.status_code == 200, r.text
    assert "text/html" in r.headers["content-type"]
    html = r.text
    assert doc["number"] in html
    assert "АКБ 6СТ-77" in html  # наименование позиции сделки
    assert "Счёт-протокол на оплату" in html
    # 2 * 150.00 = 300.00 нетто, НДС 20% = 60.00, итого 360.00
    assert "360.00" in html or "360,00" in html


async def test_invoice_without_price_quote_requires_pricing(api, session):
    """Нет котировки: выпуск запрещён, неизвестная цена не превращается в ноль."""
    session.add(Counterparty(name="ООО «БезЦены»"))
    await session.commit()
    deal = await _make_deal(api, counterparty="ООО «БезЦены»")
    session.add(Sku(code="AKB-88", title="АКБ 6СТ-88", unit="шт"))
    await session.flush()
    sku = (await session.execute(select(Sku).where(Sku.code == "AKB-88"))).scalars().first()
    session.add(DealItem(deal_id=deal["id"], sku_id=sku.id, qty=Decimal("1")))
    await session.flush()
    await session.commit()

    ids, base = await _scoped_invoice_request(api, session, deal)
    inv = await api.post(f"/sales/deals/{ids['deal']}/invoice-preview", json=base)
    assert inv.status_code == 422, inv.text

    assert all(error["loc"][:2] == ["body", "pricing"] for error in inv.json()["detail"])


async def test_render_order_kind_still_400(api, session):
    """kind=order — не имеет печатной формы; понятная ошибка, не 500."""
    session.add(Counterparty(name="ООО «Заказ»"))
    await session.commit()
    deal = await _make_deal(api, counterparty="ООО «Заказ»")
    order = await api.post(f"/sales/deals/{deal['id']}/documents", json={"kind": "order"})
    assert order.status_code == 201, order.text
    r = await api.get(f"/sales/documents/{order.json()['id']}/render")
    assert r.status_code == 400


async def test_render_invoice_escapes_html_in_sku_title(api, session):
    """XSS: наименование SKU с HTML-тегами экранируется в печатной форме счёта.

    Регрессия из code-review: title/реквизиты подставлялись в HTML f-строкой без
    html.escape → stored XSS у любого носителя sales.deal.read, открывшего рендер.
    """
    session.add(Counterparty(name="ООО «Инъекция»"))
    await session.commit()
    deal = await _make_deal(api, counterparty="ООО «Инъекция»")
    session.add(Sku(code="XSS-1", title='<script>alert(1)</script>', unit="шт"))
    session.add(StockItem(sku_code="XSS-1", qty_available=1, qty_reserved=0))
    await session.flush()
    sku = (await session.execute(select(Sku).where(Sku.code == "XSS-1"))).scalars().first()
    session.add(DealItem(deal_id=deal["id"], sku_id=sku.id, qty=Decimal("1"), unit_price=Decimal("100")))
    await session.flush()
    session.add(PriceQuote(sku_code=sku.code, counterparty=deal["counterparty"], price=Decimal("100")))
    await session.commit()

    inv = await _issue_contract_invoice(api, session, deal)
    r = await api.get(f"/sales/documents/{inv.json()['document']['id']}/render")
    assert r.status_code == 200, r.text
    # сырой <script> не должен попасть в разметку — только экранированный
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in r.text


# ── Лого продавца (company_branding) ────────────────────────────────────────────
_TINY_PNG_DATA_URL = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


async def _logo_original_flow(api, session):
    from modules.sales.invoice_issuance import verified_receipt
    from modules.sales.models import DealDocument
    from tests.test_invoice_issuance import command, create

    uploaded = await api.put("/sales/branding", json={"logo_data_url": _TINY_PNG_DATA_URL})
    assert uploaded.status_code == 200, uploaded.text
    deal = await _package_deal(api, session, counterparty="Synthetic frozen-logo buyer")
    ids, base = await _scoped_invoice_request(api, session, deal)
    payload, preview = await command(api, ids, base, key="frozen-logo-original")
    assert preview["basis_digest"] == payload["expected_basis_digest"]
    issued = await create(api, ids, payload)
    assert issued.status_code == 201, issued.text
    doc_id = issued.json()["document"]["id"]
    original = await api.get(f"/sales/documents/{doc_id}/render")
    assert original.status_code == 200
    assert f'<img src="{_TINY_PNG_DATA_URL}"' in original.text
    # Whitespace is valid in embedded PNG base64; changing its stored URI must
    # not rewrite the already issued original or its exact request replay.
    replacement = _TINY_PNG_DATA_URL.replace("base64,", "base64,\n")
    changed = await api.put("/sales/branding", json={"logo_data_url": replacement})
    assert changed.status_code == 200 and changed.json()["logo_data_url"] == replacement
    replayed = await create(api, ids, payload)
    assert replayed.status_code == 200 and replayed.json()["replayed"] is True
    assert replayed.json()["content_sha256"] == issued.json()["content_sha256"]
    again = await api.get(f"/sales/documents/{doc_id}/render")
    assert again.content == original.content
    doc = await session.get(DealDocument, doc_id, populate_existing=True)
    receipt = await verified_receipt(session, doc, ids["org"])
    assert receipt is not None and receipt.content_sha256 == issued.json()["content_sha256"]
    return original.text


async def test_invoice_logo_original_is_frozen_on_replay(api, session, tmp_path):
    original = await _logo_original_flow(api, session)
    (tmp_path / "invoice-logo-original.html").write_text(original, encoding="utf-8")


async def test_invoice_does_not_use_another_sellers_logo(api, session):
    from tests.test_invoice_issuance import command, create, seed

    assert (await api.put("/sales/branding", json={"logo_data_url": _TINY_PNG_DATA_URL})).status_code == 200
    ids, base = await seed(api, session, suffix="-foreign-logo")
    payload, _ = await command(api, ids, base)
    issued = await create(api, ids, payload)
    assert issued.status_code == 201, issued.text
    rendered = await api.get(f"/sales/documents/{issued.json()['document']['id']}/render")
    assert rendered.status_code == 200 and "Bound seller-foreign-logo" in rendered.text
    assert '<div class="logo">' not in rendered.text and _TINY_PNG_DATA_URL not in rendered.text


async def test_invoice_unsafe_logo_cannot_become_an_original(api, session):
    from sqlalchemy import func

    from modules.sales.models import DealDocument
    from modules.wms.invoice_reservations import InvoiceReservation
    from tests.test_invoice_issuance import command, create

    uploaded = await api.put("/sales/branding", json={"logo_data_url": "data:image/svg+xml;base64,PHN2Zy8+"})
    assert uploaded.status_code == 200, uploaded.text
    deal = await _package_deal(api, session, counterparty="Synthetic unsafe-logo buyer")
    ids, base = await _scoped_invoice_request(api, session, deal)
    payload, _ = await command(api, ids, base)
    refused = await create(api, ids, payload)
    assert refused.status_code == 422, refused.text
    assert "Внешние ресурсы" in refused.text
    assert await session.scalar(select(func.count()).select_from(DealDocument)) == 0
    assert await session.scalar(select(func.count()).select_from(InvoiceReservation)) == 0


async def test_branding_honest_empty_before_upload(api):
    """Нет загруженного факсимиле — все поля null (честный None), не 404."""
    r = await api.get("/sales/branding")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "logo_data_url": None,
        "stamp_data_url": None,
        "signature_data_url": None,
    }


async def test_branding_upload_rejects_non_image(api):
    r = await api.put("/sales/branding", json={"logo_data_url": "not-a-data-uri"})
    assert r.status_code == 422


async def test_branding_upload_rejects_oversized(api):
    huge = "data:image/png;base64," + ("A" * 1_500_000)
    r = await api.put("/sales/branding", json={"logo_data_url": huge})
    assert r.status_code == 422


async def test_branding_upload_then_get_roundtrip(api):
    put = await api.put("/sales/branding", json={"logo_data_url": _TINY_PNG_DATA_URL})
    assert put.status_code == 200, put.text
    assert put.json()["logo_data_url"] == _TINY_PNG_DATA_URL

    got = await api.get("/sales/branding")
    assert got.json()["logo_data_url"] == _TINY_PNG_DATA_URL

    # повторная загрузка заменяет прежнюю (singleton, не растит таблицу)
    other = _TINY_PNG_DATA_URL.replace("png", "jpeg", 1)
    put2 = await api.put("/sales/branding", json={"logo_data_url": other})
    assert put2.status_code == 200
    got2 = await api.get("/sales/branding")
    assert got2.json()["logo_data_url"] == other


async def test_render_invoice_includes_uploaded_logo(api, session):
    """Загруженное лого попадает в шапку печатной формы счёта."""
    assert (
        await api.put("/sales/branding", json={"logo_data_url": _TINY_PNG_DATA_URL})
    ).status_code == 200

    session.add(Counterparty(name='ООО «СЛого»'))
    await session.commit()
    deal = await _make_deal(api, counterparty="ООО «СЛого»")
    session.add(Sku(code="AKB-99", title="АКБ 6СТ-99", unit="шт"))
    session.add(StockItem(sku_code="AKB-99", qty_available=1, qty_reserved=0))
    await session.flush()
    sku = (await session.execute(select(Sku).where(Sku.code == "AKB-99"))).scalars().first()
    session.add(DealItem(deal_id=deal["id"], sku_id=sku.id, qty=Decimal("1"), unit_price=Decimal("100")))
    await session.flush()
    session.add(PriceQuote(sku_code=sku.code, counterparty=deal["counterparty"], price=Decimal("100")))
    await session.commit()

    inv = await _issue_contract_invoice(api, session, deal)
    r = await api.get(f"/sales/documents/{inv.json()['document']['id']}/render")
    assert r.status_code == 200, r.text
    assert f'<img src="{_TINY_PNG_DATA_URL}"' in r.text


async def test_render_invoice_no_logo_block_when_not_uploaded(api, session):
    """Лого не загружено — честно нет <div class="logo"> (не битая картинка)."""
    session.add(Counterparty(name='ООО «БезЛого»'))
    await session.commit()
    deal = await _make_deal(api, counterparty="ООО «БезЛого»")
    session.add(Sku(code="AKB-100", title="АКБ 6СТ-100", unit="шт"))
    session.add(StockItem(sku_code="AKB-100", qty_available=1, qty_reserved=0))
    await session.flush()
    sku = (await session.execute(select(Sku).where(Sku.code == "AKB-100"))).scalars().first()
    session.add(DealItem(deal_id=deal["id"], sku_id=sku.id, qty=Decimal("1"), unit_price=Decimal("100")))
    await session.flush()
    session.add(PriceQuote(sku_code=sku.code, counterparty=deal["counterparty"], price=Decimal("100")))
    await session.commit()

    inv = await _issue_contract_invoice(api, session, deal)
    r = await api.get(f"/sales/documents/{inv.json()['document']['id']}/render")
    assert r.status_code == 200, r.text
    assert '<div class="logo">' not in r.text


def test_render_contract_escapes_untrusted_ctx_values():
    """Stored-XSS-гард (PLATFORM #2): значения ctx (свободный текст — условия оплаты/доставки,
    реквизиты покупателя) экранируются, тело шаблона доверенное. <script> в payment_terms/
    counterparty не исполнится в сессии согласующего при открытии договора."""
    from modules.sales.routes import _render_contract

    body = "Оплата: {{payment_terms}}. Покупатель: {{buyer.name}}."
    ctx = {"payment_terms": "<script>steal()</script>", "buyer.name": 'ООО "<b>Р</b>"'}
    out = _render_contract(body, ctx, facsimile="<div class='fx'>подпись</div>")
    assert "<script>steal()</script>" not in out  # сырой скрипт не попал
    assert "&lt;script&gt;steal()&lt;/script&gt;" in out  # экранирован
    assert "&lt;b&gt;" in out
    assert "<div class='fx'>подпись</div>" in out  # facsimile доверенный — как есть
