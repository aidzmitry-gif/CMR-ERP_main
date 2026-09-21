"""Read-only 1С-фасады не подменяют финансы демонстрационными данными."""
from datetime import date

from modules.integrations.client import OneCClient


async def test_unmapped_financial_facades_are_honest_empty():
    rows = await OneCClient().fetch_payments()
    assert rows == []
    client = OneCClient()
    assert client.financial_source_available is False
    assert "проверенный" in client.financial_source_reason
    assert await client.fetch_bank_balance("51-1") is None
    assert await client.fetch_balance_sheet(date(2026, 6, 28)) is None


async def test_unmapped_onec_is_not_presented_as_a_payment_reconciliation_source(session):
    from modules.finance.reconcile import reconcile_with_onec

    res = await reconcile_with_onec(session, OneCClient())
    assert res["source_available"] is False
    assert res["only_in_1c"] == []
    assert "проверенный" in res["source_reason"]


async def test_onec_facade_implements_full_protocol(services):
    """Фасад собран при load_modules: все read-методы доступны, fetch_payments НЕ AttributeError."""
    onec = services.onec
    assert onec is not None
    assert await onec.fetch_payments() == []
    assert await onec.fetch_bank_balance("51-1") is None
    assert await onec.fetch_balance_sheet(date(2026, 6, 28)) is None


# ── Круг 5 харднинг: READ-ONLY инвариант 1С read-фасадов ──────────────────────


async def test_reference_mocks_do_not_extend_to_financial_facades_when_base_url_empty():
    """Dev mock remains for references, while financial values stay unknown."""
    c = OneCClient(base_url="")
    assert await c.fetch_counterparties()
    assert await c.fetch_stock()
    assert await c.fetch_payments() == []
    assert await c.fetch_bank_balance("51-1") is None
    assert await c.fetch_balance_sheet(date(2026, 6, 28)) is None


async def test_facades_no_throw_with_unreachable_url():
    """Недостижимый OData URL: фасад НЕ кидает и не блокирует (read-only деградирует, не падает).

    Проверенного OData-маппинга платежей/остатков нет: результат остаётся honest-empty, без
    сетевого вызова и без демонстрационных денежных строк.
    """
    c = OneCClient(base_url="http://127.0.0.1:9/odata")  # порт 9 заведомо закрыт
    assert await c.fetch_payments() == []
    assert await c.fetch_bank_balance("51-1") is None
    assert await c.fetch_balance_sheet(date(2026, 6, 28)) is None


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
