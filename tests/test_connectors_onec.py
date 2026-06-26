"""Юнит-тесты коннектора 1С OData (`connectors/onec.py`) с замоканным HTTP.

Источник 1С в тестах НЕ дёргается: HTTP замокан на двух уровнях —
- логика выгрузки (пагинация/курсор/модель) подменяет `OneCConnector._get`
  на инстансе, перехватывая переданные `params` ($top/$skip/$filter/$orderby);
- устойчивость (NFR-3) проверяется на реальном `_get` с фейковым `Session.get`,
  у которого подменён `.status_code`/`.json()`/`.raise_for_status()`.

Трассировка к ТЗ connectors_spec.md §7.2:
- FR-22 пагинация $top/$skip (стоп по неполной/пустой странице);
- FR-23 инкремент по date_field ($filter + продвижение курсора) и полный
  проход без date_field ($filter не добавляется, курсор не трогается);
- FR-21 модель RawRecord (source/source_id/record_type/payload);
- NFR-3 устойчивость: HTTP 5xx (503) → OneCTransientError.
"""
from __future__ import annotations

import pytest
import requests

pytest.importorskip("connectors.onec")  # опц. зависимость tenacity может отсутствовать — пропускаем

from connectors.onec import OneCConnector, OneCTransientError  # noqa: E402

pytestmark = pytest.mark.unit


# --- тестовые двойники -----------------------------------------------------

class FakeState:
    """Минимальный двойник StateStore: курсоры в памяти (get/set)."""

    def __init__(self, initial: dict | None = None) -> None:
        self.data = dict(initial or {})

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value) -> None:
        self.data[key] = value


class FakeResp:
    """Двойник requests.Response для проверки веток _get по status_code."""

    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def make_conn(entity_sets, state, page_size=500) -> OneCConnector:
    """Конструктор не ходит в сеть: создаёт Session, но запросов не шлёт."""
    return OneCConnector(
        base_url="http://1c.local/base/odata/standard.odata/",
        username="u",
        password="p",
        entity_sets=entity_sets,
        state=state,
        page_size=page_size,
    )


def paged_get(pages_by_skip: dict[int, list], captured: list):
    """Фейк self._get: отдаёт страницу по значению $skip, копит params."""

    def _get(url, params):
        captured.append(dict(params))
        return {"value": pages_by_skip.get(params["$skip"], [])}

    return _get


# --- FR-22: пагинация $top/$skip -------------------------------------------

def test_pagination_walks_top_skip_until_partial_page():
    """Полные страницы → идём дальше по $skip; неполная страница → стоп."""
    captured: list = []
    pages = {
        0: [{"Ref_Key": "A"}, {"Ref_Key": "B"}],   # полная (==page_size) → дальше
        2: [{"Ref_Key": "C"}, {"Ref_Key": "D"}],   # полная → дальше
        4: [{"Ref_Key": "E"}],                       # неполная (<page_size) → стоп
    }
    conn = make_conn([], FakeState(), page_size=2)
    conn._get = paged_get(pages, captured)

    records = list(conn._fetch_entity({"name": "Catalog_Items"}))

    assert len(records) == 5
    # минимум 2 страницы; $skip продвигается на число отданных строк
    assert [p["$skip"] for p in captured] == [0, 2, 4]
    assert all(p["$top"] == 2 for p in captured)
    assert all(p["$format"] == "json" for p in captured)


def test_pagination_stops_on_empty_value_page():
    """Стоп-ветка по пустому value (страница ровно кратна page_size)."""
    captured: list = []
    pages = {
        0: [{"Ref_Key": "A"}, {"Ref_Key": "B"}],
        2: [{"Ref_Key": "C"}, {"Ref_Key": "D"}],
        4: [],  # пусто → break до выдачи
    }
    conn = make_conn([], FakeState(), page_size=2)
    conn._get = paged_get(pages, captured)

    records = list(conn._fetch_entity({"name": "Catalog_Items"}))

    assert len(records) == 4
    assert [p["$skip"] for p in captured] == [0, 2, 4]


# --- FR-23: инкремент по date_field ($filter + курсор) ---------------------

def test_incremental_applies_filter_and_advances_cursor():
    captured: list = []
    rows = [
        {"Ref_Key": "A", "Date": "2026-01-01T10:00:00"},
        {"Ref_Key": "B", "Date": "2026-02-02T12:00:00"},  # последняя виденная
    ]
    state = FakeState({"onec_Document_Order_cursor": "2025-12-31T00:00:00"})
    conn = make_conn([], state, page_size=5)
    conn._get = paged_get({0: rows}, captured)

    list(conn._fetch_entity({"name": "Document_Order", "date_field": "Date"}))

    # FR-23: при наличии курсора в $filter появляется literal «> последнего»
    assert captured[0]["$filter"] == "Date gt datetime'2025-12-31T00:00:00'"
    assert captured[0]["$orderby"] == "Date"
    # курсор продвинут на последнее виденное значение row[date_field]
    assert state.get("onec_Document_Order_cursor") == "2026-02-02T12:00:00"


def test_incremental_without_existing_cursor_has_no_filter_but_sets_cursor():
    """Первый проход с date_field, но без сохранённого курсора: $filter нет,
    при этом курсор после прохода выставляется (для следующего инкремента)."""
    captured: list = []
    rows = [{"Ref_Key": "A", "Date": "2026-03-03T09:00:00"}]
    state = FakeState()
    conn = make_conn([], state, page_size=5)
    conn._get = paged_get({0: rows}, captured)

    list(conn._fetch_entity({"name": "Document_Order", "date_field": "Date"}))

    assert "$filter" not in captured[0]
    assert state.get("onec_Document_Order_cursor") == "2026-03-03T09:00:00"


# --- FR-23: полный проход без date_field -----------------------------------

def test_full_scan_without_date_field_leaves_filter_and_cursor_untouched():
    captured: list = []
    rows = [{"Ref_Key": "A"}, {"Ref_Key": "B"}]
    # даже если по ключу курсора что-то лежит — без date_field его не трогаем
    state = FakeState({"onec_Catalog_Ref_cursor": "SHOULD_BE_IGNORED"})
    conn = make_conn([], state, page_size=5)
    conn._get = paged_get({0: rows}, captured)

    list(conn._fetch_entity({"name": "Catalog_Ref"}))

    assert "$filter" not in captured[0]
    assert captured[0]["$orderby"] == "Ref_Key"  # сортировка по key_field
    assert state.get("onec_Catalog_Ref_cursor") == "SHOULD_BE_IGNORED"


# --- FR-21: модель RawRecord -----------------------------------------------

def test_record_shape_matches_fr21():
    captured: list = []
    row = {"Ref_Key": "REF-1", "Наименование": "ООО Ромашка"}
    conn = make_conn([{"name": "Catalog_Contra"}], FakeState())
    conn._get = paged_get({0: [row]}, captured)

    records = list(conn.fetch())  # публичный обход entity_sets

    assert len(records) == 1
    rec = records[0]
    assert rec.source == "onec"
    assert rec.source_id == "Catalog_Contra:REF-1"
    assert rec.record_type == "1c_entity"
    assert rec.payload["entity"] == "Catalog_Contra"
    assert rec.payload["Ref_Key"] == "REF-1"
    assert rec.payload["Наименование"] == "ООО Ромашка"
    assert rec.unit_id == "onec:Catalog_Contra:REF-1"


# --- NFR-3: устойчивость к временным ошибкам -------------------------------

def test_get_raises_transient_on_503(monkeypatch):
    """503 → OneCTransientError; ретраи не тормозят тест (пауза заглушена)."""
    conn = make_conn([], FakeState())
    # заглушаем сон tenacity, чтобы 5 попыток не ждали exponential backoff
    monkeypatch.setattr(OneCConnector._get.retry, "sleep", lambda *a, **k: None)

    calls: list = []

    def fake_get(url, params=None, timeout=None):
        calls.append(1)
        return FakeResp(503)

    monkeypatch.setattr(conn.session, "get", fake_get)

    with pytest.raises(OneCTransientError):
        conn._get(conn.base + "Catalog_Items", {"$top": 1})

    assert len(calls) == 5  # stop_after_attempt(5), затем reraise


def test_get_returns_json_on_200(monkeypatch):
    conn = make_conn([], FakeState())
    payload = {"value": [{"Ref_Key": "X"}]}
    monkeypatch.setattr(
        conn.session, "get",
        lambda url, params=None, timeout=None: FakeResp(200, payload),
    )
    assert conn._get(conn.base + "Catalog_Items", {"$top": 1}) == payload


def test_get_raises_http_error_on_non_transient_4xx(monkeypatch):
    """404 — не временная ошибка: поднимается HTTPError, не OneCTransientError."""
    conn = make_conn([], FakeState())
    monkeypatch.setattr(
        conn.session, "get",
        lambda url, params=None, timeout=None: FakeResp(404),
    )
    with pytest.raises(requests.HTTPError):
        conn._get(conn.base + "Catalog_Items", {"$top": 1})
