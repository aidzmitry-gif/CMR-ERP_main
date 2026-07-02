"""Коннектор к 1С:КА 2.5 (REST/OData).

Реальной 1С в прототипе нет, поэтому при пустом ``base_url`` клиент отдаёт
mock-данные. При заданном URL здесь будут реальные OData-запросы
(``/Catalog_Контрагенты``, регистры остатков и цен) — контракт сохранится.
"""
from __future__ import annotations

from datetime import date


class OneCClient:
    def __init__(self, base_url: str = "") -> None:
        self.base_url = base_url

    async def fetch_counterparties(self) -> list[dict]:
        # TODO(part-6): при base_url — реальный OData GET вместо mock.
        # 1С отдаёт Ref_Key (GUID) на каждый элемент справочника — кладём его в ``id``,
        # адаптер фиксирует его как alias-провенанс источника (golden record), чтобы
        # отключение 1С было обратимым без потери связи «наш контрагент ← запись 1С».
        return [
            {"name": "ООО Аккумулятор", "unp": "191234567", "id": "b7e3f1a0-1c00-4a01-9e10-000000000001"},
            {"name": "ООО МеталлПром", "unp": "190000001", "id": "b7e3f1a0-1c00-4a01-9e10-000000000002"},
            {"name": "АО СтройКомплект", "unp": "190000002", "id": "b7e3f1a0-1c00-4a01-9e10-000000000003"},
        ]

    async def fetch_stock(self) -> list[dict]:
        # cost = себестоимость из 1С (demo; реальный OData — регистр себестоимости).
        # Маржа «в наличии» = (price − cost)/price (см. методику цены).
        return [
            {"sku_code": "AKB-60", "title": "Аккумулятор 60 А·ч", "warehouse": "Главный", "qty_available": 120, "qty_reserved": 15, "qty_forecast": 200, "price": 95.0, "cost": 70.0},
            {"sku_code": "AKB-75", "title": "Аккумулятор 75 А·ч", "warehouse": "Главный", "qty_available": 80, "qty_reserved": 10, "qty_forecast": 150, "price": 120.0, "cost": 92.0},
            {"sku_code": "ROLL-5", "title": "Лист горячекатаный 5 мм Ст3сп5 ГОСТ 19903-2015", "warehouse": "Склад-2", "qty_available": 40, "qty_reserved": 5, "qty_forecast": 60, "price": 1500.0, "cost": 1230.0},
        ]

    async def fetch_payments(self) -> list[dict]:
        """Платёжные документы из 1С (банк) — read-only, для сверки финансов + ДДС (FIN-C4/Р6).

        Контракт совпадает с УЖЕ существующим потребителем ``finance.reconcile`` (ключ сверки —
        ``ref`` + ``counterparty_ref``): ``ref`` (ссылка на счёт/документ, матч с ERP ``Payment.ref``),
        ``counterparty_ref`` (матч контрагента), ``amount`` (float). Доп. поля для ДДС Р6: ``id``
        (Ref_Key 1С), ``doc_number``, ``date`` (ISO), ``currency``, ``direction`` (``in``/``out``),
        ``account_code`` (банк-счёт, совпадает с ``fetch_bank_balance``), ``bank``, ``counterparty``
        (имя), ``unp``, ``purpose``. # TODO(part-6): при base_url — реальный OData GET
        (``Document_ПлатёжноеПоручениеВходящее``/``Исходящее``) вместо mock; контракт сохранится.
        """
        return [
            {"id": "c1f0-0001", "ref": "СЧ-1", "counterparty_ref": "ООО Аккумулятор",
             "doc_number": "ПП-00123", "date": "2026-06-20", "amount": 12500.00, "currency": "BYN",
             "direction": "in", "account_code": "51-1", "bank": "Беларусбанк",
             "counterparty": "ООО Аккумулятор", "unp": "191234567", "purpose": "Оплата по счёту СЧ-1"},
            {"id": "c1f0-0002", "ref": "СЧ-2", "counterparty_ref": "ООО МеталлПром",
             "doc_number": "ПП-00124", "date": "2026-06-21", "amount": 8400.00, "currency": "BYN",
             "direction": "out", "account_code": "51-1", "bank": "Беларусбанк",
             "counterparty": "ООО МеталлПром", "unp": "190000001", "purpose": "Оплата поставщику"},
            {"id": "c1f0-0003", "ref": "CN-7", "counterparty_ref": "Shenzhen Power Co",
             "doc_number": "ПП-00125", "date": "2026-06-24", "amount": 21000.00, "currency": "USD",
             "direction": "out", "account_code": "52-1", "bank": "Приорбанк",
             "counterparty": "Shenzhen Power Co", "unp": None, "purpose": "Предоплата контракт CN-7"},
        ]

    async def fetch_bank_balance(self, account_code: str) -> dict | None:
        """Остаток по банковскому счёту из 1С — read-only, для ДДС / сверки календаря (Р6).

        Контракт (согласован с finance): ``account_code``, ``name``, ``bank``, ``balance``
        (float), ``currency``, ``as_of`` (ISO-дата). ``None`` — счёт не найден (не нули).
        # TODO(part-6): при base_url — реальный OData GET остатка по счёту (регистр банка).
        """
        balances = {
            "51-1": {"account_code": "51-1", "name": "Расчётный счёт BYN", "bank": "Беларусбанк",
                     "balance": 154300.00, "currency": "BYN", "as_of": "2026-06-28"},
            "52-1": {"account_code": "52-1", "name": "Валютный счёт USD", "bank": "Приорбанк",
                     "balance": 21000.00, "currency": "USD", "as_of": "2026-06-28"},
        }
        return balances.get(account_code)

    async def fetch_balance_sheet(self, on_date: date) -> dict | None:
        """Бухгалтерский баланс из 1С на дату — read-only, для управленческого баланса (Р7).

        Контракт (согласован с finance): ``on_date`` (ISO), ``currency``, ``assets``/
        ``liabilities`` — списки строк ``{code, name, amount}`` (по счетам плана РБ для джойна с
        ERP-балансом, колонка «1С» + дельта), ``total_assets``/``total_liabilities`` (сходятся).
        # TODO(part-6): при base_url — реальный OData GET оборотно-сальдовой на дату вместо mock.
        """
        return {
            "on_date": str(on_date),
            "currency": "BYN",
            "assets": [
                {"code": "01", "name": "Основные средства", "amount": 320000.00},
                {"code": "10", "name": "Материалы", "amount": 85000.00},
                {"code": "41", "name": "Товары", "amount": 240000.00},
                {"code": "51", "name": "Расчётные счета", "amount": 154300.00},
                {"code": "62", "name": "Расчёты с покупателями", "amount": 98000.00},
            ],
            "liabilities": [
                {"code": "60", "name": "Расчёты с поставщиками", "amount": 132000.00},
                {"code": "66", "name": "Краткосрочные кредиты и займы", "amount": 90000.00},
                {"code": "80", "name": "Уставный капитал", "amount": 50000.00},
                {"code": "84", "name": "Нераспределённая прибыль", "amount": 625300.00},
            ],
            "total_assets": 897300.00,
            "total_liabilities": 897300.00,
        }

    async def post_document(self, doc_type: str, payload: dict) -> dict:
        """Записать документ сделки в 1С (счёт/договор/заказ) — часть 9.

        Mock: «1С» возвращает свою ссылку на проведённый документ на основе его
        номера. При заданном ``base_url`` ``doc_type`` выберет нужный документ
        1С (``Document_СчётНаОплату`` и т. п.) для реального OData POST, а контракт
        ответа (``ref``) сохранится.
        """
        # TODO(part-9): при base_url — реальный OData POST в документ типа doc_type
        return {"ref": f"1С-{payload.get('number', '')}", "posted": True}
