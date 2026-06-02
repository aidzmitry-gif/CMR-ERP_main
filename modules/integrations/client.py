"""Коннектор к 1С:КА 2.5 (REST/OData).

Реальной 1С в прототипе нет, поэтому при пустом ``base_url`` клиент отдаёт
mock-данные. При заданном URL здесь будут реальные OData-запросы
(``/Catalog_Контрагенты``, регистры остатков и цен) — контракт сохранится.
"""
from __future__ import annotations


class OneCClient:
    def __init__(self, base_url: str = "") -> None:
        self.base_url = base_url

    async def fetch_counterparties(self) -> list[dict]:
        # TODO(part-6): при base_url — реальный OData GET вместо mock
        return [
            {"name": "ООО Аккумулятор", "unp": "191234567"},
            {"name": "ООО МеталлПром", "unp": "190000001"},
            {"name": "АО СтройКомплект", "unp": "190000002"},
        ]

    async def fetch_stock(self) -> list[dict]:
        return [
            {"sku_code": "AKB-60", "title": "Аккумулятор 60 А·ч", "warehouse": "Главный", "qty_available": 120, "qty_reserved": 15, "qty_forecast": 200, "price": 95.0},
            {"sku_code": "AKB-75", "title": "Аккумулятор 75 А·ч", "warehouse": "Главный", "qty_available": 80, "qty_reserved": 10, "qty_forecast": 150, "price": 120.0},
            {"sku_code": "ROLL-5", "title": "Лист горячекатаный 5 мм Ст3сп5 ГОСТ 19903-2015", "warehouse": "Склад-2", "qty_available": 40, "qty_reserved": 5, "qty_forecast": 60, "price": 1500.0},
        ]
