"""Коннектор Google Docs и Google Sheets.

Доступ через сервисный аккаунт (JSON-ключ). Чтобы аккаунт видел документы,
есть два пути:
  1) расшарить нужные папки/файлы на e-mail сервисного аккаунта, либо
  2) включить domain-wide delegation в Google Workspace и имперсонировать
     пользователя (параметр impersonate).

Тянет из заданных папок (folder_ids):
  - Google Docs -> экспорт в текст;
  - Google Sheets -> значения по всем листам.
Инкрементально по modifiedTime.
"""
from __future__ import annotations

import io
import logging
from typing import Any, Iterator, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from .models import RawRecord

log = logging.getLogger("connectors.gdrive")

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]
DOC_MIME = "application/vnd.google-apps.document"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"


class GoogleConnector:
    def __init__(
        self,
        credentials_file: str,
        folder_ids: list[str],
        state,
        impersonate: Optional[str] = None,
    ) -> None:
        creds = service_account.Credentials.from_service_account_file(
            credentials_file, scopes=SCOPES
        )
        if impersonate:
            creds = creds.with_subject(impersonate)
        self.drive = build("drive", "v3", credentials=creds, cache_discovery=False)
        self.sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
        self.folder_ids = folder_ids
        self.state = state

    def fetch(self) -> Iterator[RawRecord]:
        for folder_id in self.folder_ids:
            yield from self._fetch_folder(folder_id)

    def _fetch_folder(self, folder_id: str) -> Iterator[RawRecord]:
        cursor_key = f"gdrive_{folder_id}_modified"
        last = self.state.get(cursor_key)
        query = (
            f"'{folder_id}' in parents and trashed=false and "
            f"(mimeType='{DOC_MIME}' or mimeType='{SHEET_MIME}')"
        )
        if last:
            query += f" and modifiedTime > '{last}'"

        page_token = None
        while True:
            resp = self.drive.files().list(
                q=query,
                orderBy="modifiedTime",
                fields="nextPageToken, files(id,name,mimeType,modifiedTime,webViewLink)",
                pageSize=100,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
            for meta in resp.get("files", []):
                record = self._build_record(meta)
                if record:
                    yield record
                mt = meta.get("modifiedTime")
                if mt and (last is None or mt > last):
                    last = mt
                    self.state.set(cursor_key, last)
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

    def _build_record(self, meta: dict) -> Optional[RawRecord]:
        mime = meta["mimeType"]
        if mime == DOC_MIME:
            text = self._export_doc(meta["id"])
            return RawRecord(
                source="gdoc",
                source_id=meta["id"],
                record_type="document",
                payload={"name": meta["name"], "text": text, "modifiedTime": meta.get("modifiedTime")},
                source_url=meta.get("webViewLink"),
            )
        if mime == SHEET_MIME:
            sheets = self._read_sheet(meta["id"])
            return RawRecord(
                source="gsheet",
                source_id=meta["id"],
                record_type="spreadsheet",
                payload={"name": meta["name"], "sheets": sheets, "modifiedTime": meta.get("modifiedTime")},
                source_url=meta.get("webViewLink"),
            )
        return None

    def _export_doc(self, file_id: str) -> str:
        # text/plain поддерживается всегда; при желании можно text/markdown
        request = self.drive.files().export_media(fileId=file_id, mimeType="text/plain")
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue().decode("utf-8", errors="replace")

    def _read_sheet(self, spreadsheet_id: str) -> dict[str, Any]:
        meta = self.sheets.spreadsheets().get(
            spreadsheetId=spreadsheet_id, fields="sheets.properties.title"
        ).execute()
        out: dict[str, Any] = {}
        for sheet in meta.get("sheets", []):
            title = sheet["properties"]["title"]
            values = self.sheets.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=title
            ).execute().get("values", [])
            out[title] = values
        return out
