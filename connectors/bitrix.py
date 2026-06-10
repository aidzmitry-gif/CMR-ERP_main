"""Коннектор облачного Bitrix24 (REST через входящий вебхук).

Тянет:
  - звонки: voximplant.statistic.get + скачивание записи по RECORD_FILE_ID;
  - данные CRM: crm.deal.list / crm.contact.list / crm.company.list.

Инкрементально по курсору ID (фильтр >ID, сортировка ID ASC). Курсор
двигается ТОЛЬКО после того, как потребитель обработал запись (resume-after-yield),
поэтому падение не приводит к пропуску записей. Повторная обработка безопасна
за счёт идемпотентности downstream (upsert по unit_id, пропуск уже скачанного аудио).
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Iterator, Optional

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .models import RawRecord

log = logging.getLogger("connectors.bitrix")


class BitrixTransientError(Exception):
    """Временная ошибка (лимит/5xx) — имеет смысл повторить."""


class BitrixConnector:
    def __init__(
        self,
        webhook_base: str,
        state,
        media_dir: str,
        min_interval: float = 0.5,  # пауза между запросами (мягко под лимиты интенсивности)
    ) -> None:
        self.base = webhook_base.rstrip("/") + "/"
        self.state = state
        self.media_dir = media_dir
        self.min_interval = min_interval
        self._last_call = 0.0
        self.session = requests.Session()

    # --- низкоуровневый вызов метода REST ---

    def _throttle(self) -> None:
        delta = time.monotonic() - self._last_call
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last_call = time.monotonic()

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(6),
        retry=retry_if_exception_type(BitrixTransientError),
        reraise=True,
    )
    def call(self, method: str, params: Optional[dict] = None) -> dict[str, Any]:
        self._throttle()
        resp = self.session.post(self.base + method, json=params or {}, timeout=60)
        if resp.status_code in (429, 500, 502, 503, 504):
            raise BitrixTransientError(f"HTTP {resp.status_code} на {method}")
        data = resp.json()
        if "error" in data:
            err = data.get("error")
            if err in ("QUERY_LIMIT_EXCEEDED", "OVERLOAD_LIMIT"):
                raise BitrixTransientError(err)
            raise RuntimeError(f"Bitrix error {err}: {data.get('error_description')}")
        return data

    def _list(self, method: str, params: Optional[dict] = None) -> Iterator[dict]:
        """Постраничный обход списочного метода (start/next)."""
        params = dict(params or {})
        start = 0
        while True:
            page_params = dict(params)
            page_params["start"] = start
            data = self.call(method, page_params)
            for item in data.get("result", []) or []:
                yield item
            nxt = data.get("next")
            if nxt is None:
                break
            start = nxt

    # --- звонки ---

    def fetch_calls(self) -> Iterator[RawRecord]:
        cursor_key = "bitrix_calls_last_id"
        last_id = int(self.state.get(cursor_key, 0))
        params = {"order": {"ID": "ASC"}, "filter": {">ID": last_id}}
        for call in self._list("voximplant.statistic.get", params):
            call_id = call.get("ID")
            media_path = self._download_record(call)
            yield RawRecord(
                source="bitrix_call",
                source_id=str(call_id),
                record_type="call",
                payload=call,
                media_path=media_path,
                source_url=call.get("CALL_RECORD_URL"),
            )
            # сюда управление возвращается ТОЛЬКО когда потребитель уже сохранил запись
            self.state.set(cursor_key, int(call_id))

    def _download_record(self, call: dict) -> Optional[str]:
        """Скачивает запись звонка. Сначала пробуем прямой URL, затем Disk API.

        ВНИМАНИЕ: имя поля с прямой ссылкой на запись может отличаться от портала
        к порталу (CALL_RECORD_URL встречается не всегда). Если ссылки нет —
        резолвим файл по RECORD_FILE_ID через disk.file.get -> DOWNLOAD_URL.
        """
        url = call.get("CALL_RECORD_URL")
        file_id = call.get("RECORD_FILE_ID")
        if not url and file_id:
            try:
                info = self.call("disk.file.get", {"id": file_id})
                url = (info.get("result") or {}).get("DOWNLOAD_URL")
            except Exception as exc:  # запись могла быть удалена по ротации хранилища
                log.warning("не удалось получить URL записи звонка %s: %s", call.get("ID"), exc)
                url = None
        if not url:
            return None

        os.makedirs(self.media_dir, exist_ok=True)
        path = os.path.join(self.media_dir, f"call_{call.get('ID')}.mp3")
        if os.path.exists(path):  # идемпотентность: уже скачано
            return path
        try:
            with self.session.get(url, stream=True, timeout=180) as r:
                r.raise_for_status()
                tmp = path + ".part"
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)
                os.replace(tmp, path)
            return path
        except Exception as exc:
            log.warning("ошибка скачивания записи звонка %s: %s", call.get("ID"), exc)
            return None

    # --- сущности CRM ---

    def fetch_crm(
        self,
        method: str,
        record_type: str,
        select: Optional[list[str]] = None,
    ) -> Iterator[RawRecord]:
        cursor_key = f"{method}_last_id"
        last_id = int(self.state.get(cursor_key, 0))
        params: dict[str, Any] = {"order": {"ID": "ASC"}, "filter": {">ID": last_id}}
        if select:
            params["select"] = select
        for row in self._list(method, params):
            row_id = row.get("ID")
            yield RawRecord(
                source=f"bitrix_{record_type}",
                source_id=str(row_id),
                record_type=record_type,
                payload=row,
            )
            self.state.set(cursor_key, int(row_id))
