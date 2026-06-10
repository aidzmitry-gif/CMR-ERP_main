"""Конфигурация коннекторов. Значения читаются из переменных окружения / .env."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _split(env: str, sep: str = ",") -> list[str]:
    raw = os.getenv(env, "").strip()
    return [x.strip() for x in raw.split(sep) if x.strip()]


# --- куда складывать результат ---
DATA_DIR = os.getenv("DATA_DIR", "./data")
INBOX_DIR = os.path.join(DATA_DIR, "inbox")     # очередь сырых записей (по файлу на запись)
MEDIA_DIR = os.path.join(DATA_DIR, "media")     # скачанные записи звонков
STATE_FILE = os.path.join(DATA_DIR, "state.json")

# --- Bitrix24 (облако) ---
# Входящий вебхук: https://ВАШ-ПОРТАЛ.bitrix24.ru/rest/<user_id>/<код>/
BITRIX_WEBHOOK = os.getenv("BITRIX_WEBHOOK", "")

# --- 1C (OData) ---
ONEC_BASE_URL = os.getenv("ONEC_BASE_URL", "")  # .../odata/standard.odata/
ONEC_USER = os.getenv("ONEC_USER", "")
ONEC_PASSWORD = os.getenv("ONEC_PASSWORD", "")

# Список выгружаемых объектов 1С. Зависит от вашей конфигурации — отредактируйте.
#   name       — имя набора сущностей OData (Catalog_*, Document_*, AccumulationRegister_* ...)
#   key_field  — поле ключа (обычно Ref_Key)
#   date_field — поле даты изменения для инкремента (опционально)
#   select     — список полей через запятую (опционально, ускоряет выгрузку)
ONEC_ENTITY_SETS: list[dict] = [
    # {"name": "Catalog_Контрагенты", "key_field": "Ref_Key"},
    # {"name": "Document_РеализацияТоваровУслуг", "key_field": "Ref_Key", "date_field": "Date"},
]

# --- Google ---
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "")  # путь к JSON сервисного аккаунта
GOOGLE_FOLDER_IDS = _split("GOOGLE_FOLDER_IDS")                     # ID папок Drive через запятую
GOOGLE_IMPERSONATE = os.getenv("GOOGLE_IMPERSONATE") or None        # e-mail для domain-wide delegation
