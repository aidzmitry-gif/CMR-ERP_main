from __future__ import annotations

import pytest

from modules.integrations.client import OneCClient


def test_get_all_requests_ordered_pages_and_stops_on_short_page(monkeypatch):
    client = OneCClient(base_url="https://1c.example/odata")
    calls: list[tuple[str, dict]] = []

    def fake_get(entity: str, params: dict):
        calls.append((entity, params))
        if params["$skip"] == "0":
            return [{"id": 1}, {"id": 2}]
        return [{"id": 3}]

    monkeypatch.setattr(client, "_get", fake_get)

    assert client._get_all("Catalog_Test", {"$orderby": "Ref_Key"}, page_size=2) == [
        {"id": 1},
        {"id": 2},
        {"id": 3},
    ]
    assert calls == [
        (
            "Catalog_Test",
            {"$orderby": "Ref_Key", "$top": "2", "$skip": "0"},
        ),
        (
            "Catalog_Test",
            {"$orderby": "Ref_Key", "$top": "2", "$skip": "2"},
        ),
    ]


def test_get_all_returns_empty_without_calling_extra_page(monkeypatch):
    client = OneCClient(base_url="https://1c.example/odata")
    calls = []

    def fake_get(entity: str, params: dict):
        calls.append((entity, params))
        return []

    monkeypatch.setattr(client, "_get", fake_get)

    assert client._get_all("Catalog_Test") == []
    assert len(calls) == 1


def test_fetch_counterparties_normalizes_and_skips_incomplete_rows(monkeypatch):
    client = OneCClient(base_url="https://1c.example/odata")

    monkeypatch.setattr(
        client,
        "_get_all",
        lambda entity, params, *, page_size: [
            {"НаименованиеПолное": "  ООО Альфа  ", "ИНН": " 190000001 ", "Ref_Key": "ref-1"},
            {"Description": "Без ИНН", "Ref_Key": "ref-2"},
            {"Description": "Без ссылки", "Ref_Key": ""},
            {"Description": "", "Ref_Key": "ref-3"},
        ],
    )

    assert client._fetch_counterparties_sync() == [
        {"name": "ООО Альфа", "unp": "190000001", "id": "ref-1"},
        {"name": "Без ИНН", "unp": None, "id": "ref-2"},
    ]


def test_fetch_stock_merges_latest_positive_prices_and_keeps_zero_defaults(monkeypatch):
    client = OneCClient(base_url="https://1c.example/odata")

    def fake_get_all(entity, params, *, page_size):
        if entity == "Catalog_Номенклатура":
            return [
                {"Code": " A-1 ", "Ref_Key": "ref-a", "Description": " Alpha "},
                {"Code": "", "Ref_Key": "ref-empty", "Description": "Skip"},
                {"Code": "B-2", "Ref_Key": "", "Description": "Skip"},
            ]
        assert entity == "InformationRegister_ЦеныНоменклатуры"
        return [
            {"RecordSet": [{"Номенклатура_Key": "ref-a", "Цена": "12.50"}]},
            {"RecordSet": [
                {"Номенклатура_Key": "ref-a", "Цена": 0},
                {"Номенклатура_Key": "ref-a", "Цена": "bad"},
                {"Номенклатура_Key": "unknown", "Цена": 88},
            ]},
        ]

    monkeypatch.setattr(client, "_get_all", fake_get_all)

    assert client._fetch_stock_sync() == [
        {
            "sku_code": "A-1",
            "title": " Alpha ",
            "warehouse": "Главный",
            "qty_available": 0,
            "qty_reserved": 0,
            "qty_forecast": 0,
            "price": 12.5,
            "cost": None,
        }
    ]


def test_fetch_stock_fail_soft_when_price_register_is_unavailable(monkeypatch):
    client = OneCClient(base_url="https://1c.example/odata")

    def fake_get_all(entity, params, *, page_size):
        if entity == "Catalog_Номенклатура":
            return [{"Code": "A-1", "Ref_Key": "ref-a", "Description": "Alpha"}]
        raise RuntimeError("register unavailable")

    monkeypatch.setattr(client, "_get_all", fake_get_all)

    rows = client._fetch_stock_sync()
    assert rows[0]["sku_code"] == "A-1"
    assert rows[0]["price"] == 0.0
    assert rows[0]["cost"] is None


@pytest.mark.asyncio
async def test_live_fetch_fails_soft_and_mock_fetches_are_copies(monkeypatch):
    client = OneCClient(base_url="https://1c.example/odata")
    monkeypatch.setattr(client, "_fetch_counterparties_sync", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(client, "_fetch_stock_sync", lambda: (_ for _ in ()).throw(RuntimeError("down")))

    assert await client.fetch_counterparties() == []
    assert await client.fetch_stock() == []

    mock = OneCClient()
    rows = await mock.fetch_counterparties()
    assert rows[0]["name"] == "ООО Аккумулятор"
    assert rows[-1]["id"].endswith("0003")
