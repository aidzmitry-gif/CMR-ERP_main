"""Справочник перевозчиков для доставки по РБ (office-карточка → Логистика).

Каталог конвенциональный (прототип, без AI). AI-подбор оптимального перевозчика —
Итерация 1 (см. ТЗ §6.1). Здесь — только статичный список и хелпер выборки.
"""
from __future__ import annotations

# Перевозчики, доступные для доставки по Беларуси.
CARRIERS: list[dict] = [
    {"id": "cdek",       "name": "СДЭК",            "type": "Экспресс-доставка",      "rating": 4.8, "eta": "1–2 дня",   "price_from": 45, "zone": "вся РБ",          "heavy": False},
    {"id": "evropochta", "name": "Европочта",       "type": "Курьер · сеть ПВЗ",       "rating": 4.6, "eta": "1–3 дня",   "price_from": 28, "zone": "вся РБ",          "heavy": False},
    {"id": "belpochta",  "name": "Белпочта",        "type": "Посылки · EMS",           "rating": 4.2, "eta": "2–4 дня",   "price_from": 18, "zone": "вся РБ",          "heavy": False},
    {"id": "dellin",     "name": "Деловые Линии",   "type": "Сборный груз · LTL",      "rating": 4.7, "eta": "1–2 дня",   "price_from": 95, "zone": "вся РБ",          "heavy": True},
    {"id": "dpd",        "name": "DPD",             "type": "Экспресс · палеты",       "rating": 4.5, "eta": "1–2 дня",   "price_from": 52, "zone": "вся РБ",          "heavy": True},
    {"id": "own",        "name": "Свой транспорт",  "type": "Тент 5 т · день в день",  "rating": 4.9, "eta": "день в день", "price_from": 0,  "zone": "Минск + область", "heavy": True},
]

_BY_ID = {c["id"]: c for c in CARRIERS}


def get_carrier(carrier_id: str) -> dict | None:
    """Перевозчик по идентификатору либо ``None``."""
    return _BY_ID.get(carrier_id)
