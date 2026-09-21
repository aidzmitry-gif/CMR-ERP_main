"""Коннектор к 1С:КА (REST/OData).

При пустом ``base_url`` — mock только для справочников и витрины товаров в dev/тестах.
При заданном URL — OData GET (только чтение) для контрагентов и остатков/цен.
Финансовые read-фасады не используют демонстрационные суммы: пока для них нет
проверенного OData-маппинга, они отдают честное пустое значение. Исходящая запись
документов тоже закрыта до отдельного проверенного адаптера: ``post_document``
не возвращает поддельную ссылку и не пишет в 1С.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from uuid import UUID

import httpx

from core.services.mdm import CounterpartyWriteError

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


class OutboundDocumentUnavailable(RuntimeError):
    """Исходящая запись не имеет проверенного адаптера и не может считаться успешной."""

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

    @property
    def financial_source_available(self) -> bool:
        """No finance OData mapping is verified for this 1C client yet."""
        return False

    @property
    def financial_source_reason(self) -> str:
        return "Для платежей, банковских остатков и баланса 1С не настроен проверенный read-only OData-адаптер"

    @property
    def outbound_document_source_available(self) -> bool:
        """Default client never claims a document was written to 1C."""
        return False

    @property
    def outbound_document_source_reason(self) -> str:
        return "Для исходящих CRM-документов не настроен проверенный адаптер 1С"

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

    def _get_all(self, entity: str, params: dict | None = None, *, page_size: int = 500) -> list[dict]:
        """Постраничный OData GET ($skip/$top) — полный справочник, не только первая страница."""
        base = dict(params or {})
        out: list[dict] = []
        skip = 0
        while True:
            page = self._get(
                entity,
                {**base, "$top": str(page_size), "$skip": str(skip)},
            )
            if not page:
                break
            out.extend(page)
            if len(page) < page_size:
                break
            skip += page_size
        return out

    def _fetch_counterparties_sync(self) -> list[dict]:
        rows = self._get_all(
            "Catalog_Контрагенты",
            {"$select": "Ref_Key,Description,НаименованиеПолное,ИНН,ОбособленноеПодразделение,ГоловнойКонтрагент_Key,КодФилиала",
             "$orderby": "Ref_Key"},
            page_size=500,
        )
        out: list[dict] = []
        for row in rows:
            if not row:
                continue
            is_branch = row.get("ОбособленноеПодразделение")
            if type(is_branch) is not bool:
                raise CounterpartyWriteError("invalid_onec_classification", "1С вернула неоднозначный тип контрагента", 502)
            legal_name = (row.get("НаименованиеПолное") or "").strip() or None
            name = (row.get("Description") or legal_name or "").strip()
            unp = (row.get("ИНН") or "").strip() or None
            ref = str(row.get("Ref_Key") or "")
            if not name or not ref:
                if is_branch:
                    raise CounterpartyWriteError("invalid_onec_identity", "У филиала 1С отсутствует наименование или ID", 502)
                continue
            # Confirmed against the live ka_copy metadata and one branch record.
            # Missing/ambiguous classification must never flatten a branch into a legal entity.
            try:
                source_id = UUID(ref)
                parent_id = UUID(row.get("ГоловнойКонтрагент_Key"))
            except (ValueError, TypeError, AttributeError) as exc:
                raise CounterpartyWriteError("invalid_onec_identity", "1С вернула некорректную ссылку контрагента", 502) from exc
            if not source_id.int or (not is_branch and parent_id.int):
                raise CounterpartyWriteError("invalid_onec_classification", "1С вернула неоднозначный тип контрагента", 502)
            if is_branch:
                if not parent_id.int or parent_id == source_id:
                    raise CounterpartyWriteError("branch_mapping_required", "У филиала 1С отсутствует корректная ссылка на головное предприятие", 422)
                out.append({"id": str(source_id), "record_kind": "branch", "name": name,
                            "parent_external_ref": str(parent_id), "raw_branch_code": row.get("КодФилиала")})
            else:
                out.append({"name": name[:255], "legal_name": legal_name, "unp": unp, "id": str(source_id)})
        return out

    def _fetch_stock_sync(self) -> list[dict]:
        """Номенклатура + цена из регистра цен (если доступен) / без остатков склада.

        Опубликованный OData ``ka_copy`` (2026-07): есть ``Catalog_Номенклатура``,
        ``InformationRegister_ЦеныНоменклатуры``; остатки/себес-регистры — НЕ опубликованы.
        qty_* = 0 (честно), cost = None, price — последняя ненулевая Цена из RecordSet.
        """
        skus = self._get_all(
            "Catalog_Номенклатура",
            {"$select": "Ref_Key,Code,Description", "$orderby": "Code,Ref_Key"},
            page_size=500,
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
            price_docs = self._get_all(
                # $orderby обязателен: без него $skip/$top на файловой ИБ 1С не гарантирует
                # порядок между страницами → пропуск/задвоение записей регистра цен. Period —
                # хронология (делает «последняя страница ≈ актуальная цена» истинной),
                # Recorder — тай-брейк для полного детерминированного порядка.
                "InformationRegister_ЦеныНоменклатуры",
                {"$orderby": "Period,Recorder"},
                page_size=200,
            )
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
        except CounterpartyWriteError:
            raise
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
        """Never substitute a finance source with demonstration payment rows."""
        return []

    async def fetch_bank_balance(self, account_code: str | None = None) -> dict | None:
        """Bank balance is unknown until an explicit source/account mapping is verified."""
        return None

    async def fetch_balance_sheet(self, on_date: date) -> dict | None:
        """Balance is unknown until a verified ledger extract mapping exists."""
        return None

    async def post_document(self, doc_type: str, payload: dict) -> dict:
        """Fail closed until a verified outbound adapter is installed."""
        raise OutboundDocumentUnavailable(self.outbound_document_source_reason)
