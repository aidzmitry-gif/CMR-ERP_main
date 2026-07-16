"""Коннектор к 1С:КА (REST/OData).

При пустом ``base_url`` — mock (dev/тесты). При заданном URL — OData GET (только чтение)
для контрагентов и остатков/цен; финансовые фасады пока mock (контур DoD — товары/цены).
``post_document`` не пишет в 1С (мастер-данные заморожены).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date

import httpx

log = logging.getLogger("integrations.onec")

_MOCK_COUNTERPARTIES = [
    {"name": "ООО Аккумулятор", "unp": "191234567", "id": "b7e3f1a0-1c00-4a01-9e10-000000000001"},
    {"name": "ООО МеталлПром", "unp": "190000001", "id": "b7e3f1a0-1c00-4a01-9e10-000000000002"},
    {"name": "АО СтройКомплект", "unp": "190000002", "id": "b7e3f1a0-1c00-4a01-9e10-000000000003"},
]

_MOCK_STOCK = [
    {"sku_code": "AKB-60", "title": "Аккумулятор 60 А·ч", "warehouse": "Главный",
     "qty_available": 120, "qty_reserved": 15, "qty_forecast": 200, "price": 95.0, "cost": 70.0},
    {"sku_code": "AKB-75", "title": "Аккумулятор 75 А·ч", "warehouse": "Главный",
     "qty_available": 80, "qty_reserved": 10, "qty_forecast": 150, "price": 120.0, "cost": 92.0},
    {"sku_code": "ROLL-5", "title": "Лист горячекатаный 5 мм Ст3сп5 ГОСТ 19903-2015",
     "warehouse": "Склад-2", "qty_available": 40, "qty_reserved": 5, "qty_forecast": 60,
     "price": 1500.0, "cost": 1230.0},
]

_MOCK_PAYMENTS = [
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

_MOCK_BALANCES = {
    "51-1": {"account_code": "51-1", "name": "Расчётный счёт BYN", "bank": "Беларусбанк",
             "balance": 154300.00, "currency": "BYN", "as_of": "2026-06-28"},
    "52-1": {"account_code": "52-1", "name": "Валютный счёт USD", "bank": "Приорбанк",
             "balance": 21000.00, "currency": "USD", "as_of": "2026-06-28"},
}


class OneCClient:
    def __init__(
        self,
        base_url: str = "",
        username: str = "",
        password: str = "",
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.username = username or ""
        self.password = password or ""
        # Basic-auth уходит открытым текстом по http:// (base64 тривиально снимается). Предупреждаем
        # ровно когда 1С сконфигурирована небезопасно; https не принуждаем — внутренняя файловая ИБ
        # 1С обычно без TLS, форс сломал бы боевой конфиг. Канал держать в доверенной сети/VPN.
        if self.base_url.startswith("http://") and self.username:
            log.warning(
                "1С OData по http:// с логином — учётные данные уходят открытым текстом; "
                "используйте https/VPN или держите соединение в доверенной сети."
            )

    def _live(self) -> bool:
        return bool(self.base_url)

    def _client(self) -> httpx.Client:
        # httpx (уже в requirements) вместо requests: тот НЕ в прод-зависимостях, а этот модуль
        # грузится на старте (ENABLED_MODULES) → top-level import requests уронил бы прод-образ.
        auth = (self.username, self.password) if self.username else None
        return httpx.Client(auth=auth, headers={"Accept": "application/json"}, timeout=60)

    def _get(self, entity: str, params: dict | None = None) -> list[dict]:
        """OData GET page (read-only). Без $filter — файловая ИБ ka_copy его запрещает."""
        url = f"{self.base_url}/{entity}"
        q = {"$format": "json", **(params or {})}
        with self._client() as s:
            resp = s.get(url, params=q)
            resp.raise_for_status()
            return list(resp.json().get("value") or [])

    def _fetch_counterparties_sync(self) -> list[dict]:
        rows = self._get(
            "Catalog_Контрагенты",
            {"$top": "500", "$select": "Ref_Key,Description,НаименованиеПолное,ИНН",
             "$orderby": "Description"},
        )
        out: list[dict] = []
        for row in rows:
            name = (row.get("НаименованиеПолное") or row.get("Description") or "").strip()
            unp = (row.get("ИНН") or "").strip() or None
            ref = str(row.get("Ref_Key") or "")
            if not name or not ref:
                continue
            out.append({"name": name[:256], "unp": unp, "id": ref})
        return out

    def _fetch_stock_sync(self) -> list[dict]:
        """Номенклатура + цена из регистра цен (если доступен) / без остатков склада.

        Опубликованный OData ``ka_copy`` (2026-07): есть ``Catalog_Номенклатура``,
        ``InformationRegister_ЦеныНоменклатуры``; остатки/себес-регистры — НЕ опубликованы.
        qty_* = 0 (честно), cost = None, price — последняя ненулевая Цена из RecordSet.
        """
        skus = self._get(
            "Catalog_Номенклатура",
            {"$top": "1000", "$select": "Ref_Key,Code,Description", "$orderby": "Code"},
        )
        by_ref: dict[str, dict] = {}
        for row in skus:
            code = (row.get("Code") or "").strip()
            ref = str(row.get("Ref_Key") or "")
            if not code or not ref:
                continue
            by_ref[ref] = {
                "sku_code": code,
                "title": (row.get("Description") or code)[:255],
                "warehouse": "Главный",
                "qty_available": 0,
                "qty_reserved": 0,
                "qty_forecast": 0,
                "price": 0.0,
                "cost": None,
            }

        # Цены: корневой набор отдаёт Recorder + RecordSet (строки с Номенклатура_Key, Цена).
        try:
            price_docs = self._get("InformationRegister_ЦеныНоменклатуры", {"$top": "200"})
        except Exception as exc:  # noqa: BLE001 — fail-soft, цены опциональны
            log.warning("1C prices register unavailable: %s", exc)
            price_docs = []

        latest: dict[str, float] = {}
        for doc in price_docs:
            for line in doc.get("RecordSet") or []:
                ref = str(line.get("Номенклатура_Key") or "")
                try:
                    price = float(line.get("Цена") or 0)
                except (TypeError, ValueError):
                    continue
                if not ref or price <= 0:
                    continue
                latest[ref] = price  # последняя страница ≈ актуальные; достаточно для sync

        for ref, price in latest.items():
            if ref in by_ref:
                by_ref[ref]["price"] = price

        return list(by_ref.values())

    async def fetch_counterparties(self) -> list[dict]:
        if not self._live():
            return list(_MOCK_COUNTERPARTIES)
        try:
            return await asyncio.to_thread(self._fetch_counterparties_sync)
        except Exception as exc:  # noqa: BLE001
            log.warning("1C fetch_counterparties failed (%s) — empty", exc)
            return []

    async def fetch_stock(self) -> list[dict]:
        if not self._live():
            return list(_MOCK_STOCK)
        try:
            return await asyncio.to_thread(self._fetch_stock_sync)
        except Exception as exc:  # noqa: BLE001
            log.warning("1C fetch_stock failed (%s) — empty", exc)
            return []

    async def fetch_payments(self) -> list[dict]:
        """Платежи — mock до публикации платёжных документов в OData."""
        return list(_MOCK_PAYMENTS)

    async def fetch_bank_balance(self, account_code: str) -> dict | None:
        return _MOCK_BALANCES.get(account_code)

    async def fetch_balance_sheet(self, on_date: date) -> dict | None:
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
        """Исходящая ERP→1С (часть 9). Не OData POST в живую 1С — mock-ссылка."""
        return {"ref": f"1С-{payload.get('number', '')}", "posted": True}
