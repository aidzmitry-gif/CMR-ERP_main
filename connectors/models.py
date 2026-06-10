"""Единая модель сырой записи (до ASR/курирования/эмбеддинга).

Все коннекторы отдают объекты RawRecord. Дальше по конвейеру их забирает
воркер: транскрибирует звонки, нормализует через LLM-куратор, эмбеддит и
кладёт в Qdrant.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RawRecord:
    source: str                       # bitrix_call | bitrix_deal | bitrix_contact | bitrix_company | onec | gdoc | gsheet
    source_id: str                    # уникальный id внутри источника
    record_type: str                  # call | deal | contact | company | document | spreadsheet | 1c_entity
    payload: dict[str, Any]           # структурированные данные источника
    fetched_at: str = field(default_factory=_now_iso)
    media_path: Optional[str] = None  # локальный путь к скачанной записи (для звонков)
    source_url: Optional[str] = None  # ссылка в исходной системе (провенанс)

    @property
    def unit_id(self) -> str:
        """Стабильный сквозной идентификатор. По нему делается дедуп/upsert."""
        return f"{self.source}:{self.source_id}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
