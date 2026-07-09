"""Smoke-тест живого подключения к Bitrix24 и 1С — без сдвига прод-курсора.

Зачем отдельный модуль: штатный `run.py` гонит ВСЮ историю и качает записи звонков
прямо внутри генератора. Для первой проверки доступа это лишнее. Здесь мы дёргаем
ровно по одной странице каждого источника, печатаем сводку и НИЧЕГО не пишем
(ни inbox, ни media, ни state.json) — портал не нагружаем, повторный прогон безопасен.

Запуск из корня проекта (где лежит пакет connectors/):
    python -m connectors.smoke            # Bitrix: звонки + CRM
    python -m connectors.smoke calls      # только звонки
    python -m connectors.smoke crm        # только CRM
    python -m connectors.smoke onec       # только 1С OData
    python -m connectors.smoke all        # Bitrix + 1С
    python -m connectors.smoke download 5 # РЕАЛЬНО скачать 5 звонков (mp3 + inbox), курсор не двигаем

Требует заполненный BITRIX_WEBHOOK / ONEC_* в connectors/.env.
"""
from __future__ import annotations

import os
import sys

from . import config
from .bitrix import BitrixConnector
from .models import RawRecord
from .run import persist
from .state import NullStateStore, StateStore

PAGE = 50  # размер страницы voximplant.statistic.get / *.list


def _download(bx: BitrixConnector, limit: int) -> None:
    """Реально собрать первые `limit` звонков: скачать mp3 и записать RawRecord в inbox.

    Тот же путь, что и в проде (bx._download_record + run.persist), но ограниченный
    по числу и БЕЗ сдвига курсора — чтобы тест не «съел» позицию для будущего прогона.
    """
    print(f"\n=== Реальный сбор {limit} звонков (mp3 + inbox) ===")
    data = bx.call("voximplant.statistic.get", {"order": {"ID": "ASC"}, "start": 0})
    rows = (data.get("result", []) or [])[:limit]
    if not rows:
        print("  [!] звонков не получено")
        return
    done = 0
    for call in rows:
        call_id = call.get("ID")
        media_path = bx._download_record(call)  # тот же код скачивания, что в проде
        rec = RawRecord(
            source="bitrix_call",
            source_id=str(call_id),
            record_type="call",
            payload=call,
            media_path=media_path,
            source_url=call.get("CALL_RECORD_URL"),
        )
        persist(rec)
        done += 1
        size = None
        if media_path and os.path.exists(media_path):
            size = os.path.getsize(media_path)
        print(f"  звонок ID={call_id}: mp3={media_path or 'нет записи'}"
              f"{f' ({size} байт)' if size else ''}")
    print(f"\n[OK] Записано {done} звонк(а/ов) в {config.INBOX_DIR}, "
          f"аудио — в {config.MEDIA_DIR}. Курсор НЕ сдвинут (это тест).")


def _check_calls(bx: BitrixConnector) -> None:
    print("\n=== Звонки (voximplant.statistic.get) ===")
    data = bx.call("voximplant.statistic.get", {"order": {"ID": "ASC"}, "start": 0})
    rows = data.get("result", []) or []
    total = data.get("total")
    print(f"получено на 1-й странице: {len(rows)} (total по порталу: {total})")
    has_more = data.get("next") is not None
    print(f"есть следующая страница: {has_more}")
    if not rows:
        print("  [!] пусто — проверь право «Статистика звонков — Просмотр» у пользователя вебхука")
        return
    sample = rows[0]
    rec_url = sample.get("CALL_RECORD_URL")
    file_id = sample.get("RECORD_FILE_ID")
    print(f"  пример звонка: ID={sample.get('ID')} тип={sample.get('CALL_TYPE')} "
          f"длит={sample.get('CALL_DURATION')}с оператор={sample.get('PORTAL_USER_ID')} "
          f"crm={sample.get('CRM_ENTITY_TYPE')}:{sample.get('CRM_ENTITY_ID')}")
    if rec_url:
        print("  запись: прямая ссылка CALL_RECORD_URL присутствует [OK]")
    elif file_id:
        print(f"  запись: прямой ссылки нет, есть RECORD_FILE_ID={file_id} -> "
              "скачивание пойдёт через disk.file.get (фолбэк) [OK]")
    else:
        print("  запись: ни CALL_RECORD_URL, ни RECORD_FILE_ID — у этого звонка записи нет")
    with_rec = sum(1 for r in rows if r.get("CALL_RECORD_URL") or r.get("RECORD_FILE_ID"))
    print(f"  со ссылкой на запись на 1-й странице: {with_rec}/{len(rows)}")


def _check_crm(bx: BitrixConnector, method: str, label: str) -> None:
    print(f"\n=== {label} ({method}) ===")
    data = bx.call(method, {"order": {"ID": "ASC"}, "start": 0, "select": ["*", "UF_*"]})
    rows = data.get("result", []) or []
    total = data.get("total")
    print(f"получено на 1-й странице: {len(rows)} (total по порталу: {total})")
    if rows:
        keys = list(rows[0].keys())
        print(f"  пример: ID={rows[0].get('ID')}; полей в записи: {len(keys)}")


def _check_onec() -> None:
    if not config.ONEC_BASE_URL:
        print("\n[X] ONEC_BASE_URL не задан — пропуск 1С")
        return
    from .onec import OneCConnector

    print(f"\n=== 1С OData ({config.ONEC_BASE_URL}) ===")
    entities = config.ONEC_ENTITY_SETS or [{"name": "Catalog_Контрагенты", "key_field": "Ref_Key"}]
    oc = OneCConnector(
        config.ONEC_BASE_URL,
        config.ONEC_USER,
        config.ONEC_PASSWORD,
        entities,
        NullStateStore(),
        page_size=5,
    )
    for entity in entities:
        name = entity["name"]
        print(f"\n  --- {name} ---")
        try:
            rows = list(oc._fetch_entity(entity, max_rows=3))  # noqa: SLF001 — smoke
            print(f"  получено: {len(rows)} (проба до 3)")
            if rows:
                payload = rows[0].payload
                keys = [k for k in payload.keys() if k != "entity"]
                print(f"  пример ключ={rows[0].source_id}; полей: {len(keys)}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [!] ошибка: {exc}")


def _run_bitrix(args: list[str]) -> None:
    if not config.BITRIX_WEBHOOK:
        print("[X] BITRIX_WEBHOOK не задан. Заполни connectors/.env (см. .env.example).")
        sys.exit(1)

    bx = BitrixConnector(config.BITRIX_WEBHOOK, StateStore(config.STATE_FILE), config.MEDIA_DIR)
    portal = config.BITRIX_WEBHOOK.split("/rest/")[0]
    print(f"Портал: {portal}")

    if args and args[0] == "download":
        limit = int(args[1]) if len(args) > 1 and args[1].isdigit() else 5
        print(f"Режим: DOWNLOAD — реально качаем {limit} звонков и пишем в inbox. "
              "Курсор НЕ двигаем.")
        _download(bx, limit)
        return

    which = args or ["calls", "crm"]
    print("Режим: SMOKE — без скачивания mp3, без записи в inbox/state. Только проверка доступа.")
    if "calls" in which:
        _check_calls(bx)
    if "crm" in which:
        for method, label in (
            ("crm.deal.list", "Сделки"),
            ("crm.contact.list", "Контакты"),
            ("crm.company.list", "Компании"),
        ):
            _check_crm(bx, method, label)


def main() -> None:
    args = [a.lower() for a in sys.argv[1:]]
    if not args:
        args = ["calls", "crm"]

    try:
        if args[0] == "onec":
            _check_onec()
            print("\n[OK] Smoke 1С завершён.")
            return
        if args[0] == "all":
            _run_bitrix(["calls", "crm"])
            _check_onec()
            print("\n[OK] Smoke Bitrix + 1С завершён.")
            return
        if args[0] in ("bitrix", "calls", "crm", "download") or (args and args[0] == "download"):
            _run_bitrix(args if args[0] != "bitrix" else ["calls", "crm"])
            print("\n[OK] Smoke-тест Bitrix прошёл. Связь и права в порядке — "
                  "можно делать тестовую выгрузку (python -m connectors.run --test bitrix).")
            return
        print(f"[X] Неизвестный аргумент: {args[0]}. Используй: calls | crm | onec | all | download [N]")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"\n[X] Ошибка: {exc}")
        print("  Bitrix: неверный URL вебхука, не хватает прав scope "
              "(telephony/crm/user/disk), или нет права «Статистика звонков — Просмотр».")
        print("  1С: проверь ONEC_BASE_URL, логин/пароль и публикацию OData.")
        sys.exit(1)


if __name__ == "__main__":
    main()
