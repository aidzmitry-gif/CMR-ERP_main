"""Smoke-тест живого подключения к Bitrix24 — без скачивания mp3 и без сдвига курсора.

Зачем отдельный модуль: штатный `run.py` гонит ВСЮ историю и качает записи звонков
прямо внутри генератора. Для первой проверки доступа это лишнее. Здесь мы дёргаем
ровно по одной странице каждого источника, печатаем сводку и НИЧЕГО не пишем
(ни inbox, ни media, ни state.json) — портал не нагружаем, повторный прогон безопасен.

Запуск из корня проекта (где лежит пакет connectors/):
    python -m connectors.smoke            # звонки + сделки/контакты/компании
    python -m connectors.smoke calls      # только звонки
    python -m connectors.smoke crm        # только CRM
    python -m connectors.smoke download 5 # РЕАЛЬНО скачать 5 звонков (mp3 + inbox), курсор не двигаем

Требует заполненный BITRIX_WEBHOOK в connectors/.env.
"""
from __future__ import annotations

import os
import sys

from . import config
from .bitrix import BitrixConnector
from .models import RawRecord
from .run import persist
from .state import StateStore

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


def main() -> None:
    if not config.BITRIX_WEBHOOK:
        print("[X] BITRIX_WEBHOOK не задан. Заполни connectors/.env (см. .env.example).")
        sys.exit(1)

    args = [a.lower() for a in sys.argv[1:]]
    # state нужен конструктору, но в режиме проверки/теста мы его не трогаем — путь временный.
    bx = BitrixConnector(config.BITRIX_WEBHOOK, StateStore(config.STATE_FILE), config.MEDIA_DIR)

    portal = config.BITRIX_WEBHOOK.split("/rest/")[0]
    print(f"Портал: {portal}")

    try:
        # Режим реального теста скачивания: `download [N]` (по умолчанию 5).
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
    except Exception as exc:  # noqa: BLE001 — для smoke важно показать причину целиком
        print(f"\n[X] Ошибка обращения к Bitrix24: {exc}")
        print("  Частые причины: неверный URL вебхука, не хватает прав scope "
              "(telephony/crm/user/disk), или нет права «Статистика звонков — Просмотр».")
        sys.exit(1)

    print("\n[OK] Smoke-тест прошёл. Связь и права в порядке — можно делать полный прогон "
          "(python -m connectors.run bitrix).")


if __name__ == "__main__":
    main()
