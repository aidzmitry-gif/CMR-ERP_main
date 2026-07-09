"""Простое хранилище состояния (курсоры инкрементальной выгрузки).

Хранит JSON-файл с атомарной записью. Этого достаточно, чтобы рестарт
коннектора продолжал с места, а не повторял всё с нуля. Для более жёсткой
идемпотентности на уровне отдельных записей позже можно заменить на SQLite
с таблицей processed(unit_id) + dead-letter.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from typing import Any


class NullStateStore:
    """Хранилище без записи на диск — для smoke/test, курсоры не двигаются."""

    def get(self, key: str, default: Any = None) -> Any:
        return default

    def set(self, key: str, value: Any) -> None:
        pass


class StateStore:
    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        return {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._flush()

    def _flush(self) -> None:
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)  # атомарная подмена
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
