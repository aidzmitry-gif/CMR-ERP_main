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


# ── Круг 5 харднинг: READ-ONLY инвариант 1С read-фасадов ──────────────────────


async def test_facades_mock_when_base_url_empty():
    """base_url пуст → mock, без сети, без исключений (dev/прототип)."""
    c = OneCClient(base_url="")
    assert await c.fetch_payments()  # непустой mock
    assert await c.fetch_bank_balance("51-1") is not None
    assert (await c.fetch_balance_sheet(date(2026, 6, 28)))["total_assets"] > 0


async def test_facades_no_throw_with_unreachable_url():
    """Недостижимый OData URL: фасад НЕ кидает и не блокирует (read-only деградирует, не падает).

    Текущая реализация отдаёт mock (реальный OData GET — TODO при подключении 1С); инвариант
    круга 5 — отсутствие исключения/записи, а не «сходить в сеть».
    """
    c = OneCClient(base_url="http://127.0.0.1:9/odata")  # порт 9 заведомо закрыт
    assert await c.fetch_payments() is not None
    assert await c.fetch_bank_balance("51-1") is not None
    assert await c.fetch_balance_sheet(date(2026, 6, 28)) is not None


def test_onec_client_has_no_write_methods():
    """READ-ONLY инвариант: на коннекторе НЕТ patch_/update_/delete_/create_/write_/save_ методов.

    Единственная запись (исходящая ERP→1С) — `post_document` (часть 9); круг 4 read-фасадов НЕ
    добавил write-путей (мастер-данные 1С заморожены, onec-write-frozen).
    """
    writeish = [
        m for m in dir(OneCClient)
        if m.startswith(("patch_", "update_", "delete_", "create_", "write_", "save_", "put_"))
    ]
    assert writeish == []
