"""Аудит пригодности данных Bitrix24 для базы знаний по клиентам (вариант B).

НЕ пишет в БД и НЕ качает mp3. Берёт N звонков из voximplant.statistic.get, для каждого
резолвит CRM-привязку (contact/company) и считает статистику: у скольких звонков есть
компания-клиент, у скольких только контакт, у скольких контакт без имени (голый телефон),
у скольких вообще нет CRM-привязки, и у скольких есть запись разговора.

Это дешёвая проверка дорогого предположения: годятся ли данные Bitrix, чтобы строить на них
карточку клиента и рекомендации ИИ, — ДО того как вкладываться в insights/GPU/модуль.

Запуск из корня проекта (нужен BITRIX_WEBHOOK в connectors/.env):
    python -m connectors.audit_calls          # 100 звонков (по умолчанию)
    python -m connectors.audit_calls 300       # 300 звонков
    python -m connectors.audit_calls 200 tail  # 200 последних (свежих) звонков
"""
from __future__ import annotations

import sys
import time
from collections import Counter

import requests

from . import config

PAGE = 50


def _bx(method: str, params: dict) -> dict:
    base = config.BITRIX_WEBHOOK.rstrip("/") + "/"
    last = None
    for attempt in range(3):  # портал на тяжёлом методе бывает медленным/занятым
        try:
            resp = requests.post(base + method, json=params, timeout=120)
            data = resp.json()
            if "error" in data:
                # Бизнес-ошибка (напр. удалённый контакт «Not found») — не сетевая,
                # ретраить незачем; возвращаем пусто, чтобы один битый элемент не валил аудит.
                return {"result": None, "error": data.get("error")}
            return data
        except requests.exceptions.RequestException as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Bitrix {method} недоступен после 3 попыток: {last}")


def _list_calls(limit: int, tail: bool) -> list[dict]:
    """Список звонков. tail=True — самые свежие (ID DESC), иначе с начала истории (ID ASC)."""
    order = {"ID": "DESC"} if tail else {"ID": "ASC"}
    rows: list[dict] = []
    start = 0
    while len(rows) < limit:
        data = _bx("voximplant.statistic.get", {"order": order, "start": start})
        page = data.get("result", []) or []
        if not page:
            break
        rows.extend(page)
        nxt = data.get("next")
        if nxt is None:
            break
        start = nxt
        time.sleep(1.0)  # осторожно: пауза между страницами листинга
    return rows[:limit]


def main() -> None:
    if not config.BITRIX_WEBHOOK:
        print("[X] BITRIX_WEBHOOK не задан (connectors/.env).")
        sys.exit(1)

    args = sys.argv[1:]
    limit = next((int(a) for a in args if a.isdigit()), 100)
    tail = "tail" in args
    print(f"Аудит {limit} звонков ({'свежие' if tail else 'с начала истории'}). "
          "Без записи в БД, без скачивания mp3.\n")

    calls = _list_calls(limit, tail)
    print(f"получено звонков: {len(calls)}\n")

    # кэш резолва, чтобы не дёргать Bitrix повторно по одной сущности
    contact_cache: dict[str, dict] = {}
    company_cache: dict[str, dict] = {}

    stat = Counter()
    examples: dict[str, str] = {}

    for c in calls:
        has_rec = bool(c.get("CALL_RECORD_URL") or c.get("RECORD_FILE_ID"))
        stat["с записью" if has_rec else "без записи"] += 1

        etype = (c.get("CRM_ENTITY_TYPE") or "").upper()
        eid = str(c.get("CRM_ENTITY_ID") or "")
        if not etype or not eid or eid == "0":
            stat["без CRM-привязки"] += 1
            continue

        if etype == "COMPANY":
            if eid not in company_cache:
                company_cache[eid] = _bx("crm.company.get", {"id": eid}).get("result")
            info = company_cache[eid]
            if info is None:
                stat["привязка битая (удалено в Bitrix)"] += 1
            elif info.get("TITLE"):
                stat["привязан к компании"] += 1
                examples.setdefault("компания", info["TITLE"])
            else:
                stat["компания без названия"] += 1
        elif etype == "CONTACT":
            if eid not in contact_cache:
                contact_cache[eid] = _bx("crm.contact.get", {"id": eid}).get("result")
            info = contact_cache[eid]
            if info is None:
                stat["привязка битая (удалено в Bitrix)"] += 1
            else:
                name = " ".join(x for x in (info.get("NAME"), info.get("LAST_NAME")) if x).strip()
                company_id = str(info.get("COMPANY_ID") or "")
                if company_id and company_id != "0":
                    stat["контакт + компания"] += 1
                    examples.setdefault("контакт+компания", f"{name or '?'} / company {company_id}")
                elif name:
                    stat["контакт с именем (без компании)"] += 1
                    examples.setdefault("контакт с именем", name)
                else:
                    stat["контакт без имени (голый телефон)"] += 1
        else:
            stat[f"привязка к {etype}"] += 1
        time.sleep(0.6)  # осторожно: пауза между запросами резолва (мягко под лимит)

    print("=== Привязка к клиенту ===")
    n = len(calls) or 1
    for key in ("привязан к компании", "контакт + компания", "контакт с именем (без компании)",
                "контакт без имени (голый телефон)", "компания без названия",
                "привязка битая (удалено в Bitrix)", "без CRM-привязки"):
        v = stat.get(key, 0)
        print(f"  {key:42s}: {v:4d}  ({v*100//n}%)")
    other = {k: v for k, v in stat.items() if k.startswith("привязка к ")}
    for k, v in other.items():
        print(f"  {k:42s}: {v:4d}  ({v*100//n}%)")

    print("\n=== Запись разговора ===")
    for key in ("с записью", "без записи"):
        v = stat.get(key, 0)
        print(f"  {key:42s}: {v:4d}  ({v*100//n}%)")

    # «годность»: звонок полезен для базы знаний, если есть и клиент, и запись
    usable = stat.get("привязан к компании", 0) + stat.get("контакт + компания", 0) \
        + stat.get("контакт с именем (без компании)", 0)
    print("\n=== Вывод ===")
    print(f"  с идентифицируемым клиентом (компания/контакт с именем): {usable} из {len(calls)} "
          f"({usable*100//n}%)")
    print(f"  уникальных компаний: {sum(1 for i in company_cache.values() if i.get('TITLE'))}, "
          f"уникальных контактов: {len(contact_cache)}")
    if examples:
        print("  примеры:", "; ".join(f"{k}: {v}" for k, v in examples.items()))


if __name__ == "__main__":
    main()
