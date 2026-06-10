"""Точка входа: прогоняет коннекторы и складывает записи в inbox/.

Каждая запись пишется отдельным JSON-файлом атомарно (через .tmp + replace),
имя — по unit_id, поэтому повторный прогон перезаписывает тот же файл (идемпотентно).
Дальше эти файлы забирает воркер ASR/курирования/эмбеддинга.

Запуск:
    python -m connectors.run               # все источники
    python -m connectors.run bitrix        # только Bitrix24
    python -m connectors.run onec google    # 1С и Google
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys

from . import config
from .models import RawRecord
from .state import StateStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("connectors")


def _filename(record: RawRecord) -> str:
    digest = hashlib.sha1(record.unit_id.encode("utf-8")).hexdigest()[:16]
    return f"{record.source}_{digest}.json"


def persist(record: RawRecord) -> None:
    os.makedirs(config.INBOX_DIR, exist_ok=True)
    path = os.path.join(config.INBOX_DIR, _filename(record))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(record.to_dict(), f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    log.info("записано %s", record.unit_id)


def run_bitrix(state: StateStore) -> None:
    if not config.BITRIX_WEBHOOK:
        log.warning("BITRIX_WEBHOOK не задан — пропуск Bitrix24")
        return
    from .bitrix import BitrixConnector

    bx = BitrixConnector(config.BITRIX_WEBHOOK, state, config.MEDIA_DIR)
    count = 0
    for rec in bx.fetch_calls():
        persist(rec)
        count += 1
    for method, rtype in (
        ("crm.deal.list", "deal"),
        ("crm.contact.list", "contact"),
        ("crm.company.list", "company"),
    ):
        for rec in bx.fetch_crm(method, rtype, select=["*", "UF_*"]):
            persist(rec)
            count += 1
    log.info("Bitrix24: %d записей", count)


def run_onec(state: StateStore) -> None:
    if not config.ONEC_BASE_URL or not config.ONEC_ENTITY_SETS:
        log.warning("1С не сконфигурирован (ONEC_BASE_URL / ONEC_ENTITY_SETS) — пропуск")
        return
    from .onec import OneCConnector

    oc = OneCConnector(
        config.ONEC_BASE_URL,
        config.ONEC_USER,
        config.ONEC_PASSWORD,
        config.ONEC_ENTITY_SETS,
        state,
    )
    count = 0
    for rec in oc.fetch():
        persist(rec)
        count += 1
    log.info("1С: %d записей", count)


def run_google(state: StateStore) -> None:
    if not config.GOOGLE_CREDENTIALS_FILE or not config.GOOGLE_FOLDER_IDS:
        log.warning("Google не сконфигурирован (GOOGLE_CREDENTIALS_FILE / GOOGLE_FOLDER_IDS) — пропуск")
        return
    from .gdrive import GoogleConnector

    gc = GoogleConnector(
        config.GOOGLE_CREDENTIALS_FILE,
        config.GOOGLE_FOLDER_IDS,
        state,
        impersonate=config.GOOGLE_IMPERSONATE,
    )
    count = 0
    for rec in gc.fetch():
        persist(rec)
        count += 1
    log.info("Google: %d записей", count)


def main() -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    state = StateStore(config.STATE_FILE)
    which = [a.lower() for a in sys.argv[1:]] or ["bitrix", "onec", "google"]
    if "bitrix" in which:
        run_bitrix(state)
    if "onec" in which:
        run_onec(state)
    if "google" in which:
        run_google(state)


if __name__ == "__main__":
    main()
