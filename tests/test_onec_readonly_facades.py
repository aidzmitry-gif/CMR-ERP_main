"""Круг 4 — read-only 1С-фасады для финотчётов: fetch_payments/bank_balance/balance_sheet.

READ-ONLY: проверяем форму контракта (согласован с finance) + что OneCClient реализует ВЕСЬ
Protocol (fetch_payments больше не падает AttributeError — DoD). Реальная 1С в прототипе нет →
методы отдают mock (как fetch_counterparties/fetch_stock), реальный OData GET — TODO при base_url.
"""
from datetime import date

from modules.integrations.client import OneCClient


async def test_fetch_payments_shape():
    rows = await OneCClient().fetch_payments()
    assert isinstance(rows, list) and rows
    p = rows[0]
    # ключи сверки finance.reconcile (ref/counterparty_ref/amount) + поля ДДС Р6
    assert {"ref", "counterparty_ref", "amount", "date", "currency", "direction", "account_code"} <= set(p)
    assert all(r["direction"] in ("in", "out") for r in rows)


async def test_payments_match_finance_reconcile_contract(session):
    """Контракт совпадает с потребителем finance.reconcile: ключи ref|counterparty_ref различны
    (не коллапсируют) → 3 платежа видны как 3 (а не 1)."""
    from modules.finance.reconcile import reconcile_with_onec

    res = await reconcile_with_onec(session, OneCClient())
    assert res["source_available"] is True
    assert len(res["only_in_1c"]) == 3  # без сидов ERP все 3 платежа only_in_1c, ключи уникальны


async def test_fetch_bank_balance_found_and_missing():
    c = OneCClient()
    bal = await c.fetch_bank_balance("51-1")
    assert bal is not None and bal["currency"] == "BYN" and bal["balance"] > 0
    assert bal["account_code"] == "51-1"
    assert await c.fetch_bank_balance("НЕТ-СЧЁТА") is None  # не найден → None, не нули


async def test_fetch_balance_sheet_balances():
    bs = await OneCClient().fetch_balance_sheet(date(2026, 6, 28))
    assert bs is not None
    assert bs["on_date"] == "2026-06-28"  # дата нормализуется в ISO
    # баланс сходится: актив == пассив, и итоги == сумме строк
    assert bs["total_assets"] == bs["total_liabilities"]
    assert sum(ln["amount"] for ln in bs["assets"]) == bs["total_assets"]
    assert sum(ln["amount"] for ln in bs["liabilities"]) == bs["total_liabilities"]


async def test_onec_facade_implements_full_protocol(services):
    """Фасад собран при load_modules: все read-методы доступны, fetch_payments НЕ AttributeError."""
    onec = services.onec
    assert onec is not None
    assert await onec.fetch_payments() is not None
    assert await onec.fetch_bank_balance("51-1") is not None
    assert await onec.fetch_balance_sheet(date(2026, 6, 28)) is not None
