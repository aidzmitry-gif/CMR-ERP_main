"""Юнит-тесты коннектора Bitrix24 (`connectors/bitrix.py`) с замоканным HTTP.

Источник НЕ дёргается: нижний слой (`requests.Session.post/.get`) либо точечно
`BitrixConnector.call`/`_download_record` мокаются под каждый сценарий, а
автозащита `_no_real_network` валит любой случайно не замоканный запрос.

Трассировка к connectors_spec.md §7.1:
  - FR-12 — пагинация `_list()` через start/next до `next is None`;
  - FR-14 / NFR-4 — курсор `fetch_calls()` двигается ТОЛЬКО после yield (resume-after-yield);
  - FR-15 — `fetch_crm()` отдаёт RawRecord с source="bitrix_<type>", курсор `<method>_last_id` растёт;
  - FR-13 / NFR-2 — скачивание записи: прямой URL, фолбэк disk.file.get→DOWNLOAD_URL,
    идемпотентный скип существующего файла;
  - NFR-3 — удалённая/недоступная запись → media_path=None, прогон НЕ падает;
  - FR-16 — 429 / QUERY_LIMIT_EXCEEDED → BitrixTransientError (бэкофилл-паузы заглушены).

Скорость: `min_interval=0` (нет throttle-sleep) + патч `call.retry.sleep` (нет tenacity-бэкоффа).
"""
from __future__ import annotations

import os

import pytest
import requests

from connectors.bitrix import BitrixConnector, BitrixTransientError
from connectors.state import StateStore

pytestmark = pytest.mark.unit


# --- тестовая инфраструктура (фейковые HTTP-ответы, без сети) ---------------


class FakeResp:
    """Фейк ответа `Session.post`: статус + .json()."""

    def __init__(self, status_code: int = 200, json_data: dict | None = None) -> None:
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}

    def json(self) -> dict:
        return self._json


class FakeGetResp:
    """Фейк ответа `Session.get(stream=True)`: контекст-менеджер + потоковое тело."""

    def __init__(self, content: bytes = b"", raise_exc: Exception | None = None) -> None:
        self._content = content
        self._raise = raise_exc

    def __enter__(self) -> "FakeGetResp":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def raise_for_status(self) -> None:
        if self._raise is not None:
            raise self._raise

    def iter_content(self, chunk_size: int):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i : i + chunk_size]


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Страховка: любой НЕ замоканный реальный запрос валит тест (а не уходит в сеть)."""

    def _boom(*args, **kwargs):
        raise AssertionError("реальный HTTP-запрос в тесте — источник не должен дёргаться")

    monkeypatch.setattr(requests.Session, "post", _boom)
    monkeypatch.setattr(requests.Session, "get", _boom)


def make_conn(tmp_path) -> BitrixConnector:
    """Коннектор с реальным StateStore и нулевым throttle (быстрые тесты)."""
    state = StateStore(str(tmp_path / "state.json"))
    return BitrixConnector(
        webhook_base="https://portal.bitrix24.ru/rest/1/secretcode/",
        state=state,
        media_dir=str(tmp_path / "media"),
        min_interval=0,
    )


# --- FR-12: пагинация _list() через start/next ------------------------------


def test_list_walks_pages_until_next_is_none(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)
    pages = {
        0: {"result": [1, 2], "next": 2},
        2: {"result": [3], "next": 4},
        4: {"result": [4]},  # нет "next" → стоп
    }
    seen_starts: list[int] = []

    def fake_call(method, params=None):
        assert method == "voximplant.statistic.get"
        seen_starts.append(params["start"])
        return pages[params["start"]]

    monkeypatch.setattr(conn, "call", fake_call)

    items = list(conn._list("voximplant.statistic.get"))

    assert items == [1, 2, 3, 4]  # все страницы собраны по порядку
    assert seen_starts == [0, 2, 4]  # start продвигался по полю next


def test_list_empty_result_yields_nothing(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)
    monkeypatch.setattr(conn, "call", lambda m, p=None: {"result": []})
    assert list(conn._list("crm.deal.list")) == []


# --- FR-14 / NFR-4: курсор звонков двигается ТОЛЬКО после yield --------------


def test_fetch_calls_cursor_moves_only_after_yield(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)
    monkeypatch.setattr(conn, "call", lambda m, p=None: {"result": [{"ID": "7"}, {"ID": "9"}]})
    monkeypatch.setattr(conn, "_download_record", lambda call: None)

    gen = conn.fetch_calls()

    first = next(gen)
    assert first.source_id == "7"
    # запись отдана потребителю, но управление ещё не вернулось после yield →
    # курсор НЕ должен был сдвинуться (resume-after-yield, защита от пропуска)
    assert conn.state.get("bitrix_calls_last_id", 0) == 0

    second = next(gen)
    assert second.source_id == "9"
    # теперь возврат после первого yield исполнил state.set(7)
    assert conn.state.get("bitrix_calls_last_id") == 7

    with pytest.raises(StopIteration):
        next(gen)
    # после полного прохода курсор = ID последней обработанной записи
    assert conn.state.get("bitrix_calls_last_id") == 9


def test_fetch_calls_builds_rawrecord_and_resumes_from_cursor(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)
    conn.state.set("bitrix_calls_last_id", 20)  # инкрементальный рестарт
    captured: dict = {}

    def fake_call(method, params=None):
        captured["params"] = params
        return {"result": [{"ID": "30", "CALL_RECORD_URL": "https://rec/30.mp3"}]}

    monkeypatch.setattr(conn, "call", fake_call)
    monkeypatch.setattr(conn, "_download_record", lambda call: "media/call_30.mp3")

    recs = list(conn.fetch_calls())

    assert captured["params"]["filter"] == {">ID": 20}  # тянем только новое
    assert captured["params"]["order"] == {"ID": "ASC"}
    assert len(recs) == 1
    rec = recs[0]
    assert rec.source == "bitrix_call"
    assert rec.record_type == "call"
    assert rec.source_id == "30"
    assert rec.media_path == "media/call_30.mp3"
    assert rec.source_url == "https://rec/30.mp3"
    assert rec.payload["ID"] == "30"
    assert conn.state.get("bitrix_calls_last_id") == 30


# --- FR-15: CRM-сущности (source/курсор/select) -----------------------------


def test_fetch_crm_deal_sets_source_and_advances_cursor(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)
    captured: dict = {}

    def fake_call(method, params=None):
        captured["method"] = method
        captured["params"] = params
        return {"result": [{"ID": "100", "TITLE": "Сделка"}, {"ID": "200"}]}

    monkeypatch.setattr(conn, "call", fake_call)

    recs = list(conn.fetch_crm("crm.deal.list", "deal", select=["*", "UF_*"]))

    assert [r.source for r in recs] == ["bitrix_deal", "bitrix_deal"]
    assert [r.record_type for r in recs] == ["deal", "deal"]
    assert [r.source_id for r in recs] == ["100", "200"]
    assert recs[0].payload["TITLE"] == "Сделка"
    # select передаётся в запрос (все стандартные + UF_-поля)
    assert captured["params"]["select"] == ["*", "UF_*"]
    assert captured["params"]["order"] == {"ID": "ASC"}
    assert captured["params"]["filter"] == {">ID": 0}
    # курсор по ключу "<method>_last_id" продвинут до max(ID)
    assert conn.state.get("crm.deal.list_last_id") == 200


def test_fetch_crm_without_select_omits_select_param(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)
    captured: dict = {}

    def fake_call(method, params=None):
        captured["params"] = params
        return {"result": [{"ID": "5"}]}

    monkeypatch.setattr(conn, "call", fake_call)

    list(conn.fetch_crm("crm.contact.list", "contact"))

    assert "select" not in captured["params"]
    assert conn.state.get("crm.contact.list_last_id") == 5


# --- FR-13 / NFR-2: скачивание записи звонка --------------------------------


def test_download_record_direct_url(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)
    captured: dict = {}

    def fake_get(url, stream=False, timeout=None):
        captured["url"] = url
        captured["stream"] = stream
        return FakeGetResp(content=b"audio-bytes")

    monkeypatch.setattr(conn.session, "get", fake_get)

    path = conn._download_record({"ID": "55", "CALL_RECORD_URL": "https://rec/55.mp3"})

    expected = os.path.join(str(tmp_path / "media"), "call_55.mp3")
    assert path == expected
    assert os.path.exists(path)
    with open(path, "rb") as f:
        assert f.read() == b"audio-bytes"
    assert captured["url"] == "https://rec/55.mp3"
    assert captured["stream"] is True
    # временный .part переименован, мусора не осталось
    assert not list((tmp_path / "media").glob("*.part"))


def test_download_record_fallback_disk_file_get(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)

    def fake_call(method, params=None):
        # прямой ссылки нет → резолвим файл через Disk API
        assert method == "disk.file.get"
        assert params == {"id": "FILE99"}
        return {"result": {"DOWNLOAD_URL": "https://disk/dl/99"}}

    monkeypatch.setattr(conn, "call", fake_call)
    captured: dict = {}

    def fake_get(url, stream=False, timeout=None):
        captured["url"] = url
        return FakeGetResp(content=b"x")

    monkeypatch.setattr(conn.session, "get", fake_get)

    path = conn._download_record({"ID": "99", "RECORD_FILE_ID": "FILE99"})

    assert path == os.path.join(str(tmp_path / "media"), "call_99.mp3")
    assert captured["url"] == "https://disk/dl/99"  # скачали по DOWNLOAD_URL из Disk API


def test_download_record_skips_existing_file(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)
    media = tmp_path / "media"
    media.mkdir()
    existing = media / "call_77.mp3"
    existing.write_bytes(b"old-content")

    downloads: list = []

    def fake_get(*args, **kwargs):
        downloads.append(1)
        return FakeGetResp(content=b"new-content")

    monkeypatch.setattr(conn.session, "get", fake_get)

    path = conn._download_record({"ID": "77", "CALL_RECORD_URL": "https://rec/77.mp3"})

    assert path == str(existing)
    assert downloads == []  # идемпотентность: повторно НЕ качаем
    assert existing.read_bytes() == b"old-content"  # файл не перезаписан


# --- NFR-3: устойчивость к недоступной/удалённой записи ----------------------


def test_download_record_no_url_no_file_returns_none(tmp_path):
    conn = make_conn(tmp_path)
    # ни прямой ссылки, ни RECORD_FILE_ID — качать нечего
    assert conn._download_record({"ID": "1"}) is None


def test_download_record_disk_get_failure_is_graceful(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)

    def fake_call(method, params=None):
        raise BitrixTransientError("файл удалён ротацией хранилища")

    monkeypatch.setattr(conn, "call", fake_call)

    called = {"get": False}

    def fake_get(*args, **kwargs):
        called["get"] = True
        return FakeGetResp(content=b"x")

    monkeypatch.setattr(conn.session, "get", fake_get)

    # disk.file.get упал → url=None → media_path=None, прогон НЕ падает
    assert conn._download_record({"ID": "2", "RECORD_FILE_ID": "X"}) is None
    assert called["get"] is False  # до скачивания не дошли


def test_download_record_download_error_is_graceful(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)

    def fake_get(url, stream=False, timeout=None):
        return FakeGetResp(raise_exc=requests.HTTPError("404 Not Found"))

    monkeypatch.setattr(conn.session, "get", fake_get)

    # ошибка на скачивании → None, один плохой элемент не валит прогон
    assert conn._download_record({"ID": "3", "CALL_RECORD_URL": "https://rec/3.mp3"}) is None
    # частично скачанный .part не остаётся
    assert not list((tmp_path / "media").glob("*.part"))


# --- FR-16: устойчивость к лимитам (transient → backoff) --------------------


def test_call_returns_data_on_success(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)

    def fake_post(url, json=None, timeout=None):
        assert url == "https://portal.bitrix24.ru/rest/1/secretcode/voximplant.statistic.get"
        assert json == {"start": 0}
        return FakeResp(json_data={"result": [1], "next": 50})

    monkeypatch.setattr(conn.session, "post", fake_post)

    data = conn.call("voximplant.statistic.get", {"start": 0})
    assert data == {"result": [1], "next": 50}


def test_call_raises_transient_on_http_429(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)
    # заглушаем tenacity-бэкофф, чтобы 6 ретраев прошли мгновенно
    monkeypatch.setattr(conn.call.retry, "sleep", lambda *args, **kwargs: None)

    attempts = {"n": 0}

    def fake_post(*args, **kwargs):
        attempts["n"] += 1
        return FakeResp(status_code=429)

    monkeypatch.setattr(conn.session, "post", fake_post)

    with pytest.raises(BitrixTransientError):
        conn.call("voximplant.statistic.get")
    assert attempts["n"] == 6  # отработал полный цикл ретраев перед reraise


def test_call_raises_transient_on_query_limit_exceeded(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)
    monkeypatch.setattr(conn.call.retry, "sleep", lambda *args, **kwargs: None)

    def fake_post(*args, **kwargs):
        return FakeResp(json_data={"error": "QUERY_LIMIT_EXCEEDED", "error_description": "too fast"})

    monkeypatch.setattr(conn.session, "post", fake_post)

    with pytest.raises(BitrixTransientError):
        conn.call("crm.deal.list")


def test_call_raises_runtime_on_permanent_error(tmp_path, monkeypatch):
    conn = make_conn(tmp_path)

    def fake_post(*args, **kwargs):
        return FakeResp(json_data={"error": "INVALID_TOKEN", "error_description": "bad webhook"})

    monkeypatch.setattr(conn.session, "post", fake_post)

    # не transient → НЕ ретраим, поднимаем RuntimeError сразу
    with pytest.raises(RuntimeError):
        conn.call("crm.deal.list")
