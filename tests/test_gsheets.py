"""Google Sheets gateway: fail-soft wiring and API calls without external network."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from config.settings import get_settings
from core.services import build_services
from core.services.gsheets import GSheetsClient


class FakeWorksheet:
    def __init__(self, rows: list[list[str]] | None = None) -> None:
        self.rows = rows or [["header"], ["value"]]
        self.appended: list[tuple[list[list[object]], str]] = []

    def append_rows(self, rows, *, value_input_option):
        self.appended.append((rows, value_input_option))

    def get_all_values(self):
        return self.rows


class FakeBook:
    def __init__(self) -> None:
        self.sheet1 = FakeWorksheet()
        self.named = FakeWorksheet([["named"]])

    def worksheet(self, name: str):
        assert name == "Лиды"
        return self.named


class FakeGSpread:
    def __init__(self) -> None:
        self.book = FakeBook()
        self.credentials_file = ""
        self.opened_keys: list[str] = []

    def service_account(self, *, filename: str):
        self.credentials_file = filename
        return self

    def open_by_key(self, key: str):
        self.opened_keys.append(key)
        return self.book


def _settings(*, spreadsheet_id: str = "sheet-default") -> SimpleNamespace:
    return SimpleNamespace(
        gsheets_credentials_file="local-service-account.json",
        gsheets_spreadsheet_id=spreadsheet_id,
    )


def test_build_services_without_credentials_keeps_gsheets_disabled(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "gsheets_credentials_file", "")
    assert build_services().gsheets is None


@pytest.mark.asyncio
async def test_gsheets_client_append_and_read_use_requested_sheet(monkeypatch):
    fake = FakeGSpread()
    monkeypatch.setitem(sys.modules, "gspread", fake)
    client = GSheetsClient(_settings())

    await client.append_row(["CRM-1", 10], worksheet="Лиды")
    rows = await client.read_rows(worksheet="Лиды", spreadsheet_id="sheet-override")

    assert fake.credentials_file == "local-service-account.json"
    assert fake.opened_keys == ["sheet-default", "sheet-override"]
    assert fake.book.named.appended == [([["CRM-1", 10]], "USER_ENTERED")]
    assert rows == [["named"]]


@pytest.mark.asyncio
async def test_gsheets_client_requires_spreadsheet_id(monkeypatch):
    fake = FakeGSpread()
    monkeypatch.setitem(sys.modules, "gspread", fake)
    client = GSheetsClient(_settings(spreadsheet_id=""))

    with pytest.raises(RuntimeError, match="Не задан ID таблицы"):
        await client.append_rows([["row"]])
