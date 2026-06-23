"""Конфигурация коннекторов. Значения читаются из переменных окружения / .env."""
from __future__ import annotations

import os

from dotenv import load_dotenv

# Грузим .env, лежащий РЯДОМ с этим файлом (connectors/.env), а не из текущего
# рабочего каталога — иначе при запуске из корня подхватывается чужой корневой .env.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


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
#   date_field — поле даты изменения для инкремента (опционально; у документов обычно "Date")
#   select     — список полей через запятую (опционально, ускоряет выгрузку)
#
# Имена СВЕРЕНЫ по живой базе ka_copy (2026-06-23, КА 2.4, платформа 8.3.18,
# OData http://100.75.171.85/ka_copy/odata/standard.odata/). Цель: досье клиента
# (см. memory client-360-bitrix-1c). Раскомментировать по мере перехода к этапам.
ONEC_ENTITY_SETS: list[dict] = [
    # --- ЭТАП 1 (smoke): клиенты — стартуем с этого ---
    {"name": "Catalog_Контрагенты", "key_field": "Ref_Key"},

    # --- ЭТАП 2. Реквизиты/связи клиента (склейка с Bitrix по УНП) ---
    # {"name": "Catalog_Контрагенты_КонтактнаяИнформация", "key_field": "Ref_Key"},  # таб.часть
    # {"name": "Catalog_ДоговорыКонтрагентов", "key_field": "Ref_Key"},

    # --- ЭТАП 3. История покупок (что/когда/на сколько) — инкремент по дате документа ---
    # {"name": "Document_РеализацияТоваровУслуг", "key_field": "Ref_Key", "date_field": "Date"},
    # {"name": "Document_РеализацияТоваровУслуг_Товары", "key_field": "Ref_Key"},  # позиции (таб.часть)
    # {"name": "Document_ЗаказКлиента", "key_field": "Ref_Key", "date_field": "Date"},
    # {"name": "Document_ЗаказКлиента_Товары", "key_field": "Ref_Key"},

    # --- ЭТАП 4. Деньги / дебиторка ---
    # {"name": "AccumulationRegister_РасчетыСКлиентами", "key_field": "Recorder"},

    # --- ЭТАП 5. Цены ---
    # {"name": "InformationRegister_ЦеныНоменклатуры", "key_field": "Период"},
]

# --- Google ---
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "")  # путь к JSON сервисного аккаунта
GOOGLE_FOLDER_IDS = _split("GOOGLE_FOLDER_IDS")                     # ID папок Drive через запятую
GOOGLE_IMPERSONATE = os.getenv("GOOGLE_IMPERSONATE") or None        # e-mail для domain-wide delegation
