"""Точка входа: прогоняет коннекторы и складывает записи в inbox/.

Каждая запись пишется отдельным JSON-файлом атомарно (через .tmp + replace),
имя — по unit_id, поэтому повторный прогон перезаписывает тот же файл (идемпотентно).
Дальше эти файлы забирает воркер ASR/курирования/эмбеддинга.

Запуск:
    python -m connectors.run               # все источники (прод)
    python -m connectors.run bitrix        # только Bitrix24
    python -m connectors.run onec google    # 1С и Google
    python -m connectors.run --test --limit 20 bitrix onec   # тест без прод-курсоров
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys

from . import config
from .models import RawRecord
from .state import NullStateStore, StateStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("connectors")

_inbox_dir = config.INBOX_DIR


def _filename(record: RawRecord) -> str:
    digest = hashlib.sha1(record.unit_id.encode("utf-8")).hexdigest()[:16]
    return f"{record.source}_{digest}.json"


def persist(record: RawRecord) -> None:
    os.makedirs(_inbox_dir, exist_ok=True)
    path = os.path.join(_inbox_dir, _filename(record))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(record.to_dict(), f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    log.info("записано %s", record.unit_id)


def run_bitrix(state, *, test: bool = False, limit: int = 20) -> None:
    if not config.BITRIX_WEBHOOK:
        log.warning("BITRIX_WEBHOOK не задан — пропуск Bitrix24")
        return
    from .bitrix import BitrixConnector

    bx = BitrixConnector(config.BITRIX_WEBHOOK, state, config.MEDIA_DIR)
    count = 0

    if test:
        log.info("Bitrix24 [test]: CRM по %d записей, productrows по 5 сделкам; звонки пропущены", limit)
        deal_ids: list[int] = []
        for method, rtype in (
            ("crm.deal.list", "deal"),
            ("crm.contact.list", "contact"),
            ("crm.company.list", "company"),
        ):
            for rec in bx.fetch_crm(method, rtype, select=["*", "UF_*"], max_rows=limit):
                persist(rec)
                count += 1
                if rtype == "deal" and len(deal_ids) < 5:
                    deal_ids.append(int(rec.source_id))
        if deal_ids:
            for rec in bx.fetch_productrows(deal_ids):
                persist(rec)
                count += 1
        log.info("Bitrix24 [test]: %d записей", count)
        return

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


def run_onec(state, *, test: bool = False, limit: int = 20) -> None:
    entity_sets = config.ONEC_TEST_ENTITY_SETS if test else config.ONEC_ENTITY_SETS
    if not config.ONEC_BASE_URL or not entity_sets:
        log.warning("1С не сконфигурирован (ONEC_BASE_URL / entity_sets) — пропуск")
        return
    from .onec import OneCConnector

    oc = OneCConnector(
        config.ONEC_BASE_URL,
        config.ONEC_USER,
        config.ONEC_PASSWORD,
        entity_sets,
        state,
    )
    count = 0
    if test:
        for entity in entity_sets:
            single = OneCConnector(
                config.ONEC_BASE_URL,
                config.ONEC_USER,
                config.ONEC_PASSWORD,
                [entity],
                state,
            )
            try:
                for rec in single.fetch():
                    persist(rec)
                    count += 1
            except Exception as exc:
                log.warning("1С %s: пропуск — %s", entity["name"], exc)
    else:
        for rec in oc.fetch():
            persist(rec)
            count += 1
    log.info("1С%s: %d записей", " [test]" if test else "", count)


def run_google(state, *, test: bool = False, limit: int = 20) -> None:
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
        if test and count >= limit:
            break
    log.info("Google%s: %d записей", " [test]" if test else "", count)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Выгрузка сырых данных в data/inbox/")
    parser.add_argument(
        "--test",
        action="store_true",
        help="тестовый прогон: data/inbox/test/, курсоры не двигаются",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="лимит записей на источник/сущность в тестовом режиме (по умолчанию 20)",
    )
    parser.add_argument(
        "sources",
        nargs="*",
        default=["bitrix", "onec", "google"],
        help="bitrix | onec | google",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    global _inbox_dir
    args = parse_args(argv)
    sources = [s.lower() for s in args.sources if not s.startswith("-")]

    os.makedirs(config.DATA_DIR, exist_ok=True)
    if args.test:
        _inbox_dir = config.TEST_INBOX_DIR
        state = NullStateStore()
        log.info(
            "РЕЖИМ ТЕСТ: inbox=%s, курсоры не сохраняются, limit=%d",
            _inbox_dir,
            args.limit,
        )
    else:
        _inbox_dir = config.INBOX_DIR
        state = StateStore(config.STATE_FILE)

    if "bitrix" in sources:
        run_bitrix(state, test=args.test, limit=args.limit)
    if "onec" in sources:
        run_onec(state, test=args.test, limit=args.limit)
    if "google" in sources:
        run_google(state, test=args.test, limit=args.limit)


if __name__ == "__main__":
    main(sys.argv[1:])
