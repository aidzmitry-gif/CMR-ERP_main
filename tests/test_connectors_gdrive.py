"""Юнит-тесты коннектора Google Docs/Sheets (`connectors/gdrive.py`).

Реальные Google API НЕ дёргаются: drive/sheets-клиенты и `MediaIoBaseDownload`
замоканы, ключ сервисного аккаунта не нужен. `__init__` строит google-клиентов
и читает JSON-ключ, поэтому он обходится через ``__new__`` — атрибуты `.drive`,
`.sheets`, `.folder_ids`, `.state` проставляются руками, а реальной остаётся
сама логика `fetch/_fetch_folder/_build_record/_export_doc/_read_sheet`.

Покрытие (трассировка к connectors_spec.md §7.3):
  - FR-32  листинг папок Drive + пагинация через `nextPageToken`;
  - FR-33  инкремент по `modifiedTime` (фильтр в `q` + продвижение курсора папки);
  - FR-34  Google Docs → экспорт в текст (`payload.text`, source="gdoc");
  - FR-35  Google Sheets → значения по листам (`payload.sheets`, source="gsheet"),
           пустой лист → `[]`.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from connectors import gdrive
from connectors.state import StateStore

pytestmark = pytest.mark.unit


# --- хелперы ---------------------------------------------------------------

def _connector(tmp_path, *, drive=None, sheets=None, folder_ids=("F1",)):
    """Собрать GoogleConnector в обход __init__ (без сети и ключа)."""
    conn = gdrive.GoogleConnector.__new__(gdrive.GoogleConnector)
    conn.drive = drive if drive is not None else MagicMock()
    conn.sheets = sheets if sheets is not None else MagicMock()
    conn.folder_ids = list(folder_ids)
    conn.state = StateStore(str(tmp_path / "state.json"))
    return conn


def _doc_meta(file_id="d1", name="Doc 1", mt="2026-06-01T10:00:00.000Z",
              link="https://docs.google.com/d/d1"):
    return {"id": file_id, "name": name, "mimeType": gdrive.DOC_MIME,
            "modifiedTime": mt, "webViewLink": link}


def _sheet_meta(file_id="s1", name="Sheet 1", mt="2026-06-02T10:00:00.000Z",
                link="https://docs.google.com/s/s1"):
    return {"id": file_id, "name": name, "mimeType": gdrive.SHEET_MIME,
            "modifiedTime": mt, "webViewLink": link}


class _FakeDownloader:
    """Подмена googleapiclient MediaIoBaseDownload: один чанк, сразу done.

    Конструктор получает (fd, request) как настоящий; пишет фиксированный текст
    в переданный буфер и возвращает (status, True) — выход из while-цикла.
    """

    EXPORTED = b"Exported doc body\nline two"

    def __init__(self, fd, request):
        self._fd = fd

    def next_chunk(self):
        self._fd.write(self.EXPORTED)
        return (None, True)


# --- FR-32: пагинация через nextPageToken ----------------------------------

def test_fetch_folder_paginates_until_no_token(tmp_path):
    conn = _connector(tmp_path)
    conn._export_doc = lambda fid: f"text:{fid}"  # не качать реальный документ

    page1 = {"files": [_doc_meta("d1")], "nextPageToken": "TOK1"}
    page2 = {"files": [_doc_meta("d2", mt="2026-06-01T11:00:00.000Z")]}  # токена нет → стоп
    conn.drive.files.return_value.list.return_value.execute.side_effect = [page1, page2]

    records = list(conn._fetch_folder("F1"))

    # обе страницы обойдены, обе записи отданы
    assert [r.source_id for r in records] == ["d1", "d2"]
    # ровно два запроса list().execute() — пока был токен, и финальный без токена
    assert conn.drive.files.return_value.list.return_value.execute.call_count == 2
    # первый запрос без pageToken, второй — с токеном первой страницы
    calls = conn.drive.files.return_value.list.call_args_list
    assert calls[0].kwargs["pageToken"] is None
    assert calls[1].kwargs["pageToken"] == "TOK1"


def test_fetch_iterates_all_folders(tmp_path):
    conn = _connector(tmp_path, folder_ids=("F1", "F2"))
    conn._export_doc = lambda fid: f"text:{fid}"
    conn.drive.files.return_value.list.return_value.execute.side_effect = [
        {"files": [_doc_meta("a")]},
        {"files": [_doc_meta("b", mt="2026-06-03T10:00:00.000Z")]},
    ]

    records = list(conn.fetch())

    assert [r.source_id for r in records] == ["a", "b"]


# --- FR-33: инкремент по modifiedTime --------------------------------------

def test_cursor_advances_to_max_modified_time(tmp_path):
    conn = _connector(tmp_path)
    conn._export_doc = lambda fid: "x"
    # вперемешку — курсор должен стать максимумом, а не последним виденным
    conn.drive.files.return_value.list.return_value.execute.side_effect = [{
        "files": [
            _doc_meta("d1", mt="2026-06-01T10:00:00.000Z"),
            _doc_meta("d2", mt="2026-06-05T10:00:00.000Z"),
            _doc_meta("d3", mt="2026-06-03T10:00:00.000Z"),
        ]
    }]

    list(conn._fetch_folder("F1"))

    assert conn.state.get("gdrive_F1_modified") == "2026-06-05T10:00:00.000Z"


def test_existing_cursor_adds_modified_time_filter_to_query(tmp_path):
    conn = _connector(tmp_path)
    conn._export_doc = lambda fid: "x"
    cursor = "2026-06-01T00:00:00.000Z"
    conn.state.set("gdrive_F1_modified", cursor)
    conn.drive.files.return_value.list.return_value.execute.side_effect = [{"files": []}]

    list(conn._fetch_folder("F1"))

    q = conn.drive.files.return_value.list.call_args.kwargs["q"]
    assert f"modifiedTime > '{cursor}'" in q


def test_no_cursor_means_no_modified_time_filter(tmp_path):
    conn = _connector(tmp_path)
    conn.drive.files.return_value.list.return_value.execute.side_effect = [{"files": []}]

    list(conn._fetch_folder("F1"))

    q = conn.drive.files.return_value.list.call_args.kwargs["q"]
    assert "modifiedTime >" not in q
    assert "'F1' in parents" in q  # листинг именно заданной папки


# --- FR-34: Google Docs → экспорт в текст ----------------------------------

def test_build_record_for_doc_exports_text(tmp_path, monkeypatch):
    monkeypatch.setattr(gdrive, "MediaIoBaseDownload", _FakeDownloader)
    conn = _connector(tmp_path)

    rec = conn._build_record(_doc_meta("d42", name="Спека", link="https://x/d42"))

    assert rec.source == "gdoc"
    assert rec.record_type == "document"
    assert rec.source_id == "d42"
    assert rec.payload["name"] == "Спека"
    assert rec.payload["text"] == _FakeDownloader.EXPORTED.decode("utf-8")
    assert rec.source_url == "https://x/d42"
    # экспорт запрошен в text/plain
    conn.drive.files.return_value.export_media.assert_called_once()
    assert conn.drive.files.return_value.export_media.call_args.kwargs["mimeType"] == "text/plain"


def test_export_doc_concatenates_chunks(tmp_path, monkeypatch):
    """Несколько чанков склеиваются, выход из цикла — по done=True."""
    class _TwoChunk:
        def __init__(self, fd, request):
            self._fd = fd
            self._calls = 0

        def next_chunk(self):
            self._calls += 1
            if self._calls == 1:
                self._fd.write(b"part1-")
                return (None, False)
            self._fd.write(b"part2")
            return (None, True)

    monkeypatch.setattr(gdrive, "MediaIoBaseDownload", _TwoChunk)
    conn = _connector(tmp_path)

    assert conn._export_doc("d1") == "part1-part2"


# --- FR-35: Google Sheets → значения по листам -----------------------------

def test_read_sheet_returns_values_per_sheet(tmp_path):
    conn = _connector(tmp_path)
    spreadsheets = conn.sheets.spreadsheets.return_value
    spreadsheets.get.return_value.execute.return_value = {
        "sheets": [
            {"properties": {"title": "Лист1"}},
            {"properties": {"title": "Лист2"}},
        ]
    }
    spreadsheets.values.return_value.get.return_value.execute.side_effect = [
        {"values": [["a", "b"], ["c"]]},
        {"values": [["1"]]},
    ]

    out = conn._read_sheet("s1")

    assert out == {"Лист1": [["a", "b"], ["c"]], "Лист2": [["1"]]}


def test_build_record_for_sheet(tmp_path):
    conn = _connector(tmp_path)
    spreadsheets = conn.sheets.spreadsheets.return_value
    spreadsheets.get.return_value.execute.return_value = {
        "sheets": [{"properties": {"title": "Data"}}]
    }
    spreadsheets.values.return_value.get.return_value.execute.return_value = {
        "values": [["x"]]
    }

    rec = conn._build_record(_sheet_meta("s7", name="Бюджет"))

    assert rec.source == "gsheet"
    assert rec.record_type == "spreadsheet"
    assert rec.source_id == "s7"
    assert rec.payload["name"] == "Бюджет"
    assert rec.payload["sheets"] == {"Data": [["x"]]}


def test_empty_sheet_yields_empty_list(tmp_path):
    """Edge case: лист без значений (ответ без ключа "values") → [], не падать."""
    conn = _connector(tmp_path)
    spreadsheets = conn.sheets.spreadsheets.return_value
    spreadsheets.get.return_value.execute.return_value = {
        "sheets": [{"properties": {"title": "Пусто"}}]
    }
    spreadsheets.values.return_value.get.return_value.execute.return_value = {}  # нет "values"

    out = conn._read_sheet("s1")

    assert out == {"Пусто": []}


def test_build_record_skips_unknown_mime(tmp_path):
    conn = _connector(tmp_path)
    assert conn._build_record({"id": "x", "name": "n", "mimeType": "image/png"}) is None
