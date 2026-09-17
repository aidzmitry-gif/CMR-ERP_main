from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from modules.sales import routes


def _core_with_seller() -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(
            seller_name="Seller & Co",
            seller_unp="111",
            seller_address="Minsk",
            seller_director="Director <D>",
            seller_phone="+375",
            seller_email="seller@example.com",
            seller_account="BY00",
            seller_bank="Bank",
            seller_bik="BIC",
        )
    )


def test_journal_closed_on_prefers_valid_closed_date_and_falls_back_to_stage_change():
    changed = datetime(2026, 9, 17, 10, 30)
    assert routes._journal_closed_on(SimpleNamespace(closed_date="16.09.2026", stage_changed_at=changed)) == date(
        2026, 9, 16
    )
    assert routes._journal_closed_on(SimpleNamespace(closed_date="31.02.2026", stage_changed_at=changed)) == date(
        2026, 9, 17
    )
    assert routes._journal_closed_on(SimpleNamespace(closed_date="", stage_changed_at=None)) is None


def test_branding_and_seller_facsimile_preserve_honest_empty_and_images():
    assert routes._branding_out(None).model_dump() == {
        "logo_data_url": None,
        "stamp_data_url": None,
        "signature_data_url": None,
    }
    branding = SimpleNamespace(
        logo_data_url="data:image/png;base64,logo",
        stamp_data_url="data:image/png;base64,stamp",
        signature_data_url="data:image/png;base64,sig",
    )
    assert routes._branding_out(branding).model_dump() == vars(branding)

    seller = routes._seller_with_facsimile(_core_with_seller(), None)
    assert seller["logo_data_url"] == ""
    assert seller["stamp_data_url"] is None
    assert seller["signature_data_url"] is None


def test_contract_cover_and_facsimile_escape_untrusted_values():
    seller = routes._seller_with_facsimile(
        _core_with_seller(),
        SimpleNamespace(logo_data_url="", stamp_data_url='stamp"<', signature_data_url='sig"<'),
    )
    doc = SimpleNamespace(
        number="DG-<1>",
        amount=Decimal("12.5"),
        payment_terms="<script>bad()</script>",
        delivery_terms="",
    )
    html = routes._contract_cover_html(doc, seller, {"name": "Buyer <B>"}, "Item <X>")

    assert "data:image" not in html
    assert "&lt;script&gt;bad()&lt;/script&gt;" in html
    assert "Buyer &lt;B&gt;" in html and "Item &lt;X&gt;" in html
    assert 'src="sig&quot;&lt;"' in html
    assert 'src="stamp&quot;&lt;"' in html


def test_invoice_without_deal_rounds_money_and_uses_configured_validity(monkeypatch):
    monkeypatch.setenv("AIOS_INVOICE_VALID_DAYS", "7")
    seller = routes._seller_with_facsimile(_core_with_seller(), None)
    html = routes._render_invoice(
        SimpleNamespace(number="INV-<1>", created_at=None),
        None,
        seller,
        {"name": "Buyer", "unp": "222"},
        [{"name": "Part", "qty": "3", "unit": "шт", "price": "0.335"}],
    )

    assert "INV-&lt;1&gt; от </h1>" in html
    assert "1.01" in html  # 3 × 0.335 rounds to 1.01 before VAT
    assert "1.21" in html  # VAT 0.20 and total 1.21 use Decimal half-up rounding
    assert "заказу клиента № </div>" in html
    assert "в течение 7 банковских дней" in html
