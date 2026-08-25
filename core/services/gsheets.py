"""Шлюз Google Sheets — запись/чтение строк таблицы через сервис-аккаунт.

Симметрично ``llm``: сервис конструируется в ``build_services`` из настроек и
работает fail-soft — без ``AIOS_GSHEETS_CREDENTIALS_FILE`` поле ``Services.gsheets``
остаётся ``None`` (потребитель пропускает экспорт / отдаёт 503), с ключом —
пишет в таблицу. Ядро держит Protocol, любой модуль обращается через
``core.services.gsheets`` (§2.4), не зная про gspread.

Аутентификация — сервис-аккаунт Google Cloud: включить Google Sheets API,
скачать JSON-ключ, выдать email сервис-аккаунта права «Редактор» на таблицу.
``gspread`` синхронный → вызовы обёрнуты в ``asyncio.to_thread`` (не блокируем
event loop). Импорт ленивый — библиотека нужна лишь когда сервис сконфигурирован.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from config.settings import Settings


class GSheetsGateway(Protocol):
    """Добавление и чтение строк листа Google-таблицы.

    ``spreadsheet_id`` — ключ таблицы из её URL (``.../d/<ID>/edit``); ``None`` —
    таблица по умолчанию (``AIOS_GSHEETS_SPREADSHEET_ID``). ``worksheet`` — имя
    листа; ``None`` — первый лист.
    """

    async def append_row(
        self, values: list[Any], *, worksheet: str | None = None,
        spreadsheet_id: str | None = None,
    ) -> None: ...

    async def append_rows(
        self, rows: list[list[Any]], *, worksheet: str | None = None,
        spreadsheet_id: str | None = None,
    ) -> None: ...

    async def read_rows(
        self, *, worksheet: str | None = None, spreadsheet_id: str | None = None,
    ) -> list[list[Any]]: ...


class GSheetsClient:
    """Реализация ``GSheetsGateway`` на ``gspread`` + сервис-аккаунт."""

    def __init__(self, settings: "Settings") -> None:
        self._credentials_file = settings.gsheets_credentials_file
        self._default_spreadsheet = settings.gsheets_spreadsheet_id
        self._gc: Any = None  # ленивый клиент gspread (создаётся при первом вызове)

    def _worksheet(self, worksheet: str | None, spreadsheet_id: str | None) -> Any:
        """Синхронно открыть лист (выполняется в отдельном потоке)."""
        if self._gc is None:
            try:
                import gspread  # ленивый импорт: нужен лишь при сконфигурированном сервисе
            except ImportError as exc:  # pragma: no cover - зависит от окружения
                raise RuntimeError(
                    "Google Sheets требует пакет gspread: pip install gspread"
                ) from exc
            self._gc = gspread.service_account(filename=self._credentials_file)
        key = spreadsheet_id or self._default_spreadsheet
        if not key:
            raise RuntimeError(
                "Не задан ID таблицы: передайте spreadsheet_id или AIOS_GSHEETS_SPREADSHEET_ID."
            )
        sheet = self._gc.open_by_key(key)
        return sheet.worksheet(worksheet) if worksheet else sheet.sheet1

    async def append_row(
        self, values: list[Any], *, worksheet: str | None = None,
        spreadsheet_id: str | None = None,
    ) -> None:
        await self.append_rows([values], worksheet=worksheet, spreadsheet_id=spreadsheet_id)

    async def append_rows(
        self, rows: list[list[Any]], *, worksheet: str | None = None,
        spreadsheet_id: str | None = None,
    ) -> None:
        def _do() -> None:
            ws = self._worksheet(worksheet, spreadsheet_id)
            # USER_ENTERED — как ввод человеком: "2026-07-18" станет датой, числа числами
            ws.append_rows(rows, value_input_option="USER_ENTERED")

        await asyncio.to_thread(_do)

    async def read_rows(
        self, *, worksheet: str | None = None, spreadsheet_id: str | None = None,
    ) -> list[list[Any]]:
        def _do() -> list[list[Any]]:
            return self._worksheet(worksheet, spreadsheet_id).get_all_values()

        return await asyncio.to_thread(_do)
