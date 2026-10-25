"""SALES-53: договор по шаблону + реквизиты по УНП + пакет «счёт + договор»."""
from decimal import Decimal

import pytest
import pytest_asyncio
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


@pytest_asyncio.fixture
async def selected_contract_parties(api, session):
    from modules.integrations.registry import RegistryClient

    registry = api._transport.app.state.core.services.registry
    if type(registry) is not RegistryClient or registry.base_url or registry.allow_demo is not True:
        raise AssertionError("SYNTHETIC_REGISTRY_REQUIRED")
    session.add_all(Counterparty(name=name) for name in (
        "ООО «Аккумулятор»", "ООО «МеталлПром»", "АО «СтройКомплект»", "ООО «ПакетТест»",
        "ООО «ФормаКлиента»", "ООО «АльфаМеталл»", "ООО «Без УНП»", "ООО «АвтоЗапчасть»",
        "ООО «БезЦены»", "ООО «Заказ»", "ООО «Инъекция»", "ООО «СЛого»", "ООО «БезЛого»",
    ))
    await session.commit()


@pytest_asyncio.fixture
async def erp_contract_context(api, selected_contract_parties):
    from modules.integrations.client import OneCClient

    onec = api._transport.app.state.core.services.onec
    if (type(onec) is not OneCClient or onec.base_url or onec.allow_demo is not True
            or onec.outbound_document_source_available is not False):
        raise AssertionError("SYNTHETIC_ONEC_REQUIRED")
    api.headers["X-User"] = "e2e_owner"


async def test_prepare_contract_enriches_by_unp(api, session, selected_contract_parties):
    # УНП 191234567 есть в mock-реестре ЕГР (RegistryClient)
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


async def test_render_prefills_from_deal(api, session, selected_contract_parties):
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


async def test_send_package_one_record(api, session, erp_contract_context):
    await _make_template(api)
    deal = await _make_deal(api, counterparty="АО «СтройКомплект»")
    # без счёта и договора — 409
    assert (await api.post(f"/sales/deals/{deal['id']}/send-package")).status_code == 409
    inv = await _issue_package_invoice(api, session, deal["id"], unp="190000002")
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


async def test_package_render_combines_invoice_and_contract(api, session, erp_contract_context):
    await _make_template(api)
    deal = await _make_deal(api, counterparty="ООО «ПакетТест»")
    inv = await _issue_package_invoice(api, session, deal["id"], unp="190000003")
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


async def test_package_render_template_less_contract_cover(api, session, erp_contract_context):
    # Договор «по форме клиента» (template_id=None) — «открыть» и пакет отдают честную обложку,
    # а не 409 (регресс на находку верификатора: _contract_html падал на template-less договоре).
    deal = await _make_deal(api, counterparty="ООО «ФормаКлиента»")
    inv = await _issue_package_invoice(api, session, deal["id"])
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


async def test_prepare_contract_duplicate_409(api, selected_contract_parties):
    """Повторная подготовка договора по сделке (активный уже есть) → 409."""
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


async def test_prepare_contract_graceful_unknown_unp(api, selected_contract_parties):
    """УНП не в реестре → реквизиты минимум из сделки, без падения (graceful)."""
    await _make_template(api)
    deal = await _make_deal(api, counterparty="ООО «Без УНП»")
    r = await api.post(
        f"/sales/deals/{deal['id']}/contract",
        json={"template_code": "supply", "unp": "000000000"},
    )
    assert r.status_code == 201, r.text
    html = (await api.get(f"/sales/documents/{r.json()['id']}/render")).text
    assert "ООО «Без УНП»" in html  # имя покупателя из сделки


async def test_prepare_contract_unknown_template_404(api, selected_contract_parties):
    deal = await _make_deal(api, counterparty="ООО «Аккумулятор»")
    r = await api.post(
        f"/sales/deals/{deal['id']}/contract", json={"template_code": "nope", "unp": ""}
    )
    assert r.status_code == 404


async def _issue_package_invoice(api, session, deal_id, *, unp=None, logo_data_url=""):
    from modules.sales.models import Deal

    row = await session.get(Deal, deal_id)
    buyer = await session.get(Counterparty, row.counterparty_id)
    if unp is not None:
        buyer.unp = unp
    sku = Sku(code="PACKAGE-TEST", title="Synthetic package goods", unit="шт")
    session.add(sku)
    await session.flush()
    session.add(DealItem(deal_id=deal_id, sku_id=sku.id, qty=Decimal("1"), unit_price=Decimal("100")))
    await session.commit()
    inv, _ = await _issue_single_line_contract_invoice(api, session, deal_id, logo_data_url=logo_data_url)
    return inv


async def _contract_invoice_command(api, session, deal_id, *, unit_price_net, logo_data_url=""):
    from datetime import date

    from modules.accounting import seller_profiles
    from modules.accounting.models import AccessGrant, Organization
    from modules.accounting.schemas import SellerProfileInput
    from modules.accounting.service import lock_organization
    from modules.sales.accounting_ownership import DealOwnership
    from modules.sales.client_document_register import DealClientBinding, preview_snapshot
    from modules.sales.models import Deal
    from modules.wms.models import StockMovement, WarehouseDirectory
    from tests.test_invoice_issuance import command

    row = await session.get(Deal, deal_id)
    item = await session.scalar(select(DealItem).where(DealItem.deal_id == row.id))
    assert item is not None
    sku = await session.get(Sku, item.sku_id)
    buyer = await session.get(Counterparty, row.counterparty_id)
    buyer.unp = buyer.unp or "500000001"
    buyer.requisites = buyer.requisites or {"address": "Synthetic buyer address"}
    org = Organization(name="Synthetic contract seller", unp="100000001")
    session.add(org)
    await session.flush()
    # Only reader membership in this isolated synthetic book.
    session.add_all([
        AccessGrant(organization_id=org.id, subject="e2e_owner", role="reader"),
        DealOwnership(deal_id=row.id, organization_id=org.id, snapshot={},
                      evidence="Synthetic confirmed organization", actor="synthetic-accountant"),
        StockMovement(organization_id=org.id, sku_code=sku.code, warehouse="W",
                      kind="in", qty=item.qty, reason="receipt"),
        WarehouseDirectory(organization_id=org.id, name="W", title="Synthetic physical warehouse",
                           created_by="synthetic-accountant", is_active=True, wms_enabled=False,
                           prohibit_negative_stock=True),
    ])
    await session.flush()
    session.add(DealClientBinding(
        deal_id=row.id, organization_id=org.id, counterparty_id=buyer.id,
        snapshot=await preview_snapshot(session, org.id, row, buyer.id),
        evidence="Synthetic exact buyer", actor="synthetic-accountant",
    ))
    await lock_organization(session, org.id)
    await seller_profiles.create(session, org.id, SellerProfileInput(
        source_key="synthetic-contract-seller", expected_revision=0, effective_from=date(2026, 1, 1),
        currency="BYN", address="Synthetic seller address", account="TEST ACCOUNT", bank="TEST BANK",
        bik="TEST BIK", director="Synthetic director", evidence="Synthetic confirmed seller", confirmed=True, logo_data_url=logo_data_url,
    ), "synthetic-accountant")
    await session.commit()
    ids = {"org": org.id, "deal": row.id, "item": item.id}
    base = {"organization_id": org.id, "currency": "BYN", "document_date": "2026-09-01",
            "valid_until": "2026-09-06", "pricing_evidence": "Confirmed synthetic item price",
            "pricing": [{"item_id": item.id, "unit_price_net": unit_price_net, "vat_rate": "20.00"}]}
    cmd, preview = await command(api, ids, base)
    return ids, cmd, preview


async def _issue_single_line_contract_invoice(api, session, deal_id, *, logo_data_url=""):
    from modules.sales.invoice_issuance import verified_receipt
    from modules.sales.models import DealDocument
    from tests.test_invoice_issuance import create

    item = await session.scalar(select(DealItem).where(DealItem.deal_id == deal_id))
    assert item is not None and item.unit_price is not None
    ids, cmd, preview = await _contract_invoice_command(
        api, session, deal_id, unit_price_net=format(item.unit_price, ".2f"), logo_data_url=logo_data_url,
    )
    inv = await create(api, ids, cmd)
    assert inv.status_code == 201, inv.text
    doc = inv.json()["document"]
    issued = await session.get(DealDocument, doc["id"])
    assert await verified_receipt(session, issued, ids["org"]) is not None
    return inv, preview


async def test_render_invoice_uses_real_deal_data(api, session, erp_contract_context):
    """kind=invoice → печатная форма счёта (sales-invoice-template.html), не договор."""
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

    inv, preview = await _issue_single_line_contract_invoice(api, session, deal["id"])
    assert preview["lines"][0]["net"] == "300.00"
    assert preview["lines"][0]["tax"] == "60.00" and preview["amount"] == "360.00"
    assert inv.status_code == 201, inv.text
    doc = inv.json()["document"]
    assert doc["kind"] == "invoice"

    r = await api.get(f"/sales/documents/{doc['id']}/render")
    assert r.status_code == 200, r.text
    assert "text/html" in r.headers["content-type"]
    html = r.text
    assert doc["number"] in html
    assert "АКБ 6СТ-77" in html  # наименование позиции сделки
    assert f"<h1>Счёт {doc['number']} от 2026-09-01</h1>" in html
    # 2 * 150.00 = 300.00 нетто, НДС 20% = 60.00, итого 360.00
    assert "360.00" in html or "360,00" in html


async def test_invoice_without_price_quote_requires_pricing(api, session, erp_contract_context):
    """Missing explicit pricing blocks issuance without inventing a stored zero price."""
    from sqlalchemy import func

    from modules.sales.invoice_issuance import InvoiceIssuanceReceipt
    from modules.sales.models import DealDocument
    from modules.sales.schemas import InvoiceCreate
    from modules.wms.invoice_reservations import InvoiceReservation
    from modules.wms.models import ReservationVersion

    deal = await _make_deal(api, counterparty="ООО «БезЦены»")
    sku = Sku(code="AKB-88", title="АКБ 6СТ-88", unit="шт")
    session.add(sku)
    await session.flush()
    session.add(DealItem(deal_id=deal["id"], sku_id=sku.id, qty=Decimal("1")))
    await session.commit()
    # This explicit synthetic preview price is never persisted to the deal item.
    ids, cmd, _ = await _contract_invoice_command(api, session, deal["id"], unit_price_net="100.00")
    request = {"kind": "invoice", **cmd}
    InvoiceCreate.model_validate(request)
    del request["pricing"]
    inv = await api.post(f"/sales/deals/{deal['id']}/documents", json=request)
    assert inv.status_code == 422, inv.text
    missing = [error for error in inv.json()["detail"]
               if error["loc"][-1] == "pricing" and error["type"] == "missing"]
    assert len(missing) == 1, inv.text
    assert (await session.get(DealItem, ids["item"])).unit_price is None
    assert await session.scalar(select(func.count()).select_from(PriceQuote)) == 0
    assert await session.scalar(select(func.count()).select_from(DealDocument).where(
        DealDocument.kind == "invoice")) == 0
    assert await session.scalar(select(func.count()).select_from(InvoiceIssuanceReceipt)) == 0
    assert await session.scalar(select(func.count()).select_from(InvoiceReservation)) == 0
    assert await session.scalar(select(func.count()).select_from(ReservationVersion)) == 0


async def test_render_order_kind_still_400(api, selected_contract_parties):
    """kind=order — не имеет печатной формы; понятная ошибка, не 500."""
    from modules.integrations.client import OneCClient

    onec = api._transport.app.state.core.services.onec
    if (type(onec) is not OneCClient or onec.base_url or onec.allow_demo is not True
            or onec.outbound_document_source_available is not False):
        raise AssertionError("SYNTHETIC_ONEC_REQUIRED")
    deal = await _make_deal(api, counterparty="ООО «Заказ»")
    order = await api.post(f"/sales/deals/{deal['id']}/documents", json={"kind": "order"})
    assert order.status_code == 201, order.text
    r = await api.get(f"/sales/documents/{order.json()['id']}/render")
    assert r.status_code == 400


async def test_render_invoice_escapes_html_in_sku_title(api, session, erp_contract_context):
    """XSS: наименование SKU с HTML-тегами экранируется в печатной форме счёта.

    Регрессия из code-review: title/реквизиты подставлялись в HTML f-строкой без
    html.escape → stored XSS у любого носителя sales.deal.read, открывшего рендер.
    """
    deal = await _make_deal(api, counterparty="ООО «Инъекция»")
    session.add(Sku(code="XSS-1", title='<script>alert(1)</script>', unit="шт"))
    session.add(StockItem(sku_code="XSS-1", qty_available=1, qty_reserved=0))
    await session.flush()
    sku = (await session.execute(select(Sku).where(Sku.code == "XSS-1"))).scalars().first()
    session.add(DealItem(deal_id=deal["id"], sku_id=sku.id, qty=Decimal("1"), unit_price=Decimal("100")))
    await session.flush()
    session.add(PriceQuote(sku_code=sku.code, counterparty=deal["counterparty"], price=Decimal("100")))
    await session.commit()

    inv, preview = await _issue_single_line_contract_invoice(api, session, deal["id"])
    assert inv.status_code == 201, inv.text
    assert preview["lines"][0]["net"] == "100.00"
    assert preview["lines"][0]["tax"] == "20.00" and preview["amount"] == "120.00"
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


async def test_render_invoice_includes_uploaded_logo(api, session, erp_contract_context):
    """Загруженное лого попадает в шапку печатной формы счёта."""
    assert (
        await api.put("/sales/branding", json={"logo_data_url": _TINY_PNG_DATA_URL})
    ).status_code == 200

    deal = await _make_deal(api, counterparty="ООО «СЛого»")
    session.add(Sku(code="AKB-99", title="АКБ 6СТ-99", unit="шт"))
    session.add(StockItem(sku_code="AKB-99", qty_available=1, qty_reserved=0))
    await session.flush()
    sku = (await session.execute(select(Sku).where(Sku.code == "AKB-99"))).scalars().first()
    session.add(DealItem(deal_id=deal["id"], sku_id=sku.id, qty=Decimal("1"), unit_price=Decimal("100")))
    await session.flush()
    session.add(PriceQuote(sku_code=sku.code, counterparty=deal["counterparty"], price=Decimal("100")))
    await session.commit()

    inv, _ = await _issue_single_line_contract_invoice(api, session, deal["id"], logo_data_url=_TINY_PNG_DATA_URL)
    assert inv.status_code == 201, inv.text
    r = await api.get(f"/sales/documents/{inv.json()['document']['id']}/render")
    assert r.status_code == 200, r.text
    assert f'<img src="{_TINY_PNG_DATA_URL}"' in r.text


async def test_render_invoice_no_logo_block_when_not_uploaded(api, session, erp_contract_context):
    """Лого не загружено — честно нет <div class="logo"> (не битая картинка)."""
    deal = await _make_deal(api, counterparty="ООО «БезЛого»")
    session.add(Sku(code="AKB-100", title="АКБ 6СТ-100", unit="шт"))
    session.add(StockItem(sku_code="AKB-100", qty_available=1, qty_reserved=0))
    await session.flush()
    sku = (await session.execute(select(Sku).where(Sku.code == "AKB-100"))).scalars().first()
    session.add(DealItem(deal_id=deal["id"], sku_id=sku.id, qty=Decimal("1"), unit_price=Decimal("100")))
    await session.flush()
    session.add(PriceQuote(sku_code=sku.code, counterparty=deal["counterparty"], price=Decimal("100")))
    await session.commit()

    inv, _ = await _issue_single_line_contract_invoice(api, session, deal["id"])
    assert inv.status_code == 201, inv.text
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


@pytest.mark.parametrize("case", [
    "legacy_posted", "legacy_paid", "cancelled", "superseded", "issued_contract",
    "issued_invoice_no_receipt", "erp_marker_posted_no_receipt",
])
async def test_package_original_compatibility(api, session, erp_contract_context, case):
    """Synthetic historical originals and deliberately invalid restored candidates."""
    from datetime import datetime

    from sqlalchemy import func

    from core.domain.models import OutboxEvent
    from modules.accounting.models import Organization
    from modules.sales import documents
    from modules.sales.accounting_ownership import DealOwnership
    from modules.sales.invoice_issuance import MODE
    from modules.sales.models import DealDocument, DocumentPackage, Message

    deal = await _make_deal(api)
    org = Organization(name="Synthetic historical seller", unp="100000001")
    session.add(org)
    await session.flush()
    session.add(DealOwnership(deal_id=deal["id"], organization_id=org.id, snapshot={},
                              evidence="Synthetic historical ownership", actor="synthetic-accountant"))

    def historical(kind, status):
        original = "<p>Synthetic historical " + kind + "</p>"
        return DealDocument(deal_id=deal["id"], kind=kind, number="HIST-" + kind,
                            status=status, amount=Decimal("120"), original_html=original,
                            snapshot_json={"amount": "120.00"}, content_sha256=documents.digest(original),
                            issued_at=datetime(2026, 9, 1), issued_by="synthetic-accountant")

    invoice = historical("invoice", "paid" if case == "legacy_paid" else "posted")
    contract = historical("contract", "issued" if case == "issued_contract" else "posted")
    if case == "cancelled":
        invoice.status = "cancelled"
    elif case == "issued_invoice_no_receipt":
        invoice.status = "issued"  # Negative candidate: deliberately no ERP receipt.
    elif case == "erp_marker_posted_no_receipt":
        invoice.snapshot_json = {"amount": "120.00", "issuance_mode": MODE}
    session.add_all([invoice, contract])
    await session.flush()
    if case == "superseded":
        replacement = DealDocument(deal_id=deal["id"], kind="invoice", number="REPLACEMENT", status="draft")
        session.add(replacement)
        await session.flush()
        invoice.superseded_by_id = replacement.id
    await session.commit()
    response = await api.post(f"/sales/deals/{deal['id']}/send-package")
    accepted = case in {"legacy_posted", "legacy_paid"}
    assert response.status_code == (200 if accepted else 409), response.text
    assert await session.scalar(select(func.count()).select_from(DocumentPackage)) == int(accepted)
    assert await session.scalar(select(func.count()).select_from(Message).where(
        Message.text.contains("Подготовлен пакет"))) == int(accepted)
    assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
        OutboxEvent.event_type == "sales.package.prepared")) == int(accepted)
    if accepted:
        assert response.json()["sent"] is False


@pytest.mark.parametrize("fault", ["missing", "wrong"])
async def test_package_erp_invoice_requires_exact_ownership(api, session, erp_contract_context, fault):
    """SQLite-only ownership fault injection; genuine invoice/receipt remain intact."""
    from sqlalchemy import func

    from core.domain.models import OutboxEvent
    from modules.accounting.models import Organization
    from modules.sales.accounting_ownership import DealOwnership
    from modules.sales.invoice_issuance import verified_receipt
    from modules.sales.models import DealDocument, DocumentPackage, Message

    deal = await _make_deal(api)
    inv = await _issue_package_invoice(api, session, deal["id"])
    invoice_id = inv.json()["document"]["id"]
    original_org = (await session.get(DealOwnership, deal["id"])).organization_id
    assert await verified_receipt(session, await session.get(DealDocument, invoice_id), original_org) is not None
    contract = await api.post(f"/sales/deals/{deal['id']}/documents", json={"kind": "contract"})
    assert contract.status_code == 201, contract.text
    decision = await api.post(f"/sales/documents/{contract.json()['id']}/decide",
                              json={"approved": True, "by": "РОП"})
    assert decision.status_code == 200, decision.text
    # Deliberate isolated SQLite storage corruption; ORM guards are never disabled.
    table = DealOwnership.__table__
    if fault == "missing":
        await session.execute(table.delete().where(table.c.deal_id == deal["id"]))
    else:
        other = Organization(name="Synthetic unrelated seller", unp="100000002")
        session.add(other)
        await session.flush()
        await session.execute(table.update().where(table.c.deal_id == deal["id"])
                              .values(organization_id=other.id))
    await session.commit()
    session.expire_all()
    response = await api.post(f"/sales/deals/{deal['id']}/send-package")
    assert response.status_code == 409, response.text
    assert await verified_receipt(session, await session.get(DealDocument, invoice_id), original_org) is not None
    assert await session.scalar(select(func.count()).select_from(DocumentPackage)) == 0
    assert await session.scalar(select(func.count()).select_from(Message).where(
        Message.text.contains("Подготовлен пакет"))) == 0
    assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
        OutboxEvent.event_type == "sales.package.prepared")) == 0


async def test_invoice_logo_original_survives_profile_update(api, session, erp_contract_context):
    from datetime import date

    from modules.accounting import seller_profiles
    from modules.accounting.schemas import SellerProfileInput
    from modules.accounting.service import lock_organization
    from tests.accounting.test_seller_logo import media
    from tests.accounting.test_seller_profiles import payload

    deal = await _make_deal(api)
    inv = await _issue_package_invoice(api, session, deal["id"], logo_data_url=_TINY_PNG_DATA_URL)
    body = inv.json()
    url = f"/sales/documents/{body['document']['id']}/render"
    before = await api.get(url)
    assert before.status_code == 200, before.text
    org = body["organization_id"]
    replacement = media("JPEG")
    await lock_organization(session, org)
    await seller_profiles.create(session, org, SellerProfileInput(**payload(
        source_key="synthetic-logo-revision", expected_revision=1, effective_from="2026-10-01",
        logo_data_url=replacement)), "synthetic-accountant")
    await session.commit()
    assert (await seller_profiles.current(session, org, date(2026, 10, 1), "BYN"))["seller"]["logo_data_url"] == replacement
    after = await api.get(url)
    assert after.content == before.content and after.headers["etag"] == before.headers["etag"]
    assert _TINY_PNG_DATA_URL in after.text and replacement not in after.text


async def test_erp_invoice_does_not_use_global_branding(api, session, erp_contract_context):
    uploaded = await api.put("/sales/branding", json={"logo_data_url": _TINY_PNG_DATA_URL})
    assert uploaded.status_code == 200, uploaded.text
    deal = await _make_deal(api)
    inv = await _issue_package_invoice(api, session, deal["id"])
    response = await api.get(f"/sales/documents/{inv.json()['document']['id']}/render")
    assert response.status_code == 200, response.text
    assert '<div class="logo">' not in response.text
    assert _TINY_PNG_DATA_URL not in response.text
