"""Коннектор 1С через стандартный интерфейс OData.

Требует, чтобы в 1С была опубликована стандартная служба OData
(обычно URL вида http://server/base/odata/standard.odata/) и был заведён
пользователь с правами на чтение нужных объектов (HTTP Basic auth).

Состав выгружаемых объектов задаётся списком entity_sets в config.py,
т.к. он зависит от конкретной конфигурации 1С. Для объектов с полем-датой
изменения выгрузка идёт инкрементально; для справочников без такого поля —
полный проход (на ваших объёмах это дёшево, дубли отсекаются ниже по конвейеру).
"""
from __future__ import annotations

import logging
from typing import Any, Iterator, Optional

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .models import RawRecord

log = logging.getLogger("connectors.onec")


class OneCTransientError(Exception):
    pass


class OneCConnector:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        entity_sets: list[dict],
        state,
        page_size: int = 500,
    ) -> None:
        self.base = base_url.rstrip("/") + "/"
        self.entity_sets = entity_sets
        self.state = state
        self.page_size = page_size
        self.session = requests.Session()
        self.session.auth = (username, password)
        self.session.headers.update({"Accept": "application/json"})

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type(OneCTransientError),
        reraise=True,
    )
    def _get(self, url: str, params: dict) -> dict[str, Any]:
        resp = self.session.get(url, params=params, timeout=120)
        if resp.status_code in (429, 500, 502, 503, 504):
            raise OneCTransientError(f"HTTP {resp.status_code}")
        resp.raise_for_status()
        return resp.json()

    def fetch(self, max_rows: int | None = None) -> Iterator[RawRecord]:
        for entity in self.entity_sets:
            entity_limit = entity.get("limit", max_rows)
            yield from self._fetch_entity(entity, max_rows=entity_limit)

    def _fetch_entity(self, entity: dict, max_rows: int | None = None) -> Iterator[RawRecord]:
        name: str = entity["name"]                       # напр. "Catalog_Контрагенты"
        key_field: str = entity.get("key_field", "Ref_Key")
        date_field: Optional[str] = entity.get("date_field")  # напр. "Date" / "DataVersion"
        select: Optional[str] = entity.get("select")
        cursor_key = f"onec_{name}_cursor"
        url = self.base + name

        base_params: dict[str, Any] = {
            "$format": "json",
            "$top": self.page_size,
            "$orderby": date_field or key_field,
        }
        if select:
            base_params["$select"] = select

        last_cursor = self.state.get(cursor_key)
        if date_field and last_cursor:
            # синтаксис литерала даты в фильтре может зависеть от версии платформы 1С
            base_params["$filter"] = f"{date_field} gt datetime'{last_cursor}'"

        yielded = 0
        skip = 0
        while True:
            if max_rows is not None and yielded >= max_rows:
                break
            params = dict(base_params)
            params["$skip"] = skip
            if max_rows is not None:
                params["$top"] = min(self.page_size, max_rows - yielded)
            data = self._get(url, params)
            rows = data.get("value", []) or []
            if not rows:
                break
            for row in rows:
                if max_rows is not None and yielded >= max_rows:
                    return
                row_id = str(row.get(key_field))
                yield RawRecord(
                    source="onec",
                    source_id=f"{name}:{row_id}",
                    record_type="1c_entity",
                    payload={"entity": name, **row},
                )
                yielded += 1
                if date_field and row.get(date_field):
                    self.state.set(cursor_key, row[date_field])
            skip += len(rows)
            if len(rows) < self.page_size:
                break
