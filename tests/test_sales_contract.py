"""SALES-53: договор по шаблону + реквизиты по УНП + пакет «счёт + договор»."""
from decimal import Decimal

from sqlalchemy import select

from core.domain.models import Counterparty, Sku
from modules.sales.models import DealItem

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
