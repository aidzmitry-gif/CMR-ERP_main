"""SALES-53: договор по шаблону + реквизиты по УНП + пакет «счёт + договор»."""
from decimal import Decimal

from sqlalchemy import select

from core.domain.models import Counterparty, Sku
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


async def test_prepare_contract_enriches_by_unp(api, session):
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


async def test_render_prefills_from_deal(api, session):
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


async def test_send_package_one_record(api):
    await _make_template(api)
    deal = await _make_deal(api, counterparty="АО «СтройКомплект»")
    # без счёта и договора — 409
    assert (await api.post(f"/sales/deals/{deal['id']}/send-package")).status_code == 409
    inv = await api.post(f"/sales/deals/{deal['id']}/documents", json={"kind": "invoice"})
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
    assert body["sent"] and body["invoice_number"] and body["contract_number"]
    # ровно одна запись «отправлен пакет» в истории переписки
    msgs = (await api.get(f"/sales/deals/{deal['id']}/messages")).json()
    assert len([m for m in msgs if "Отправлен пакет" in m["text"]]) == 1


async def test_package_render_combines_invoice_and_contract(api):
    await _make_template(api)
    deal = await _make_deal(api, counterparty="ООО «ПакетТест»")
    inv = await api.post(f"/sales/deals/{deal['id']}/documents", json={"kind": "invoice"})
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
    r = await api.get(f"/sales/deals/{deal['id']}/package/render")
    assert r.status_code == 200, r.text
    html = r.text
    assert inv.json()["number"] in html  # счёт в пакете
    assert "ДОГОВОР" in html  # тело договора по шаблону
    assert "page-break-before" in html  # разрыв страницы между счётом и договором


async def test_package_render_template_less_contract_cover(api):
    # Договор «по форме клиента» (template_id=None) — «открыть» и пакет отдают честную обложку,
    # а не 409 (регресс на находку верификатора: _contract_html падал на template-less договоре).
    deal = await _make_deal(api, counterparty="ООО «ФормаКлиента»")
    inv = await api.post(f"/sales/deals/{deal['id']}/documents", json={"kind": "invoice"})
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
    pkg = await api.get(f"/sales/deals/{deal['id']}/package/render")
    assert pkg.status_code == 200, pkg.text
    assert "Оформлен по форме клиента" in pkg.text


async def test_prepare_contract_duplicate_409(api):
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


async def test_prepare_contract_graceful_unknown_unp(api):
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


async def test_prepare_contract_unknown_template_404(api):
    deal = await _make_deal(api, counterparty="ООО «Аккумулятор»")
    r = await api.post(
        f"/sales/deals/{deal['id']}/contract", json={"template_code": "nope", "unp": ""}
    )
    assert r.status_code == 404


async def test_render_invoice_uses_real_deal_data(api, session):
    """kind=invoice → печатная форма счёта (sales-invoice-template.html), не договор."""
    deal = await _make_deal(api, counterparty="ООО «АвтоЗапчасть»")
    session.add(Sku(code="AKB-77", title="АКБ 6СТ-77", unit="шт"))
    await session.flush()
    sku = (await session.execute(select(Sku).where(Sku.code == "AKB-77"))).scalars().first()
    session.add(DealItem(deal_id=deal["id"], sku_id=sku.id, qty=Decimal("2")))
    session.add(
        PriceQuote(sku_code="AKB-77", counterparty="ООО «АвтоЗапчасть»", price=Decimal("150.00"))
    )
    await session.flush()
    await session.commit()

    inv = await api.post(f"/sales/deals/{deal['id']}/documents", json={"kind": "invoice"})
    assert inv.status_code == 201, inv.text
    doc = inv.json()
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


async def test_render_invoice_without_price_quote_is_zero(api, session):
    """Нет котировки цены — честный ноль, без падения (не demo-данные)."""
    deal = await _make_deal(api, counterparty="ООО «БезЦены»")
    session.add(Sku(code="AKB-88", title="АКБ 6СТ-88", unit="шт"))
    await session.flush()
    sku = (await session.execute(select(Sku).where(Sku.code == "AKB-88"))).scalars().first()
    session.add(DealItem(deal_id=deal["id"], sku_id=sku.id, qty=Decimal("1")))
    await session.flush()
    await session.commit()

    inv = await api.post(f"/sales/deals/{deal['id']}/documents", json={"kind": "invoice"})
    assert inv.status_code == 201, inv.text
    r = await api.get(f"/sales/documents/{inv.json()['id']}/render")
    assert r.status_code == 200, r.text
    assert "АКБ 6СТ-88" in r.text


async def test_render_order_kind_still_400(api):
    """kind=order — не имеет печатной формы; понятная ошибка, не 500."""
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
    deal = await _make_deal(api, counterparty="ООО «Инъекция»")
    session.add(Sku(code="XSS-1", title='<script>alert(1)</script>', unit="шт"))
    await session.flush()
    sku = (await session.execute(select(Sku).where(Sku.code == "XSS-1"))).scalars().first()
    session.add(DealItem(deal_id=deal["id"], sku_id=sku.id, qty=Decimal("1")))
    await session.flush()
    await session.commit()

    inv = await api.post(f"/sales/deals/{deal['id']}/documents", json={"kind": "invoice"})
    r = await api.get(f"/sales/documents/{inv.json()['id']}/render")
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


async def test_render_invoice_includes_uploaded_logo(api, session):
    """Загруженное лого попадает в шапку печатной формы счёта."""
    assert (
        await api.put("/sales/branding", json={"logo_data_url": _TINY_PNG_DATA_URL})
    ).status_code == 200

    deal = await _make_deal(api, counterparty="ООО «СЛого»")
    session.add(Sku(code="AKB-99", title="АКБ 6СТ-99", unit="шт"))
    await session.flush()
    sku = (await session.execute(select(Sku).where(Sku.code == "AKB-99"))).scalars().first()
    session.add(DealItem(deal_id=deal["id"], sku_id=sku.id, qty=Decimal("1")))
    await session.flush()
    await session.commit()

    inv = await api.post(f"/sales/deals/{deal['id']}/documents", json={"kind": "invoice"})
    r = await api.get(f"/sales/documents/{inv.json()['id']}/render")
    assert r.status_code == 200, r.text
    assert f'<img src="{_TINY_PNG_DATA_URL}"' in r.text


async def test_render_invoice_no_logo_block_when_not_uploaded(api, session):
    """Лого не загружено — честно нет <div class="logo"> (не битая картинка)."""
    deal = await _make_deal(api, counterparty="ООО «БезЛого»")
    session.add(Sku(code="AKB-100", title="АКБ 6СТ-100", unit="шт"))
    await session.flush()
    sku = (await session.execute(select(Sku).where(Sku.code == "AKB-100"))).scalars().first()
    session.add(DealItem(deal_id=deal["id"], sku_id=sku.id, qty=Decimal("1")))
    await session.flush()
    await session.commit()

    inv = await api.post(f"/sales/deals/{deal['id']}/documents", json={"kind": "invoice"})
    r = await api.get(f"/sales/documents/{inv.json()['id']}/render")
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
